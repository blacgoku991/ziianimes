"""Prix conseillé.

Position assumée, argumentée dans `docs/REVUE_SPEC.md` §1.3 : les prix de
**vente** ne sont pas exposés publiquement par Vinted. Le service repose
donc, par ordre de fiabilité décroissante :

1. sur **l'historique de ventes de l'espace de travail** — la seule donnée
   de vente réelle à laquelle on ait accès, et elle s'enrichit toute seule ;
2. sur une source de marché branchable (`MarketSource`), qui renvoie des
   prix **demandés** et non des prix de vente — l'origine est signalée dans
   la réponse pour que l'interface ne mente pas ;
3. sur le coût d'achat et la marge cible, quand il n'existe aucun
   comparable.

Le prix plancher et la marge cible de l'utilisateur sont appliqués en
dernier, et ils l'emportent toujours sur la statistique.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.catalog import Article
from app.models.enums import Platform, PublicationStatus
from app.models.marketplace import MarketplaceAccount, Publication
from app.models.referential import PriceSuggestion
from app.services import fees

logger = get_logger(__name__)

#: En dessous, l'échantillon ne dit rien de fiable et on le signale.
MIN_RELIABLE_SAMPLE = 5
#: Ancienneté maximale d'une vente retenue comme comparable.
COMPARABLE_MAX_AGE_DAYS = 365


@dataclass
class Comparable:
    price_cents: int
    source: str
    label: str
    sold_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "price_cents": self.price_cents,
            "source": self.source,
            "label": self.label,
            "sold_at": self.sold_at.isoformat() if self.sold_at else None,
        }


class MarketSource(Protocol):
    """Source de comparables externes.

    Toute implémentation doit remplir `source` avec « prix demandés » ou
    « prix de vente » : l'interface affiche cette mention, parce que
    confondre les deux fait conseiller des prix trop élevés.
    """

    def comparables(
        self, *, platform: Platform, brand: str | None, category: str | None, condition: str | None
    ) -> list[Comparable]: ...


@dataclass
class PriceAdvice:
    low_cents: int
    median_cents: int
    high_cents: int
    recommended_cents: int
    floor_cents: int
    sample_size: int
    reliable: bool
    basis: str
    comparables: list[Comparable] = field(default_factory=list)
    margin: dict | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "low_cents": self.low_cents,
            "median_cents": self.median_cents,
            "high_cents": self.high_cents,
            "recommended_cents": self.recommended_cents,
            "floor_cents": self.floor_cents,
            "sample_size": self.sample_size,
            "reliable": self.reliable,
            "basis": self.basis,
            "comparables": [comparable.as_dict() for comparable in self.comparables],
            "margin": self.margin,
            "warnings": self.warnings,
        }


def own_sales_comparables(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    platform: Platform | None,
    brand: str | None,
    category: str | None,
    exclude_article_id: uuid.UUID | None = None,
) -> list[Comparable]:
    """Ventes réellement conclues par ce revendeur, sur des pièces proches."""
    horizon = datetime.now(UTC) - timedelta(days=COMPARABLE_MAX_AGE_DAYS)
    conditions = [
        Publication.workspace_id == workspace_id,
        Publication.status == PublicationStatus.sold,
        Publication.sold_at.is_not(None),
        Publication.sold_at >= horizon,
        Publication.sale_price_cents.is_not(None),
    ]
    statement = (
        sa.select(Publication, Article)
        .join(Article, Article.id == Publication.article_id)
        .where(*conditions)
    )
    if brand:
        statement = statement.where(sa.func.lower(Article.brand) == brand.lower())
    if category:
        statement = statement.where(sa.func.lower(Article.category_label) == category.lower())
    if exclude_article_id:
        statement = statement.where(Article.id != exclude_article_id)
    if platform is not None:
        statement = statement.join(
            MarketplaceAccount, MarketplaceAccount.id == Publication.marketplace_account_id
        ).where(MarketplaceAccount.platform == platform)

    rows = db.execute(statement.order_by(Publication.sold_at.desc()).limit(60)).all()
    return [
        Comparable(
            price_cents=int(publication.sale_price_cents or 0),
            source="ventes_propres",
            label=f"{article.brand or '—'} · {article.category_label or '—'}",
            sold_at=publication.sold_at,
        )
        for publication, article in rows
        if publication.sale_price_cents
    ]


def suggest_price(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article: Article,
    platform: Platform,
    workspace_settings: dict | None = None,
    market_source: MarketSource | None = None,
    persist: bool = True,
) -> PriceAdvice:
    warnings: list[str] = []

    comparables = own_sales_comparables(
        db,
        workspace_id=workspace_id,
        platform=platform,
        brand=article.brand,
        category=article.category_label,
        exclude_article_id=article.id,
    )
    basis = "ventes_propres"

    if len(comparables) < MIN_RELIABLE_SAMPLE:
        # On élargit avant d'abandonner : la marque seule reste un signal.
        broader = own_sales_comparables(
            db,
            workspace_id=workspace_id,
            platform=None,
            brand=article.brand,
            category=None,
            exclude_article_id=article.id,
        )
        if len(broader) > len(comparables):
            comparables = broader
            basis = "ventes_propres_elargies"
            warnings.append(
                "Échantillon élargi à toutes les plateformes et catégories, "
                "faute de ventes comparables assez proches."
            )

    if len(comparables) < MIN_RELIABLE_SAMPLE and market_source is not None:
        external = market_source.comparables(
            platform=platform,
            brand=article.brand,
            category=article.category_label,
            condition=article.condition.value if article.condition else None,
        )
        if external:
            comparables = comparables + external
            basis = "prix_demandes"
            warnings.append(
                "Fourchette calculée sur des prix DEMANDÉS, pas sur des prix de "
                "vente : elle est structurellement optimiste."
            )

    prices = sorted(
        comparable.price_cents for comparable in comparables if comparable.price_cents > 0
    )
    floor_cents = _floor_price(article, platform, workspace_settings)

    if prices:
        low = int(_quantile(prices, 0.25))
        median = int(statistics.median(prices))
        high = int(_quantile(prices, 0.75))
    else:
        basis = "cout_et_marge"
        warnings.append(
            "Aucun comparable : fourchette dérivée du coût d'achat et de la "
            "marge cible. À revoir dès les premières ventes."
        )
        median = floor_cents
        low = int(median * 0.85)
        high = int(median * 1.3)

    recommended = max(median, floor_cents)
    if recommended > median:
        warnings.append("Prix relevé au plancher défini pour cet article.")

    reliable = len(prices) >= MIN_RELIABLE_SAMPLE and basis.startswith("ventes_propres")

    margin = fees.compute_margin(
        platform=platform,
        price_cents=recommended,
        purchase_cost_cents=article.purchase_cost_cents,
        workspace_settings=workspace_settings,
    ).as_dict()
    if margin["margin_cents"] < 0:
        warnings.append("À ce prix, la vente est à perte une fois les frais déduits.")

    advice = PriceAdvice(
        low_cents=max(low, 100),
        median_cents=max(median, 100),
        high_cents=max(high, 100),
        recommended_cents=max(recommended, 100),
        floor_cents=floor_cents,
        sample_size=len(prices),
        reliable=reliable,
        basis=basis,
        comparables=comparables[:20],
        margin=margin,
        warnings=warnings,
    )

    if persist:
        _persist(db, workspace_id=workspace_id, article=article, platform=platform, advice=advice)
    return advice


def _floor_price(article: Article, platform: Platform, workspace_settings: dict | None) -> int:
    """Plancher : le plus contraignant entre le plancher explicite et la marge cible."""
    candidates = [100]
    if article.floor_price_cents:
        candidates.append(article.floor_price_cents)
    if article.target_margin_pct is not None:
        candidates.append(
            fees.price_for_target_margin(
                platform=platform,
                purchase_cost_cents=article.purchase_cost_cents,
                target_margin_pct=article.target_margin_pct,
                workspace_settings=workspace_settings,
            )
        )
    return max(candidates)


def _quantile(sorted_values: list[int], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _persist(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article: Article,
    platform: Platform,
    advice: PriceAdvice,
) -> None:
    existing = db.execute(
        sa.select(PriceSuggestion).where(
            PriceSuggestion.article_id == article.id, PriceSuggestion.platform == platform
        )
    ).scalar_one_or_none()
    payload = {
        "low_cents": advice.low_cents,
        "median_cents": advice.median_cents,
        "high_cents": advice.high_cents,
        "sample_size": advice.sample_size,
        "comparables": [comparable.as_dict() for comparable in advice.comparables],
        "computed_at": datetime.now(UTC),
    }
    if existing is None:
        db.add(
            PriceSuggestion(
                workspace_id=workspace_id, article_id=article.id, platform=platform, **payload
            )
        )
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
    db.flush()


def adjust_for_platform(base_cents: int, platform: Platform) -> int:
    """Ajuste un prix d'une plateforme à l'autre.

    Les niveaux de prix ne sont pas les mêmes : eBay supporte des prix plus
    élevés qu'une friperie en ligne, Leboncoin est plus bas. Ces
    coefficients sont un point de départ à affiner sur les données réelles
    du revendeur.
    """
    factors = {
        Platform.vinted: 1.0,
        Platform.leboncoin: 0.9,
        Platform.depop: 1.1,
        Platform.ebay: 1.15,
    }
    return max(100, int(round(base_cents * factors.get(platform, 1.0))))
