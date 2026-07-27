"""Conversion modèles → schémas de sortie, avec URL média signées."""

from __future__ import annotations

import uuid

from app.models.catalog import Article, ArticlePhoto, PhotoVariant
from app.schemas.catalog import ArticleDetailOut, ArticleOut, PhotoOut, VariantOut
from app.services.media import media_url


def serialize_variant(variant: PhotoVariant, workspace_id: uuid.UUID) -> VariantOut:
    out = VariantOut.model_validate(variant)
    if variant.storage_key:
        out.url = media_url(kind="variant", object_id=variant.id, workspace_id=workspace_id)
    return out


def serialize_photo(
    photo: ArticlePhoto, workspace_id: uuid.UUID, variants: list[PhotoVariant] | None = None
) -> PhotoOut:
    out = PhotoOut.model_validate(photo)
    out.url = media_url(kind="photo", object_id=photo.id, workspace_id=workspace_id)
    source = photo.variants if variants is None else variants
    out.variants = [serialize_variant(variant, workspace_id) for variant in source]
    return out


def serialize_article(article: Article) -> ArticleOut:
    return ArticleOut.model_validate(article)


def serialize_article_detail(article: Article, workspace_id: uuid.UUID) -> ArticleDetailOut:
    out = ArticleDetailOut.model_validate(article)
    out.photos = [serialize_photo(photo, workspace_id) for photo in article.photos]
    return out
