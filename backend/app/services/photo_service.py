"""Import des photos sources.

La source est stockée **telle qu'elle a été envoyée**, sans recompression :
c'est elle qui alimente toutes les variantes. Toute normalisation faite ici
(redimensionnement, réencodage) serait une perte de qualité définitive,
propagée à chaque publication.
"""

from __future__ import annotations

import hashlib
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.imaging.pipeline import analyse_source
from app.models.catalog import Article, ArticlePhoto, PhotoVariant
from app.models.enums import PhotoStatus
from app.storage import build_key, get_storage

logger = get_logger(__name__)

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def upload_photo(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article: Article,
    data: bytes,
    filename: str | None,
    content_type: str,
) -> tuple[ArticlePhoto, bool]:
    """Ajoute une photo à un article. Retourne `(photo, créée)`.

    Le même fichier envoyé deux fois sur le même article renvoie la ligne
    existante : les doubles-clics et les reprises d'envoi ne créent pas de
    doublons.
    """
    if content_type not in settings.image_allowed_content_types:
        raise ValidationError(
            f"format non géré : {content_type}",
            details={"allowed": settings.image_allowed_content_types},
        )
    if not data:
        raise ValidationError("fichier vide")
    if len(data) > settings.image_max_upload_bytes:
        raise ValidationError(
            "fichier trop volumineux",
            details={"max_bytes": settings.image_max_upload_bytes, "size": len(data)},
        )

    checksum = hashlib.sha256(data).hexdigest()
    existing = db.execute(
        sa.select(ArticlePhoto).where(
            ArticlePhoto.article_id == article.id,
            ArticlePhoto.checksum_sha256 == checksum,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    count = db.execute(
        sa.select(sa.func.count())
        .select_from(ArticlePhoto)
        .where(ArticlePhoto.article_id == article.id)
    ).scalar_one()
    if count >= settings.max_photos_per_article:
        raise ValidationError(f"maximum {settings.max_photos_per_article} photos par article")

    # Décodage de contrôle : on refuse ici ce qui casserait plus tard dans
    # le worker, quand l'utilisateur n'est plus devant l'écran.
    analysis = analyse_source(data)

    photo_id = uuid.uuid4()
    extension = _EXTENSIONS.get(content_type, "bin")
    key = build_key(workspace_id, article.id, "originals", f"{photo_id}.{extension}")
    get_storage().put(key, data, content_type=content_type)

    next_position = db.execute(
        sa.select(sa.func.coalesce(sa.func.max(ArticlePhoto.position), -1)).where(
            ArticlePhoto.article_id == article.id
        )
    ).scalar_one()

    photo = ArticlePhoto(
        id=photo_id,
        workspace_id=workspace_id,
        article_id=article.id,
        position=int(next_position) + 1,
        storage_key=key,
        original_filename=(filename or "")[:255] or None,
        content_type=content_type,
        byte_size=len(data),
        width=analysis.width,
        height=analysis.height,
        checksum_sha256=checksum,
        phash=analysis.phash,
        status=PhotoStatus.ready,
    )
    db.add(photo)
    db.flush()
    logger.info(
        "photo_uploaded",
        workspace_id=str(workspace_id),
        article_id=str(article.id),
        photo_id=str(photo.id),
        width=analysis.width,
        height=analysis.height,
        bytes=len(data),
    )
    return photo, True


def get_photo(db: Session, *, workspace_id: uuid.UUID, photo_id: uuid.UUID) -> ArticlePhoto:
    photo = db.execute(
        sa.select(ArticlePhoto).where(
            ArticlePhoto.id == photo_id, ArticlePhoto.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if photo is None:
        raise NotFoundError("photo introuvable")
    return photo


def list_photos(
    db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID
) -> list[ArticlePhoto]:
    rows = (
        db.execute(
            sa.select(ArticlePhoto)
            .where(
                ArticlePhoto.workspace_id == workspace_id,
                ArticlePhoto.article_id == article_id,
            )
            .order_by(ArticlePhoto.position.asc())
        )
        .scalars()
        .all()
    )
    return list(rows)


def read_photo_bytes(photo: ArticlePhoto) -> bytes:
    return get_storage().get(photo.storage_key)


def delete_photo(db: Session, *, workspace_id: uuid.UUID, photo_id: uuid.UUID) -> None:
    photo = get_photo(db, workspace_id=workspace_id, photo_id=photo_id)
    storage = get_storage()
    variant_keys = (
        db.execute(
            sa.select(PhotoVariant.storage_key).where(PhotoVariant.source_photo_id == photo.id)
        )
        .scalars()
        .all()
    )
    db.delete(photo)
    db.flush()
    # Les objets ne sont retirés qu'après le succès du flush : une erreur
    # base ne doit pas laisser des lignes pointant vers des fichiers absents.
    for key in [*(k for k in variant_keys if k), photo.storage_key]:
        try:
            storage.delete(key)
        except Exception as exc:  # nettoyage au mieux
            logger.warning("storage_delete_failed", key=key, error=str(exc))


def reorder_photos(
    db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID, ordered_ids: list[uuid.UUID]
) -> list[ArticlePhoto]:
    photos = {p.id: p for p in list_photos(db, workspace_id=workspace_id, article_id=article_id)}
    if set(ordered_ids) != set(photos):
        raise ValidationError("la liste doit contenir exactement les photos de l'article")
    # Décalage temporaire hors plage : la contrainte d'unicité
    # (article_id, position) est vérifiée à chaque instruction.
    for offset, photo_id in enumerate(ordered_ids):
        photos[photo_id].position = 1000 + offset
    db.flush()
    for offset, photo_id in enumerate(ordered_ids):
        photos[photo_id].position = offset
    db.flush()
    return list_photos(db, workspace_id=workspace_id, article_id=article_id)
