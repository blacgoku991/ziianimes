"""Étape 5 — moteur de publication.

Ce module porte les garde-fous. Ils comptent plus que le code de
publication lui-même, parce que ce sont eux qui évitent de faire restreindre
le compte d'un client :

* **une publication à la fois par compte**, avec un verrou pris en base ;
* **délai aléatoire** entre deux actions sur un même compte, et **plafond
  quotidien** — un compte qui publie 60 annonces en dix minutes se signale
  tout seul ;
* **doublon inter-comptes bloqué** : deux annonces du même article sur deux
  comptes de la même plateforme, c'est un des signaux les plus nets de
  rapprochement de comptes. Le cas est refusé, pas seulement signalé ;
* **mode brouillon imposé** tant que l'espace de travail n'a pas accepté
  l'avertissement CGU ;
* **rejeu idempotent** : la clé d'idempotence est unique en base, et les
  étapes franchies sont conservées.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.catalog import Article, PhotoVariant
from app.models.enums import (
    AccountStatus,
    ArticleStatus,
    Platform,
    PublicationEventType,
    PublicationMode,
    PublicationStatus,
    VariantStatus,
)
from app.models.identity import Workspace
from app.models.marketplace import MarketplaceAccount, Publication, PublicationEvent
from app.services import account_service, enrichment_service, pricing_service

logger = get_logger(__name__)

#: Statuts considérés comme « occupant » une place sur la plateforme.
ACTIVE_STATUSES = (
    PublicationStatus.queued,
    PublicationStatus.running,
    PublicationStatus.draft_ready,
    PublicationStatus.published,
)

#: Statuts qui vont ou peuvent encore aboutir à une annonce en ligne.
#: Une publication simplement en attente est tout aussi dangereuse qu'une
#: publication en ligne au moment d'une vente : si on ne l'annule pas, elle
#: part *après* que l'article a été vendu.
PENDING_OR_ACTIVE_STATUSES = (
    PublicationStatus.pending,
    PublicationStatus.blocked,
    *ACTIVE_STATUSES,
)


def build_idempotency_key(article_id: uuid.UUID, account_id: uuid.UUID) -> str:
    """Clé stable : rejouer la même demande ne crée pas une seconde annonce."""
    digest = hashlib.sha256(f"{article_id}:{account_id}".encode()).hexdigest()
    return digest[:40]


@dataclass
class Guard:
    ok: bool
    reason: str | None = None
    retry_after_seconds: int | None = None


def check_account_cadence(account: MarketplaceAccount) -> Guard:
    """Cadence et plafond quotidien d'un compte."""
    now = datetime.now(UTC)

    if account.daily_action_reset_at is None or account.daily_action_reset_at.date() < now.date():
        return Guard(ok=True)  # le compteur sera réinitialisé à la prise du verrou

    if account.daily_action_count >= settings.publish_daily_cap_per_account:
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        return Guard(
            ok=False,
            reason=(
                f"plafond quotidien atteint sur « {account.label} » "
                f"({settings.publish_daily_cap_per_account} actions)"
            ),
            retry_after_seconds=int((tomorrow - now).total_seconds()),
        )

    if account.last_action_at is not None:
        elapsed = (now - account.last_action_at).total_seconds()
        if elapsed < settings.publish_min_delay_seconds:
            return Guard(
                ok=False,
                reason="cadence trop rapide sur ce compte",
                retry_after_seconds=int(settings.publish_min_delay_seconds - elapsed) + 1,
            )
    return Guard(ok=True)


def check_duplicate_platform(
    db: Session, *, workspace_id: uuid.UUID, article: Article, account: MarketplaceAccount
) -> Guard:
    """Refuse le même article sur deux comptes d'une même plateforme."""
    conflicting = db.execute(
        sa.select(Publication, MarketplaceAccount)
        .join(MarketplaceAccount, MarketplaceAccount.id == Publication.marketplace_account_id)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.article_id == article.id,
            Publication.status.in_(PENDING_OR_ACTIVE_STATUSES),
            MarketplaceAccount.platform == account.platform,
            MarketplaceAccount.id != account.id,
        )
    ).first()
    if conflicting is None:
        return Guard(ok=True)
    _, other = conflicting
    return Guard(
        ok=False,
        reason=(
            f"cet article est déjà en ligne sur « {other.label} », un autre compte "
            f"{account.platform.value}. Publier les deux rapproche vos comptes."
        ),
    )


