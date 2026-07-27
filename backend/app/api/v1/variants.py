"""Routes variantes : consultation, régénération, acceptation/refus."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, StreamingResponse

from app.api.deps import Context, DbSession
from app.api.serializers import serialize_variant
from app.api.v1.photos import _serve
from app.schemas.catalog import VariantDecisionRequest, VariantOut
from app.services import variant_service
from app.services.media import verify_media_token

router = APIRouter(tags=["variants"])


@router.get("/articles/{article_id}/variants", response_model=list[VariantOut])
def list_article_variants(
    article_id: uuid.UUID, db: DbSession, context: Context
) -> list[VariantOut]:
    variants = variant_service.list_variants(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    return [serialize_variant(variant, context.workspace_id) for variant in variants]


@router.get("/photos/{photo_id}/variants", response_model=list[VariantOut])
def list_photo_variants(photo_id: uuid.UUID, db: DbSession, context: Context) -> list[VariantOut]:
    variants = variant_service.list_variants(
        db, workspace_id=context.workspace_id, photo_id=photo_id
    )
    return [serialize_variant(variant, context.workspace_id) for variant in variants]


@router.get("/variants/{variant_id}", response_model=VariantOut)
def get_variant(variant_id: uuid.UUID, db: DbSession, context: Context) -> VariantOut:
    variant = variant_service.get_variant(
        db, workspace_id=context.workspace_id, variant_id=variant_id
    )
    return serialize_variant(variant, context.workspace_id)


@router.post("/variants/{variant_id}/regenerate", response_model=VariantOut)
def regenerate_variant(variant_id: uuid.UUID, db: DbSession, context: Context) -> VariantOut:
    variant = variant_service.regenerate_variant(
        db, workspace_id=context.workspace_id, variant_id=variant_id
    )
    return serialize_variant(variant, context.workspace_id)


@router.post("/variants/{variant_id}/decision", response_model=VariantOut)
def decide_variant(
    variant_id: uuid.UUID, payload: VariantDecisionRequest, db: DbSession, context: Context
) -> VariantOut:
    variant = variant_service.set_variant_decision(
        db,
        workspace_id=context.workspace_id,
        variant_id=variant_id,
        accepted=payload.accepted,
    )
    return serialize_variant(variant, context.workspace_id)


@router.get("/variants/{variant_id}/file", response_model=None)
def serve_variant(
    variant_id: uuid.UUID,
    db: DbSession,
    token: str = Query(..., description="Jeton média signé"),
) -> StreamingResponse | RedirectResponse:
    workspace_id = verify_media_token(token, kind="variant", object_id=variant_id)
    variant = variant_service.get_variant(db, workspace_id=workspace_id, variant_id=variant_id)
    return _serve(variant.storage_key, variant.content_type)
