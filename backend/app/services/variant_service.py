"""Génération et arbitrage des variantes.

Deux garanties sont vérifiées à chaque rendu :

* **écart à la source** — la variante ne doit pas être rapprochée de
  l'originale par un hash perceptuel (géré dans le pipeline, par escalade) ;
* **écart entre variantes sœurs** — deux variantes d'une même photo
  destinées à deux comptes ne doivent pas se ressembler entre elles non
  plus, sinon le problème est simplement déplacé.

Une variante rendue reste en `ready` : elle n'est ni acceptée ni refusée
tant que l'utilisateur ne l'a pas vue. C'est la prévisualisation avant/après
demandée par la spécification.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.imaging.phash import hamming_distance
from app.imaging.pipeline import render_variant_with_guarantee
from app.models.catalog import ArticlePhoto, PhotoVariant
from app.models.enums import VariantStatus
from app.services import photo_service
from app.storage import build_key, get_storage

logger = get_logger(__name__)

#: Distance minimale entre deux variantes d'une même photo source.
MIN_SIBLING_DISTANCE = 8
#: Nombre de graines essayées pour écarter une variante de ses sœurs.
MAX_SIBLING_ATTEMPTS = 3
DEFAULT_VARIANT_COUNT = 3
MAX_VARIANT_COUNT = 6


def new_seed() -> int:
    return int.from_bytes(secrets.token_bytes(6), "big")


def plan_variants(
    db: Session, *, workspace_id: uuid.UUID, photo: ArticlePhoto, count: int
) -> list[PhotoVariant]:
    """Crée (ou complète) les lignes de variantes en attente de rendu.

    Séparer la planification du rendu permet à l'interface d'afficher
    immédiatement N emplacements « en cours », et au worker de reprendre
    proprement après un incident.
    """
    if count < 1 or count > MAX_VARIANT_COUNT:
        raise ValidationError(f"entre 1 et {MAX_VARIANT_COUNT} variantes par photo")

    existing = {
        variant.variant_index: variant
        for variant in db.execute(
            sa.select(PhotoVariant).where(PhotoVariant.source_photo_id == photo.id)
        )
        .scalars()
        .all()
    }
    planned: list[PhotoVariant] = []
    for index in range(count):
        variant = existing.get(index)
        if variant is None:
            variant = PhotoVariant(
                workspace_id=workspace_id,
                article_id=photo.article_id,
                source_photo_id=photo.id,
                variant_index=index,
                seed=new_seed(),
                status=VariantStatus.pending,
            )
            db.add(variant)
        planned.append(variant)
    db.flush()
    return planned


def render_variant_row(
    db: Session, *, workspace_id: uuid.UUID, variant_id: uuid.UUID, force: bool = False
) -> PhotoVariant:
    """Effectue le rendu d'une variante planifiée.

    Idempotent : une variante déjà rendue n'est pas refaite sans `force`.
    """
    variant = get_variant(db, workspace_id=workspace_id, variant_id=variant_id)
    if variant.status in (VariantStatus.ready, VariantStatus.accepted) and not force:
        return variant

    photo = photo_service.get_photo(db, workspace_id=workspace_id, photo_id=variant.source_photo_id)
    source_bytes = photo_service.read_photo_bytes(photo)
    siblings = _sibling_hashes(db, photo_id=photo.id, exclude_variant_id=variant.id)

    seed = variant.seed
    result = None
    for attempt in range(1, MAX_SIBLING_ATTEMPTS + 1):
        try:
            candidate = render_variant_with_guarantee(
                source_bytes, seed=seed, variant_index=variant.variant_index
            )
        except Exception as exc:
            variant.status = VariantStatus.failed
            variant.failure_reason = str(exc)[:500]
            db.flush()
            logger.exception("variant_render_failed", variant_id=str(variant.id), error=str(exc))
            raise

        result = candidate
        too_close = [
            h for h in siblings if hamming_distance(h, candidate.phash) < MIN_SIBLING_DISTANCE
        ]
        if not too_close:
            break
        logger.info(
            "variant_too_close_to_sibling",
            variant_id=str(variant.id),
            attempt=attempt,
            seed=seed,
        )
        seed = new_seed()

    assert result is not None
    previous_key = variant.storage_key
    key = build_key(
        workspace_id,
        variant.article_id,
        "variants",
        f"{variant.id}-r{variant.render_count + 1}.jpg",
    )
    storage = get_storage()
    storage.put(key, result.data, content_type=result.content_type)

    variant.seed = seed
    variant.recipe = result.recipe.to_dict()
    variant.storage_key = key
    variant.content_type = result.content_type
    variant.byte_size = len(result.data)
    variant.width = result.width
    variant.height = result.height
    variant.phash = result.phash
    variant.phash_distance_to_source = result.distance_to_source
    variant.background_replaced = result.background_replaced
    variant.status = VariantStatus.ready
    variant.failure_reason = None
    variant.render_count += 1
    variant.render_ms = result.render_ms
    variant.rendered_at = datetime.now(UTC)
    db.flush()

    if previous_key and previous_key != key:
        try:
            storage.delete(previous_key)
        except Exception as exc:
            logger.warning("storage_delete_failed", key=previous_key, error=str(exc))

    logger.info(
        "variant_rendered",
        variant_id=str(variant.id),
        distance_to_source=result.distance_to_source,
        background_replaced=result.background_replaced,
        render_ms=result.render_ms,
    )
    return variant


def _sibling_hashes(
    db: Session, *, photo_id: uuid.UUID, exclude_variant_id: uuid.UUID
) -> list[str]:
    rows = (
        db.execute(
            sa.select(PhotoVariant.phash).where(
                PhotoVariant.source_photo_id == photo_id,
                PhotoVariant.id != exclude_variant_id,
                PhotoVariant.phash.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    return [row for row in rows if row]


def regenerate_variant(
    db: Session, *, workspace_id: uuid.UUID, variant_id: uuid.UUID
) -> PhotoVariant:
    """Refait une variante avec une nouvelle graine (action utilisateur)."""
    variant = get_variant(db, workspace_id=workspace_id, variant_id=variant_id)
    variant.seed = new_seed()
    variant.status = VariantStatus.pending
    db.flush()
    return render_variant_row(db, workspace_id=workspace_id, variant_id=variant_id, force=True)


def set_variant_decision(
    db: Session, *, workspace_id: uuid.UUID, variant_id: uuid.UUID, accepted: bool
) -> PhotoVariant:
    variant = get_variant(db, workspace_id=workspace_id, variant_id=variant_id)
    if variant.status not in (VariantStatus.ready, VariantStatus.accepted, VariantStatus.rejected):
        raise ValidationError("cette variante n'a pas encore de rendu à valider")
    variant.status = VariantStatus.accepted if accepted else VariantStatus.rejected
    db.flush()
    return variant


def get_variant(db: Session, *, workspace_id: uuid.UUID, variant_id: uuid.UUID) -> PhotoVariant:
    variant = db.execute(
        sa.select(PhotoVariant).where(
            PhotoVariant.id == variant_id, PhotoVariant.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError("variante introuvable")
    return variant


def list_variants(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    photo_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
) -> list[PhotoVariant]:
    conditions = [PhotoVariant.workspace_id == workspace_id]
    if photo_id is not None:
        conditions.append(PhotoVariant.source_photo_id == photo_id)
    if article_id is not None:
        conditions.append(PhotoVariant.article_id == article_id)
    rows = (
        db.execute(
            sa.select(PhotoVariant)
            .where(*conditions)
            .order_by(PhotoVariant.source_photo_id, PhotoVariant.variant_index)
        )
        .scalars()
        .all()
    )
    return list(rows)


def read_variant_bytes(variant: PhotoVariant) -> bytes:
    if not variant.storage_key:
        raise NotFoundError("variante sans rendu")
    return get_storage().get(variant.storage_key)


def default_variant_count() -> int:
    return DEFAULT_VARIANT_COUNT


def min_source_distance() -> int:
    return settings.variant_min_phash_distance