def resolve_mode(workspace: Workspace, requested: PublicationMode) -> PublicationMode:
    """Le brouillon est le comportement par défaut, et le reste sous condition."""
    if requested is PublicationMode.draft:
        return PublicationMode.draft
    if settings.autopublish_requires_notice and workspace.automation_notice_accepted_at is None:
        # L'avertissement CGU n'a pas été accepté : on rétrograde plutôt que
        # de refuser, pour que l'utilisateur obtienne quand même son travail.
        logger.info("autopublish_downgraded_to_draft", workspace_id=str(workspace.id))
        return PublicationMode.draft
    return PublicationMode.autopublish


def prepare_publication(
    db: Session,
    *,
    workspace: Workspace,
    article: Article,
    account: MarketplaceAccount,
    mode: PublicationMode = PublicationMode.draft,
    price_cents: int | None = None,
    copy_variant_index: int | None = None,
) -> Publication:
    """Crée (ou retrouve) la publication d'un article sur un compte.

    N'envoie rien : la mise en file est une décision séparée, ce qui permet
    de préparer un lot puis de le lâcher d'un coup.
    """
    if account.workspace_id != workspace.id or article.workspace_id != workspace.id:
        raise NotFoundError("ressource introuvable")
    if account.status is AccountStatus.disabled:
        raise ValidationError(f"le compte « {account.label} » est désactivé")

    key = build_idempotency_key(article.id, account.id)
    existing = db.execute(
        sa.select(Publication).where(
            Publication.workspace_id == workspace.id, Publication.idempotency_key == key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    duplicate = check_duplicate_platform(
        db, workspace_id=workspace.id, article=article, account=account
    )
    if not duplicate.ok:
        raise ConflictError(duplicate.reason or "publication en doublon")

    variants = _variants_for_publication(db, article_id=article.id)
    if not variants:
        raise ValidationError(
            "aucune variante d'image prête : générez-les et validez-les avant de publier"
        )

    index = (
        copy_variant_index
        if copy_variant_index is not None
        else _next_copy_index(db, workspace_id=workspace.id, article_id=article.id)
    )
    copy = enrichment_service.take_copy_variant(article, index)

    price = price_cents
    if price is None:
        advice = pricing_service.suggest_price(
            db,
            workspace_id=workspace.id,
            article=article,
            platform=account.platform,
            workspace_settings=workspace.settings,
            persist=False,
        )
        price = pricing_service.adjust_for_platform(advice.recommended_cents, account.platform)

    publication = Publication(
        workspace_id=workspace.id,
        article_id=article.id,
        marketplace_account_id=account.id,
        mode=resolve_mode(workspace, mode),
        status=PublicationStatus.pending,
        title=(copy or {}).get("title") or article.title,
        description=(copy or {}).get("description") or article.description,
        price_cents=price,
        currency=article.currency,
        idempotency_key=key,
        copy_variant_index=index,
    )
    db.add(publication)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("cet article est déjà publié sur ce compte") from exc

    # Les variantes sont rattachées à la publication : chaque compte reçoit
    # ses propres fichiers, jamais les mêmes.
    for variant in variants:
        if variant.publication_id is None:
            variant.publication_id = publication.id

    _record_event(db, publication, PublicationEventType.created, {"mode": publication.mode.value})
    db.flush()
    logger.info(
        "publication_prepared",
        publication_id=str(publication.id),
        account=account.label,
        mode=publication.mode.value,
        price_cents=price,
    )
    return publication


def _variants_for_publication(db: Session, *, article_id: uuid.UUID) -> list[PhotoVariant]:
    """Variantes utilisables : celles que l'utilisateur a validées, sinon celles prêtes."""
    accepted = list(
        db.execute(
            sa.select(PhotoVariant)
            .where(
                PhotoVariant.article_id == article_id,
                PhotoVariant.status == VariantStatus.accepted,
            )
            .order_by(PhotoVariant.variant_index)
        )
        .scalars()
        .all()
    )
    if accepted:
        return accepted
    return list(
        db.execute(
            sa.select(PhotoVariant)
            .where(
                PhotoVariant.article_id == article_id,
                PhotoVariant.status == VariantStatus.ready,
            )
            .order_by(PhotoVariant.variant_index)
        )
        .scalars()
        .all()
    )


def _next_copy_index(db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID) -> int:
    """Index du prochain jeu de textes : deux comptes n'ont jamais le même."""
    used = db.execute(
        sa.select(sa.func.count())
        .select_from(Publication)
        .where(Publication.workspace_id == workspace_id, Publication.article_id == article_id)
    ).scalar_one()
    return int(used)


def enqueue(db: Session, *, workspace_id: uuid.UUID, publication: Publication) -> Publication:
    """Met une publication en file, garde-fous vérifiés."""
    account = account_service.get_account(
        db, workspace_id=workspace_id, account_id=publication.marketplace_account_id
    )
    if account.status is not AccountStatus.active:
        publication.status = PublicationStatus.blocked
        publication.last_error = f"le compte « {account.label} » demande une reconnexion"
        db.flush()
        _record_event(
            db, publication, PublicationEventType.failed, {"reason": publication.last_error}
        )
        return publication

    cadence = check_account_cadence(account)
    if not cadence.ok:
        publication.status = PublicationStatus.blocked
        publication.last_error = cadence.reason
        db.flush()
        _record_event(
            db,
            publication,
            PublicationEventType.queued,
            {"blocked": cadence.reason, "retry_after_seconds": cadence.retry_after_seconds},
        )
        return publication

    publication.status = PublicationStatus.queued
    publication.last_error = None
    db.flush()
    _record_event(db, publication, PublicationEventType.queued, {})
    return publication


def acquire_account_slot(db: Session, *, account_id: uuid.UUID) -> bool:
    """Verrou « une publication à la fois par compte », en une instruction.

    Un `UPDATE ... WHERE` unique fait à la fois le verrou et le contrôle de
    cadence : la ligne n'est modifiée que si le délai minimal est écoulé, et
    la base garantit qu'un seul worker l'obtient. Un `SELECT` puis un
    `UPDATE` séparés laisseraient deux workers passer ensemble.
    """
    now = datetime.now(UTC)
    threshold = now - timedelta(seconds=settings.publish_min_delay_seconds)
    result = db.execute(
        sa.update(MarketplaceAccount)
        .where(
            MarketplaceAccount.id == account_id,
            sa.or_(
                MarketplaceAccount.last_action_at.is_(None),
                MarketplaceAccount.last_action_at <= threshold,
            ),
        )
        .values(last_action_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def register_action(db: Session, *, account: MarketplaceAccount) -> None:
    """Comptabilise une action et programme le prochain créneau."""
    now = datetime.now(UTC)
    if account.daily_action_reset_at is None or account.daily_action_reset_at.date() < now.date():
        account.daily_action_count = 0
        account.daily_action_reset_at = datetime.combine(
            date.today(), datetime.min.time(), tzinfo=UTC
        )
    account.daily_action_count += 1
    account.last_action_at = now
    db.flush()


def next_delay_seconds() -> int:
    """Délai aléatoire avant la prochaine action sur un compte."""
    return random.randint(settings.publish_min_delay_seconds, settings.publish_max_delay_seconds)


# ---------------------------------------------------------------------------
# Vente et dépublication croisée
# ---------------------------------------------------------------------------


@dataclass
class SaleOutcome:
    publication_id: uuid.UUID
    unpublished_publication_ids: list[uuid.UUID]
    oversold: bool
    margin: dict | None

    def as_dict(self) -> dict:
        return {
            "publication_id": str(self.publication_id),
            "unpublished_publication_ids": [str(pid) for pid in self.unpublished_publication_ids],
            "oversold": self.oversold,
            "margin": self.margin,
        }


def mark_sold(
    db: Session,
    *,
    workspace: Workspace,
    publication: Publication,
    sale_price_cents: int | None = None,
    shipping_cents: int | None = None,
) -> SaleOutcome:
    """Enregistre une vente et dépublie les autres annonces de l'article.

    Le cas de la **survente** est traité explicitement : si une autre
    publication du même article est déjà vendue, on ne l'écrase pas, on
    signale le conflit. Entre deux synchronisations, deux acheteurs peuvent
    acheter la même pièce — c'est le mode d'échec normal d'un stock unitaire,
    et le taire ferait découvrir le problème au moment du litige.
    """
    from app.services import fees

    article = db.get(Article, publication.article_id)
    if article is None:
        raise NotFoundError("article introuvable")

    already_sold = (
        db.execute(
            sa.select(Publication).where(
                Publication.article_id == article.id,
                Publication.id != publication.id,
                Publication.status == PublicationStatus.sold,
            )
        )
        .scalars()
        .first()
    )
    oversold = already_sold is not None and article.quantity <= 1

    now = datetime.now(UTC)
    price = sale_price_cents or publication.price_cents or 0
    account = db.get(MarketplaceAccount, publication.marketplace_account_id)
    platform = account.platform if account else Platform.vinted

    breakdown = fees.compute_margin(
        platform=platform,
        price_cents=price,
        purchase_cost_cents=article.purchase_cost_cents,
        shipping_cents=shipping_cents,
        workspace_settings=workspace.settings,
    )

    publication.status = PublicationStatus.sold
    publication.sold_at = now
    publication.sale_price_cents = price
    publication.fee_cents = breakdown.fee_cents
    publication.shipping_cents = breakdown.shipping_cents
    publication.net_proceeds_cents = breakdown.net_proceeds_cents
    _record_event(
        db,
        publication,
        PublicationEventType.sold,
        {"sale_price_cents": price, "oversold": oversold, **breakdown.as_dict()},
    )

    article.status = ArticleStatus.sold
    article.sold_at = now

    # Dépublication croisée : toutes les autres annonces de l'article, y
    # compris celles encore en attente — sans quoi une publication déjà en
    # file partirait après la vente.
    siblings = list(
        db.execute(
            sa.select(Publication).where(
                Publication.article_id == article.id,
                Publication.id != publication.id,
                Publication.status.in_(PENDING_OR_ACTIVE_STATUSES),
            )
        )
        .scalars()
        .all()
    )
    unpublished: list[uuid.UUID] = []
    for sibling in siblings:
        sibling.status = PublicationStatus.unpublished
        sibling.unpublished_at = now
        _record_event(
            db,
            sibling,
            PublicationEventType.unpublished,
            {"reason": "vendu ailleurs", "sold_publication_id": str(publication.id)},
        )
        unpublished.append(sibling.id)

    db.flush()
    logger.info(
        "publication_sold",
        publication_id=str(publication.id),
        unpublished=len(unpublished),
        oversold=oversold,
        net_proceeds_cents=breakdown.net_proceeds_cents,
    )
    return SaleOutcome(
        publication_id=publication.id,
        unpublished_publication_ids=unpublished,
        oversold=oversold,
        margin=breakdown.as_dict(),
    )


def mark_returned(db: Session, *, publication: Publication) -> Publication:
    """Retour acheteur : la pièce revient en stock."""
    article = db.get(Article, publication.article_id)
    publication.status = PublicationStatus.unpublished
    publication.sold_at = None
    publication.sale_price_cents = None
    publication.net_proceeds_cents = None
    if article is not None:
        article.status = ArticleStatus.returned
        article.sold_at = None
    _record_event(db, publication, PublicationEventType.unpublished, {"reason": "retour acheteur"})
    db.flush()
    return publication


def get_publication(
    db: Session, *, workspace_id: uuid.UUID, publication_id: uuid.UUID
) -> Publication:
    publication = db.execute(
        sa.select(Publication).where(
            Publication.id == publication_id, Publication.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if publication is None:
        raise NotFoundError("publication introuvable")
    return publication


def list_publications(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article_id: uuid.UUID | None = None,
    status: PublicationStatus | None = None,
    limit: int = 100,
) -> list[Publication]:
    conditions = [Publication.workspace_id == workspace_id]
    if article_id is not None:
        conditions.append(Publication.article_id == article_id)
    if status is not None:
        conditions.append(Publication.status == status)
    return list(
        db.execute(
            sa.select(Publication)
            .where(*conditions)
            .order_by(Publication.created_at.desc())
            .limit(min(limit, 500))
        )
        .scalars()
        .all()
    )


def _record_event(
    db: Session, publication: Publication, event_type: PublicationEventType, payload: dict
) -> PublicationEvent:
    event = PublicationEvent(
        workspace_id=publication.workspace_id,
        publication_id=publication.id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    return event


record_event = _record_event
