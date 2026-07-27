"""Routes photos : import, ordre, prévisualisation, génération de variantes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse

from app.api.deps import Context, DbSession
from app.api.serializers import serialize_photo, serialize_variant
from app.core.config import settings
from app.core.errors import AuthenticationError, NotFoundError, ValidationError
from app.schemas.catalog import (
    GenerateVariantsRequest,
    PhotoOut,
    PhotoReorderRequest,
    VariantJobOut,
)
from app.services import article_service, photo_service, variant_service
from app.services.media import verify_media_token
from app.storage import ObjectNotFound, get_storage

router = APIRouter(tags=["photos"])


@router.post(
    "/articles/{article_id}/photos",
    response_model=list[PhotoOut],
    status_code=status.HTTP_201_CREATED,
)
def upload_photos(
    article_id: uuid.UUID,
    db: DbSession,
    context: Context,
    files: Annotated[list[UploadFile], File(description="Photos en pleine résolution")],
) -> list[PhotoOut]:
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    if not files:
        raise ValidationError("aucun fichier reçu")

    results = []
    for upload in files:
        data = upload.file.read()
        photo, _ = photo_service.upload_photo(
            db,
            workspace_id=context.workspace_id,
            article=article,
            data=data,
            filename=upload.filename,
            content_type=upload.content_type or "application/octet-stream",
        )
        results.append(photo)
    db.flush()
    return [serialize_photo(photo, context.workspace_id, variants=[]) for photo in results]


@router.get("/articles/{article_id}/photos", response_model=list[PhotoOut])
def list_photos(article_id: uuid.UUID, db: DbSession, context: Context) -> list[PhotoOut]:
    article_service.get_article(db, workspace_id=context.workspace_id, article_id=article_id)
    photos = photo_service.list_photos(db, workspace_id=context.workspace_id, article_id=article_id)
    return [serialize_photo(photo, context.workspace_id) for photo in photos]


@router.post("/articles/{article_id}/photos/reorder", response_model=list[PhotoOut])
def reorder_photos(
    article_id: uuid.UUID, payload: PhotoReorderRequest, db: DbSession, context: Context
) -> list[PhotoOut]:
    article_service.get_article(db, workspace_id=context.workspace_id, article_id=article_id)
    photos = photo_service.reorder_photos(
        db,
        workspace_id=context.workspace_id,
        article_id=article_id,
        ordered_ids=payload.photo_ids,
    )
    return [serialize_photo(photo, context.workspace_id) for photo in photos]


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_photo(photo_id: uuid.UUID, db: DbSession, context: Context) -> None:
    photo_service.delete_photo(db, workspace_id=context.workspace_id, photo_id=photo_id)


@router.post("/photos/{photo_id}/variants", response_model=VariantJobOut)
def generate_variants(
    photo_id: uuid.UUID, payload: GenerateVariantsRequest, db: DbSession, context: Context
) -> VariantJobOut:
    """Planifie N variantes puis lance leur rendu.

    Le rendu est asynchrone par défaut : l'interface affiche des
    emplacements « en cours » et les rafraîchit. Le mode synchrone existe
    pour le développement et les tests.
    """
    photo = photo_service.get_photo(db, workspace_id=context.workspace_id, photo_id=photo_id)
    variants = variant_service.plan_variants(
        db, workspace_id=context.workspace_id, photo=photo, count=payload.count
    )
    variant_ids = [variant.id for variant in variants]

    run_inline = payload.synchronous or settings.celery_task_always_eager
    if run_inline:
        for variant_id in variant_ids:
            variant_service.render_variant_row(
                db, workspace_id=context.workspace_id, variant_id=variant_id, force=True
            )
        queued = False
    else:
        from app.workers.tasks.imaging import render_variant_task

        # Les tâches sont émises après le commit de la transaction : sans
        # cela, le worker peut lire la ligne avant qu'elle n'existe.
        db.commit()
        for variant_id in variant_ids:
            render_variant_task.delay(str(context.workspace_id), str(variant_id))
        queued = True

    fresh = [
        variant_service.get_variant(db, workspace_id=context.workspace_id, variant_id=variant_id)
        for variant_id in variant_ids
    ]
    return VariantJobOut(
        variants=[serialize_variant(variant, context.workspace_id) for variant in fresh],
        queued=queued,
    )


@router.get("/photos/{photo_id}/file", response_model=None)
def serve_photo(
    photo_id: uuid.UUID,
    db: DbSession,
    token: str = Query(..., description="Jeton média signé"),
) -> StreamingResponse | RedirectResponse:
    workspace_id = verify_media_token(token, kind="photo", object_id=photo_id)
    photo = photo_service.get_photo(db, workspace_id=workspace_id, photo_id=photo_id)
    return _serve(photo.storage_key, photo.content_type)


def _serve(storage_key: str | None, content_type: str | None):  # type: ignore[no-untyped-def]
    if not storage_key:
        raise NotFoundError("fichier introuvable")
    storage = get_storage()
    direct = storage.presigned_url(storage_key)
    if direct:
        # S3/R2 : on laisse le stockage servir l'octet, l'API ne fait que
        # l'autorisation.
        return RedirectResponse(direct, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    try:
        stream = storage.stream(storage_key)
    except ObjectNotFound as exc:
        raise NotFoundError("fichier introuvable") from exc
    return StreamingResponse(
        stream,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=900"},
    )


__all__ = ["router", "_serve", "AuthenticationError"]
