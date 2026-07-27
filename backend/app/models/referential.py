"""Référentiels plateformes et correspondances (étape 2).

Les arbres de catégories, listes de marques et grilles de tailles sont
partagés par tous les espaces de travail : ce sont des données publiques de
plateforme, pas des données locataires. Seules les correspondances
(`CategoryMapping`) peuvent être surchargées par espace de travail.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType, TimestampType, UUIDType
from app.models.enums import MappingSource, Platform
from app.models.identity import enum_col
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PlatformCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_categories"
    __table_args__ = (
        sa.UniqueConstraint("platform", "external_id", name="uq_platform_categories_platform_ext"),
        sa.Index("ix_platform_categories_platform_leaf", "platform", "is_leaf"),
    )

    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    external_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    #: Chemin complet lisible : « Hommes > Vêtements > Sweats > Sweatshirts ».
    path: Mapped[str] = mapped_column(sa.String(600), nullable=False)
    level: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    is_leaf: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: Certaines plateformes n'autorisent des tailles que sur certains nœuds.
    size_group_external_id: Mapped[str | None] = mapped_column(sa.String(120))
    raw: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(TimestampType)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)


class PlatformBrand(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_brands"
    __table_args__ = (
        sa.UniqueConstraint("platform", "external_id", name="uq_platform_brands_platform_ext"),
        sa.Index("ix_platform_brands_platform_normalized", "platform", "normalized_name"),
    )

    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    external_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    #: Minuscules, sans accents ni ponctuation — clé de rapprochement.
    normalized_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    fetched_at: Mapped[datetime | None] = mapped_column(TimestampType)


class PlatformSize(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Grille de tailles : dépend de la catégorie, d'où le groupe."""

    __tablename__ = "platform_sizes"
    __table_args__ = (
        sa.UniqueConstraint("platform", "external_id", name="uq_platform_sizes_platform_ext"),
        sa.Index("ix_platform_sizes_platform_group", "platform", "size_group_external_id"),
    )

    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    external_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    size_group_external_id: Mapped[str | None] = mapped_column(sa.String(120))
    name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(TimestampType)


class CategoryMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Correspondance « libellé IA » → nœud de catégorie plateforme.

    `workspace_id` nul = correspondance globale, entretenue par l'éditeur.
    Une ligne portant un `workspace_id` surcharge la globale pour ce
    locataire (choix utilisateur mémorisé).
    """

    __tablename__ = "category_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id",
            "platform",
            "source_key",
            name="uq_category_mappings_workspace_platform_key",
        ),
        sa.Index("ix_category_mappings_platform_key", "platform", "source_key"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    #: Libellé normalisé issu de l'IA : « sweat nike gris » → « sweat ».
    source_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    category_external_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=1.0)
    source: Mapped[MappingSource] = mapped_column(
        enum_col(MappingSource), nullable=False, default=MappingSource.manual
    )
    hit_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)


class BrandMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "brand_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "platform", "source_key", name="uq_brand_mappings_workspace_key"
        ),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    source_key: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    brand_external_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=1.0)
    source: Mapped[MappingSource] = mapped_column(
        enum_col(MappingSource), nullable=False, default=MappingSource.manual
    )


class PriceSuggestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fourchette de prix calculée à partir de comparables vendus."""

    __tablename__ = "price_suggestions"
    __table_args__ = (sa.Index("ix_price_suggestions_article_platform", "article_id", "platform"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    low_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    median_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    high_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Comparables retenus, pour pouvoir justifier la suggestion à l'écran.
    comparables: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    computed_at: Mapped[datetime | None] = mapped_column(TimestampType)


class AiGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Traçabilité et coût des appels IA (analyse vision, rédaction)."""

    __tablename__ = "ai_generations"
    __table_args__ = (
        sa.Index("ix_ai_generations_workspace_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("articles.id", ondelete="SET NULL"), index=True
    )
    #: `vision_analysis` | `listing_copy` | `category_match`.
    kind: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    input_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    cost_micros: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    result: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(sa.Text)
