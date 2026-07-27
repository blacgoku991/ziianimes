"""Exécution d'une publication : orchestre connecteur, reprise et journal.

Séparé de `publication_service` (qui décide) et de la tâche Celery (qui
planifie) : ici on exécute, et on est le seul endroit qui touche à la fois
au connecteur et à l'état persistant.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError, PublishRequest, PublishResult
from app.connectors.registry import get_connector
from app.core.config import settings
from app.core.logging import get_logger
from app.models.catalog import Article, PhotoVariant
from app.models.enums import (
    ArticleStatus,
    PublicationEventType,
    PublicationMode,
    PublicationStatus,
    VariantStatus,
)
from app.models.identity import Workspace
from app.models.marketplace import MarketplaceAccount, Publication
from app.services import account_service, mapping_service, publication_service
from app.storage import get_storage

logger = get_logger(__name__)


@dataclass
class RunOutcome:
    publication_id: uuid.UUID
    status: PublicationStatus
    draft_ready: bool
    remote_url: str | None
    error: str | None

    def as_dict(self) -> dict:
        return {
            "publication_id": str(self.publication_id),
            "status": self.status.value,
            "draft_ready": self.draft_ready,
            "remote_url": self.remote_url,
            "error": self.error,
        }


def run_publication(
    db: Session, *, workspace_id: uuid.UUID, publication_id: uuid.UUID
) -> RunOutcome:
    """Exécute une publication en file.

    Idempotent : une publication déjà aboutie n'est pas rejouée, et une
    reprise après incident repart du dernier point franchi — en particulier
    sans réenvoyer les photos.
    """
    publication = publication_service.get_publication(
        db, workspace_id=workspace_id, publication_id=publication_id
    )
    if publication.status in (
        PublicationStatus.published,
        PublicationStatus.sold,
        # Annulée à la vente d'une autre annonce du même article : ne surtout
        # pas la remettre en ligne.
        PublicationStatus.unpublished,
    ):
        return RunOutcome(publication.id, publication.status, False, publication.remote_url, None)

    workspace = db.get(Workspace, workspace_id)
    article = db.get(Article, publication.article_id)
    account = db.get(MarketplaceAccount, publication.marketplace_account_id)
    if workspace is None or article is None or account is None:
        raise ValueError("publication incohérente")

    if not publication_service.acquire_account_slot(db, account_id=account.id):
        # Un autre job occupe le compte, ou la cadence n'est pas respectée :
        # on repose la publication en file sans la marquer en échec.
        publication.status = PublicationStatus.queued
        db.flush()
        return RunOutcome(publication.id, publication.status, False, None, "compte occupé")

    publication.status = PublicationStatus.running
    publication.attempts += 1
    db.flush()

    with tempfile.TemporaryDirectory(prefix="ziia-pub-") as workdir:
        try:
            request = _build_request(
                db,
                workspace=workspace,
                article=article,
                account=account,
                publication=publication,
                workdir=Path(workdir),
            )
            connector = get_connector(account)
            result = connector.publish(request, _credentials(account, workspace_id))
            return _apply_result(
                db, publication=publication, account=account, article=article, result=result
            )
        except ConnectorError as exc:
            return _apply_failure(db, publication=publication, account=account, exc=exc)
        except Exception as exc:  # défaut inattendu : on trace et on réessaiera
            logger.exception("publication_crashed", publication_id=str(publication.id))
            return _apply_failure(
                db,
                publication=publication,
                account=account,
                exc=ConnectorError(str(exc)[:400], retryable=True),
            )
        finally:
            publication_service.register_action(db, account=account)


def _credentials(account: MarketplaceAccount, workspace_id: uuid.UUID) -> dict:
    credentials = account_service.load_credentials(account=account, workspace_id=workspace_id)
    if credentials is None:
        raise ConnectorError(
            f"aucun identifiant enregistré pour « {account.label} »",
            retryable=False,
            needs_reauth=True,
        )
    return credentials


def _build_request(
    db: Session,
    *,
    workspace: Workspace,  # noqa: ARG001 — signature stable pour les évolutions
    article: Article,
    account: MarketplaceAccount,
    publication: Publication,
    workdir: Path,
) -> PublishRequest:
    variants = list(
        db.execute(
            sa.select(PhotoVariant)
            .where(
                PhotoVariant.publication_id == publication.id,
                PhotoVariant.status.in_([VariantStatus.ready, VariantStatus.accepted]),
            )
            .order_by(PhotoVariant.variant_index)
        )
        .scalars()
        .all()
    )
    if not variants:
        raise ConnectorError("aucune variante d'image rattachée", retryable=False)

    # Les fichiers sont matérialisés dans un répertoire temporaire, effacé
    # à la sortie du bloc : le worker ne conserve rien.
    storage = get_storage()
    image_paths: list[str] = []
    for variant in variants:
        if not variant.storage_key:
            continue
        target = workdir / f"{variant.variant_index:02d}-{variant.id}.jpg"
        target.write_bytes(storage.get(variant.storage_key))
        image_paths.append(str(target))

    category_path = _resolve_category_path(
        db, article=article, account=account, publication=publication
    )
    brand_name = _resolve_brand_name(db, article=article, account=account, publication=publication)
    size_name = _resolve_size_name(db, article=article, account=account, publication=publication)

    draft_only = publication.mode is PublicationMode.draft
    return PublishRequest(
        publication_id=str(publication.id),
        title=publication.title or article.title or article.sku,
        description=publication.description or article.description or "",
        price_cents=publication.price_cents or 0,
        currency=publication.currency,
        image_paths=image_paths,
        category_external_id=category_path,
        brand_external_id=brand_name,
        size_external_id=size_name,
        condition=article.condition.value if article.condition else None,
        colour=article.color,
        material=article.material,
        draft_only=draft_only,
        checkpoint=dict(publication.checkpoint or {}),
    )


def _resolve_category_path(
    db: Session, *, article: Article, account: MarketplaceAccount, publication: Publication
) -> str | None:
    """Chemin de catégorie de la plateforme, mémorisé sur la publication."""
    if publication.remote_category_id:
        from app.models.referential import PlatformCategory

        category = db.execute(
            sa.select(PlatformCategory).where(
                PlatformCategory.platform == account.platform,
                PlatformCategory.external_id == publication.remote_category_id,
            )
        ).scalar_one_or_none()
        if category is not None:
            return category.path

    match = mapping_service.match_category(
        db,
        workspace_id=article.workspace_id,
        platform=account.platform,
        label=article.category_label or "",
        extra_context=" ".join(filter(None, [article.title, article.brand, article.size_label])),
    )
    if match.needs_user_choice or match.best is None:
        # On ne publie pas une supposition : une annonce mal rangée est
        # invisible, et l'utilisateur peut trancher en deux secondes.
        raise ConnectorError(
            "catégorie non déterminée : choisissez-la avant de publier", retryable=False
        )
    publication.remote_category_id = match.best.external_id
    return match.best.path


def _resolve_brand_name(
    db: Session, *, article: Article, account: MarketplaceAccount, publication: Publication
) -> str | None:
    if not article.brand:
        return None
    match = mapping_service.match_brand(
        db, workspace_id=article.workspace_id, platform=account.platform, label=article.brand
    )
    if match.best is not None and not match.needs_user_choice:
        publication.remote_brand_id = match.best.external_id
        return match.best.label
    fallback = mapping_service.fallback_brand(db, account.platform)
    if fallback is not None:
        publication.remote_brand_id = fallback.external_id
        return fallback.name
    return None


def _resolve_size_name(
    db: Session, *, article: Article, account: MarketplaceAccount, publication: Publication
) -> str | None:
    if not article.size_label:
        return None
    match = mapping_service.match_size(
        db,
        platform=account.platform,
        category_external_id=publication.remote_category_id,
        label=article.size_label,
    )
    if match.best is None:
        return None
    publication.remote_size_id = match.best.external_id
    return match.best.label


def _apply_result(
    db: Session,
    *,
    publication: Publication,
    account: MarketplaceAccount,
    article: Article,
    result: PublishResult,
) -> RunOutcome:
    publication.checkpoint = result.checkpoint
    publication.last_error = None

    if result.draft_ready:
        publication.status = PublicationStatus.draft_ready
        publication.remote_url = result.remote_url
        publication_service.record_event(
            db,
            publication,
            PublicationEventType.draft_ready,
            {"steps": result.completed_steps()},
        )
    else:
        publication.status = PublicationStatus.published
        publication.published_at = datetime.now(UTC)
        publication.remote_listing_id = result.remote_listing_id
        publication.remote_url = result.remote_url
        publication.next_sync_at = datetime.now(UTC)
        publication_service.record_event(
            db,
            publication,
            PublicationEventType.published,
            {"remote_listing_id": result.remote_listing_id},
        )
        if article.status is ArticleStatus.draft:
            article.status = ArticleStatus.listed
        if article.first_listed_at is None:
            article.first_listed_at = datetime.now(UTC)

    db.flush()
    logger.info(
        "publication_run_ok",
        publication_id=str(publication.id),
        status=publication.status.value,
        account=account.label,
    )
    return RunOutcome(
        publication.id, publication.status, result.draft_ready, publication.remote_url, None
    )


def _apply_failure(
    db: Session, *, publication: Publication, account: MarketplaceAccount, exc: ConnectorError
) -> RunOutcome:
    publication.last_error = exc.message[:500]
    # On conserve les étapes franchies avant l'échec : sans elles, la
    # reprise réenverrait les photos, avec le risque de doublon que cela
    # implique côté plateforme.
    if exc.checkpoint:
        publication.checkpoint = {**(publication.checkpoint or {}), **exc.checkpoint}
    exhausted = publication.attempts >= settings.publish_max_attempts

    if exc.needs_reauth:
        account_service.mark_needs_reauth(db, account=account, reason=exc.message)
        publication.status = PublicationStatus.blocked
    elif exc.retryable and not exhausted:
        publication.status = PublicationStatus.queued
    else:
        publication.status = PublicationStatus.failed

    publication_service.record_event(
        db,
        publication,
        PublicationEventType.failed,
        {
            "error": exc.message[:400],
            "retryable": exc.retryable,
            "attempts": publication.attempts,
            "needs_reauth": exc.needs_reauth,
        },
    )
    db.flush()
    logger.warning(
        "publication_run_failed",
        publication_id=str(publication.id),
        status=publication.status.value,
        error=exc.message[:200],
    )
    return RunOutcome(publication.id, publication.status, False, None, exc.message)


def sync_publication(db: Session, *, workspace_id: uuid.UUID, publication_id: uuid.UUID) -> dict:
    """Interroge la plateforme sur l'état d'une annonce.

    C'est ce qui déclenche la dépublication croisée à la vente. La fenêtre
    entre deux passages est la fenêtre de survente : elle est configurable
    (`SYNC_INTERVAL_SECONDS`) et affichée à l'utilisateur, parce qu'elle est
    un risque métier, pas un détail technique.
    """
    publication = publication_service.get_publication(
        db, workspace_id=workspace_id, publication_id=publication_id
    )
    if publication.status is not PublicationStatus.published or not publication.remote_listing_id:
        return {"skipped": True, "reason": "publication non en ligne"}

    workspace = db.get(Workspace, workspace_id)
    account = db.get(MarketplaceAccount, publication.marketplace_account_id)
    if workspace is None or account is None:
        return {"skipped": True, "reason": "compte introuvable"}

    connector = get_connector(account)
    try:
        status = connector.fetch_status(
            publication.remote_listing_id, _credentials(account, workspace_id)
        )
    except ConnectorError as exc:
        if exc.needs_reauth:
            account_service.mark_needs_reauth(db, account=account, reason=exc.message)
        return {"skipped": True, "reason": exc.message}

    publication.last_synced_at = datetime.now(UTC)
    publication.next_sync_at = datetime.now(UTC)
    if status.get("views_count"):
        publication.views_count = int(status["views_count"])

    if status.get("sold"):
        outcome = publication_service.mark_sold(
            db,
            workspace=workspace,
            publication=publication,
            sale_price_cents=status.get("sale_price_cents"),
        )
        return {"sold": True, **outcome.as_dict()}

    db.flush()
    return {"sold": False, "views_count": publication.views_count}
