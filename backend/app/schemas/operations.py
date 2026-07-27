"""Schémas des étapes 2 à 6."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AccountStatus,
    ArticleStatus,
    Platform,
    PublicationMode,
    PublicationStatus,
)

# -- Étape 2 : enrichissement ------------------------------------------------


class AnalyseRequest(BaseModel):
    hint: str | None = Field(default=None, max_length=500)
    #: Écrase les champs déjà renseignés. Faux par défaut : une correction
    #: manuelle de l'utilisateur ne doit pas être perdue.
    overwrite: bool = False


class CopyRequest(BaseModel):
    variant_count: int = Field(default=3, ge=1, le=8)
    niche: str | None = Field(default=None, max_length=40)


class AnalysisOut(BaseModel):
    garment_type: str | None
    brand: str | None
    brand_confidence: float
    color: str | None
    material: str | None
    fit: str | None
    size_label: str | None
    condition: str | None
    defects: list[str]
    has_visible_logo_or_text: bool
    keywords: list[str]


class CopyOut(BaseModel):
    variants: list[dict[str, Any]]


# -- Étape 2 : référentiels et rapprochement ---------------------------------


class MatchRequest(BaseModel):
    platform: Platform = Platform.vinted
    label: str = Field(min_length=1, max_length=200)
    context: str | None = Field(default=None, max_length=300)


class MatchOut(BaseModel):
    best: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    needs_user_choice: bool


class RememberChoiceRequest(BaseModel):
    platform: Platform = Platform.vinted
    label: str = Field(min_length=1, max_length=200)
    external_id: str = Field(min_length=1, max_length=120)


class ReferentialEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str
    path: str | None = None


# -- Étape 2 : prix ----------------------------------------------------------


class PriceRequest(BaseModel):
    platform: Platform = Platform.vinted


class PriceOut(BaseModel):
    low_cents: int
    median_cents: int
    high_cents: int
    recommended_cents: int
    floor_cents: int
    sample_size: int
    reliable: bool
    basis: str
    comparables: list[dict[str, Any]]
    margin: dict[str, Any] | None
    warnings: list[str]


# -- Étape 3 : stock ---------------------------------------------------------


class StockQuery(BaseModel):
    status: ArticleStatus | None = None
    platform: Platform | None = None
    search: str | None = None
    stale_only: bool = False


class StockOut(BaseModel):
    items: list[dict[str, Any]]
    total: int
    summary: dict[str, Any]


# -- Étape 4 : comptes -------------------------------------------------------


class AccountCreate(BaseModel):
    platform: Platform
    label: str = Field(min_length=1, max_length=80)
    niche: str | None = Field(default=None, max_length=80)
    external_username: str | None = Field(default=None, max_length=120)


class CredentialsRequest(BaseModel):
    """Secrets d'un compte.

    Pour Vinted, `cookies` est la liste de cookies exportée depuis le
    navigateur où l'utilisateur est déjà connecté. Pour les plateformes à
    API, `access_token` et `refresh_token` proviennent du parcours OAuth.
    Ces valeurs ne ressortent jamais de l'API.
    """

    cookies: list[dict[str, Any]] | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    extra: dict[str, Any] | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    label: str
    niche: str | None
    external_username: str | None
    auth_type: str
    status: AccountStatus
    last_error: str | None
    last_health_check_at: datetime | None
    daily_action_count: int
    created_at: datetime


# -- Étape 5 : publications --------------------------------------------------


class PreparePublicationRequest(BaseModel):
    account_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    #: Le brouillon est le comportement par défaut, et le reste.
    mode: PublicationMode = PublicationMode.draft
    price_cents: int | None = Field(default=None, ge=100)
    #: Met en file immédiatement après préparation.
    enqueue: bool = False


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    article_id: uuid.UUID
    marketplace_account_id: uuid.UUID
    mode: PublicationMode
    status: PublicationStatus
    title: str | None
    price_cents: int | None
    currency: str
    remote_url: str | None
    remote_listing_id: str | None
    published_at: datetime | None
    sold_at: datetime | None
    sale_price_cents: int | None
    net_proceeds_cents: int | None
    views_count: int
    attempts: int
    last_error: str | None
    created_at: datetime


class MarkSoldRequest(BaseModel):
    sale_price_cents: int | None = Field(default=None, ge=0)
    shipping_cents: int | None = Field(default=None, ge=0)


class ScheduleRequest(BaseModel):
    kind: str = Field(pattern="^(price_drop|relist)$")
    steps: list[dict[str, Any]] | None = None


# -- Étape 6 : boîte de réception --------------------------------------------


class ReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class QuickReplyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=4000)


class QuickReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    body: str
    usage_count: int


# -- Divers ------------------------------------------------------------------


class AcceptNoticeRequest(BaseModel):
    accepted: bool = True
