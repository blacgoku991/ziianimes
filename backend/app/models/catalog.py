"""Articles, photos sources et variantes générées.

Modèle central « un article, N publications » : l'article porte le stock et
le coût, la publication porte le prix et l'identifiant distant, la variante
porte le fichier image effectivement envoyé à une plateforme donnée.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, TimestampType, UUIDType
from app.models.enums import ArticleCondition, ArticleStatus, PhotoStatus, VariantStatus
from app.models.identity import enum_col
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, workspace_fk


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "sku", name="uq_articles_workspace_id_sku"),
        sa.Index("ix_articles_workspace_status", "workspace_id", "status"),
        sa.CheckConstraint("purchase_cost_cents >= 0", name="purchase_cost_positive"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()

    #: Référence lisible par l'utilisateur, unique dans l'espace de travail.
    sku: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text)

    # -- Caractéristiques (renseignées manuellement, puis par l'IA à l'étape 2)
    brand: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    category_label: Mapped[str | None] = mapped_column(sa.String(200))
    size_label: Mapped[str | None] = mapped_column(sa.String(40))
    color: Mapped[str | None] = mapped_column(sa.String(60))
    material: Mapped[str | None] = mapped_column(sa.String(120))
    condition: Mapped[ArticleCondition | None] = mapped_column(enum_col(ArticleCondition))
    attributes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    # -- Stock et marge
    status: Mapped[ArticleStatus] = mapped_column(
        enum_col(ArticleStatus), nullable=False, default=ArticleStatus.draft, index=True
    )
    quantity: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    purchase_cost_cents: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    target_margin_pct: Mapped[float | None] = mapped_column(sa.Float)
    floor_price_cents: Mapped[int | None] = mapped_column(sa.Integer)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False, default="EUR")

    first_listed_at: Mapped[datetime | None] = mapped_column(TimestampType)
    sold_at: Mapped[datetime | None] = mapped_column(TimestampType)
    notes: Mapped[str | None] = mapped_column(sa.Text)

    #: Suppression logique : une publication distante peut survivre à la
    #: suppression locale, on garde la trace pour pouvoir dépublier.
    deleted_at: Mapped[datetime | None] = mapped_column(TimestampType, index=True)

    photos: Mapped[list[ArticlePhoto]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticlePhoto.position",
    )


class ArticlePhoto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Photo source, conservée en pleine résolution et jamais réencodée."""

    __tablename__ = "article_photos"
    __table_args__ = (
        sa.UniqueConstraint("article_id", "position", name="uq_article_photos_article_id_position"),
        sa.Index("ix_article_photos_workspace_checksum", "workspace_id", "checksum_sha256"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    storage_key: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(sa.String(255))
    content_type: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    byte_size: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    height: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    #: Empreinte exacte : déduplication des envois répétés du même fichier.
    checksum_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: Empreinte perceptuelle de la source, référence pour mesurer l'écart
    #: des variantes générées.
    phash: Mapped[str | None] = mapped_column(sa.String(16))

    status: Mapped[PhotoStatus] = mapped_column(
        enum_col(PhotoStatus), nullable=False, default=PhotoStatus.uploaded
    )

    article: Mapped[Article] = relationship(back_populates="photos")
    variants: Mapped[list[PhotoVariant]] = relationship(
        back_populates="source_photo",
        cascade="all, delete-orphan",
        order_by="PhotoVariant.variant_index",
    )


class PhotoVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Déclinaison d'une photo source, destinée à une publication.

    La régénération réécrit la ligne en place (nouvelle graine, nouveau
    fichier) : l'index de variante reste stable pour l'interface.
    """

    __tablename__ = "photo_variants"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_photo_id", "variant_index", name="uq_photo_variants_photo_index"
        ),
        sa.Index("ix_photo_variants_workspace_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_photo_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("article_photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Rattachement à une publication (étape 4+). Nul tant que la variante
    #: n'est pas affectée à un compte cible.
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("publications.id", ondelete="SET NULL"), index=True
    )

    variant_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    seed: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    #: Recette appliquée, sérialisée : permet de rejouer exactement le rendu.
    recipe: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    storage_key: Mapped[str | None] = mapped_column(sa.String(500))
    content_type: Mapped[str | None] = mapped_column(sa.String(80))
    byte_size: Mapped[int | None] = mapped_column(sa.BigInteger)
    width: Mapped[int | None] = mapped_column(sa.Integer)
    height: Mapped[int | None] = mapped_column(sa.Integer)
    phash: Mapped[str | None] = mapped_column(sa.String(16))
    #: Distance de Hamming avec la source : garantit que la variante ne sera
    #: pas rapprochée de l'originale par un hash perceptuel.
    phash_distance_to_source: Mapped[int | None] = mapped_column(sa.Integer)
    background_replaced: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    status: Mapped[VariantStatus] = mapped_column(
        enum_col(VariantStatus), nullable=False, default=VariantStatus.pending, index=True
    )
    failure_reason: Mapped[str | None] = mapped_column(sa.Text)
    render_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    render_ms: Mapped[int | None] = mapped_column(sa.Integer)
    rendered_at: Mapped[datetime | None] = mapped_column(TimestampType)

    source_photo: Mapped[ArticlePhoto] = relationship(back_populates="variants")
