"""Étape 3 — vue de stock.

Le cœur fonctionnel : un tableau où le revendeur voit, par article, où il
en est sur chaque plateforme, ce qu'il a payé, ce qu'il gagnerait, et ce qui
dort depuis trop longtemps.

Toutes les marges passent par `fees.compute_margin` : afficher un prix moins
un coût d'achat, sans les commissions ni le port, donne un chiffre faux qui
oriente mal les décisions d'achat.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.catalog import Article
from app.models.enums import ArticleStatus, Platform, PublicationStatus
from app.models.marketplace import MarketplaceAccount, Publication
from app.services import fees

_LIVE_STATUSES = (
    PublicationStatus.published,
    PublicationStatus.draft_ready,
    PublicationStatus.queued,
    PublicationStatus.running,
)


@dataclass
class PublicationCell:
    """État d'un article sur un compte donné, une case du tableau."""

    publication_id: uuid.UUID
    account_id: uuid.UUID
    account_label: str
    platform: Platform
    status: PublicationStatus
    price_cents: int | None
    remote_url: str | None
    published_at: datetime | None
    views_count: int
    days_online: int | None

    def as_dict(self) -> dict:
        return {
            "publication_id": str(self.publication_id),
            "account_id": str(self.account_id),
            "account_label": self.account_label,
            "platform": self.platform.value,
            "status": self.status.value,
            "price_cents": self.price_cents,
            "remote_url": self.remote_url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "views_count": self.views_count,
            "days_online": self.days_online,
        }


@dataclass
class StockRow:
    article: Article
    publications: list[PublicationCell] = field(default_factory=list)
    photo_count: int = 0
    best_price_cents: int | None = None
    expected_margin_cents: int | None = None
    expected_margin_pct: float | None = None
    days_since_listed: int | None = None
    is_stale: bool = False
    #: Deux annonces actives sur deux comptes de la même plateforme : à
    #: éviter, c'est un des signaux les plus nets de rapprochement de comptes.
    duplicate_platform_warning: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": str(self.article.id),
            "sku": self.article.sku,
            "title": self.article.title,
            "brand": self.article.brand,
            "category_label": self.article.category_label,
            "size_label": self.article.size_label,
            "status": self.article.status.value,
            "purchase_cost_cents": self.article.purchase_cost_cents,
            "currency": self.article.currency,
            "photo_count": self.photo_count,
            "best_price_cents": self.best_price_cents,
            "expected_margin_cents": self.expected_margin_cents,
            "expected_margin_pct": self.expected_margin_pct,
            "days_since_listed": self.days_since_listed,
            "is_stale": self.is_stale,
            "duplicate_platform_warning": self.duplicate_platform_warning,
            "publications": [cell.as_dict() for cell in self.publications],
            "created_at": self.article.created_at.isoformat(),
        }


def stock_table(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    workspace_settings: dict | None = None,
    status: ArticleStatus | None = None,
    platform: Platform | None = None,
    search: str | None = None,
    stale_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[StockRow], int]:
    conditions = [Article.workspace_id == workspace_id, Article.deleted_at.is_(None)]
    if status is not None:
        conditions.append(Article.status == status)
    if search:
        pattern = f"%{search.strip().lower()}%"
        conditions.append(
            sa.or_(
                sa.func.lower(Article.title).like(pattern),
                sa.func.lower(Article.brand).like(pattern),
                sa.func.lower(Article.sku).like(pattern),
                sa.func.lower(Article.category_label).like(pattern),
            )
        )

    total = db.execute(
        sa.select(sa.func.count()).select_from(Article).where(*conditions)
    ).scalar_one()
    articles = list(
        db.execute(
            sa.select(Article)
            .where(*conditions)
            .order_by(Article.created_at.desc())
            .limit(min(limit, 200))
            .offset(max(offset, 0))
        )
        .scalars()
        .all()
    )
    if not articles:
        return [], int(total)

    article_ids = [article.id for article in articles]
    cells = _publication_cells(db, workspace_id=workspace_id, article_ids=article_ids)
    photo_counts = _photo_counts(db, article_ids)

    now = datetime.now(UTC)
    stale_threshold = timedelta(days=settings.stale_listing_days)
    rows: list[StockRow] = []

    for article in articles:
        article_cells = cells.get(article.id, [])
        if platform is not None:
            article_cells = [cell for cell in article_cells if cell.platform == platform]
            if not article_cells:
                continue

        row = StockRow(
            article=article,
            publications=article_cells,
            photo_count=photo_counts.get(article.id, 0),
        )
        live = [cell for cell in article_cells if cell.status in _LIVE_STATUSES]
        prices = [cell.price_cents for cell in live if cell.price_cents]
        if prices:
            row.best_price_cents = max(prices)
            reference_platform = next(
                (cell.platform for cell in live if cell.price_cents == row.best_price_cents),
                Platform.vinted,
            )
            margin = fees.compute_margin(
                platform=reference_platform,
                price_cents=row.best_price_cents,
                purchase_cost_cents=article.purchase_cost_cents,
                workspace_settings=workspace_settings,
            )
            row.expected_margin_cents = margin.margin_cents
            row.expected_margin_pct = margin.margin_pct

        if article.first_listed_at:
            row.days_since_listed = (now - article.first_listed_at).days
            row.is_stale = (
                article.status in (ArticleStatus.listed, ArticleStatus.draft)
                and (now - article.first_listed_at) > stale_threshold
            )

        row.duplicate_platform_warning = _duplicate_platforms(live)

        if stale_only and not row.is_stale:
            continue
        rows.append(row)

    return rows, int(total)


