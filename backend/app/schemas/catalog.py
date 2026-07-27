"""Schémas articles, photos et variantes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ArticleCondition, ArticleStatus, PhotoStatus, VariantStatus


class ArticleCreate(BaseModel):
    sku: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=120)
    category_label: str | None = Field(default=None, max_length=200)
    size_label: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=60)
    material: str | None = Field(default=None, max_length=120)
    condition: ArticleCondition | None = None
    purchase_cost_cents: int = Field(default=0, ge=0)
    target_margin_pct: float | None = Field(default=None, ge=0, le=1000)
    floor_price_cents: int | None = Field(default=None, ge=0)
    quantity: int = Field(default=1, ge=0)
    notes: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ArticleUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=120)
    category_label: str | None = Field(default=None, max_length=200)
    size_label: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=60)
    material: str | None = Field(default=None, max_length=120)
    condition: ArticleCondition | None = None
    status: ArticleStatus | None = None
    purchase_cost_cents: int | None = Field(default=None, ge=0)
    target_margin_pct: float | None = Field(default=None, ge=0, le=1000)
    floor_price_cents: int | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, ge=0)
    notes: str | None = None
    attributes: dict[str, Any] | None = None


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_photo_id: uuid.UUID
    variant_index: int
    status: VariantStatus
    width: int | None
    height: int | None
    byte_size: int | None
    phash: str | None
    #: Distance de Hamming avec la photo source (0-64). Affichée à
    #: l'utilisateur : c'est la mesure de « à quel point cette variante est
    #: différente de l'originale ».
    phash_distance_to_source: int | None
    background_replaced: bool
    recipe: dict[str, Any]
    failure_reason: str | None
    render_count: int
    render_ms: int | None
    rendered_at: datetime | None
    url: str | None = None


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    article_id: uuid.UUID
    position: int
    content_type: str
    byte_size: int
    width: int
    height: int
    status: PhotoStatus
    original_filename: str | None
    created_at: datetime
    url: str | None = None
    variants: list[VariantOut] = Field(default_factory=list)


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    title: str | None
    description: str | None
    brand: str | None
    category_label: str | None
    size_label: str | None
    color: str | None
    material: str | None
    condition: ArticleCondition | None
    status: ArticleStatus
    quantity: int
    purchase_cost_cents: int
    target_margin_pct: float | None
    floor_price_cents: int | None
    currency: str
    notes: str | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ArticleDetailOut(ArticleOut):
    photos: list[PhotoOut] = Field(default_factory=list)


class ArticleListOut(BaseModel):
    items: list[ArticleOut]
    total: int
    limit: int
    offset: int


class PhotoReorderRequest(BaseModel):
    photo_ids: list[uuid.UUID] = Field(min_length=1)


class GenerateVariantsRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=6)
    #: Rendu immédiat (utile en développement et pour les tests) au lieu de
    #: passer par la file. En production, laisser `false`.
    synchronous: bool = False


class VariantDecisionRequest(BaseModel):
    accepted: bool


class VariantJobOut(BaseModel):
    variants: list[VariantOut]
    queued: bool