def _duplicate_platforms(live_cells: list[PublicationCell]) -> list[str]:
    seen: dict[Platform, int] = {}
    for cell in live_cells:
        seen[cell.platform] = seen.get(cell.platform, 0) + 1
    return [platform.value for platform, count in seen.items() if count > 1]


def _publication_cells(
    db: Session, *, workspace_id: uuid.UUID, article_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[PublicationCell]]:
    rows = db.execute(
        sa.select(Publication, MarketplaceAccount)
        .join(MarketplaceAccount, MarketplaceAccount.id == Publication.marketplace_account_id)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.article_id.in_(article_ids),
        )
        .order_by(MarketplaceAccount.platform, MarketplaceAccount.label)
    ).all()

    now = datetime.now(UTC)
    grouped: dict[uuid.UUID, list[PublicationCell]] = {}
    for publication, account in rows:
        days_online = (now - publication.published_at).days if publication.published_at else None
        grouped.setdefault(publication.article_id, []).append(
            PublicationCell(
                publication_id=publication.id,
                account_id=account.id,
                account_label=account.label,
                platform=account.platform,
                status=publication.status,
                price_cents=publication.price_cents,
                remote_url=publication.remote_url,
                published_at=publication.published_at,
                views_count=publication.views_count,
                days_online=days_online,
            )
        )
    return grouped


def _photo_counts(db: Session, article_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    from app.models.catalog import ArticlePhoto

    rows = db.execute(
        sa.select(ArticlePhoto.article_id, sa.func.count())
        .where(ArticlePhoto.article_id.in_(article_ids))
        .group_by(ArticlePhoto.article_id)
    ).all()
    return {article_id: int(count) for article_id, count in rows}


@dataclass
class StaleSuggestion:
    article_id: uuid.UUID
    sku: str
    title: str | None
    days_online: int
    current_price_cents: int
    suggested_price_cents: int
    floor_cents: int
    reason: str

    def as_dict(self) -> dict:
        return {
            "article_id": str(self.article_id),
            "sku": self.sku,
            "title": self.title,
            "days_online": self.days_online,
            "current_price_cents": self.current_price_cents,
            "suggested_price_cents": self.suggested_price_cents,
            "floor_cents": self.floor_cents,
            "reason": self.reason,
        }


def stale_listings(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    workspace_settings: dict | None = None,
    days: int | None = None,
) -> list[StaleSuggestion]:
    """Annonces dormantes et baisse de prix proposée.

    La suggestion ne descend jamais sous le plancher de l'article : brader
    sous le prix de revient n'est pas une stratégie de rotation, c'est une
    perte.
    """
    days = days or settings.stale_listing_days
    horizon = datetime.now(UTC) - timedelta(days=days)

    rows = db.execute(
        sa.select(Publication, Article, MarketplaceAccount)
        .join(Article, Article.id == Publication.article_id)
        .join(MarketplaceAccount, MarketplaceAccount.id == Publication.marketplace_account_id)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.status == PublicationStatus.published,
            Publication.published_at.is_not(None),
            Publication.published_at <= horizon,
            Article.deleted_at.is_(None),
        )
        .order_by(Publication.published_at)
    ).all()

    now = datetime.now(UTC)
    suggestions: list[StaleSuggestion] = []
    for publication, article, account in rows:
        if not publication.price_cents:
            continue
        days_online = (now - publication.published_at).days  # type: ignore[operator]
        drop_pct = _drop_for_age(days_online)
        floor = _floor_for(article, account.platform, workspace_settings)
        suggested = max(floor, int(round(publication.price_cents * (1 - drop_pct / 100))))
        if suggested >= publication.price_cents:
            continue
        suggestions.append(
            StaleSuggestion(
                article_id=article.id,
                sku=article.sku,
                title=article.title,
                days_online=days_online,
                current_price_cents=publication.price_cents,
                suggested_price_cents=suggested,
                floor_cents=floor,
                reason=f"en ligne depuis {days_online} jours sur {account.label}",
            )
        )
    return suggestions


def _drop_for_age(days_online: int) -> float:
    applicable = [
        step["drop_pct"]
        for step in settings.default_price_drop_steps
        if days_online >= int(step["after_days"])
    ]
    return float(max(applicable)) if applicable else 0.0


def _floor_for(article: Article, platform: Platform, workspace_settings: dict | None) -> int:
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


def stock_summary(db: Session, *, workspace_id: uuid.UUID) -> dict:
    """Compteurs d'en-tête du tableau de stock."""
    counts = dict(
        db.execute(
            sa.select(Article.status, sa.func.count())
            .where(Article.workspace_id == workspace_id, Article.deleted_at.is_(None))
            .group_by(Article.status)
        ).all()
    )
    invested = db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(Article.purchase_cost_cents), 0)).where(
            Article.workspace_id == workspace_id,
            Article.deleted_at.is_(None),
            Article.status.notin_([ArticleStatus.sold, ArticleStatus.withdrawn]),
        )
    ).scalar_one()
    return {
        "by_status": {
            (status.value if hasattr(status, "value") else str(status)): int(count)
            for status, count in counts.items()
        },
        "total": int(sum(counts.values())),
        "capital_immobilise_cents": int(invested),
    }
