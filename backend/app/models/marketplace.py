"""Comptes marketplace rattachés, publications et messagerie.

Le schéma est posé dès l'étape 1 pour figer les invariants (idempotence,
unicité article/compte, journal d'événements). La logique de publication
n'arrive qu'à l'étape 4.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, TimestampType, UUIDType
from app.models.enums import (
    AccountAuthType,
    AccountStatus,
    MessageDirection,
    Platform,
    PublicationEventType,
    PublicationMode,
    PublicationStatus,
)
from app.models.identity import enum_col
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, workspace_fk


class MarketplaceAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Compte marketplace **appartenant déjà à l'utilisateur**, rattaché à l'outil.

    Aucune création de compte n'est faite par le produit. Les secrets
    (cookies de session, jetons OAuth) sont chiffrés au repos via
    `app.core.crypto`, avec l'identifiant du compte en données authentifiées.
    """

    __tablename__ = "marketplace_accounts"
    __table_args__ = (
        sa.UniqueConstraint(
            "workspace_id", "platform", "label", name="uq_marketplace_accounts_workspace_label"
        ),
        sa.Index("ix_marketplace_accounts_workspace_platform", "workspace_id", "platform"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    platform: Mapped[Platform] = mapped_column(enum_col(Platform), nullable=False)
    #: Nom donné par l'utilisateur, typiquement la niche (« vintage », « street »).
    label: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    niche: Mapped[str | None] = mapped_column(sa.String(80))
    external_username: Mapped[str | None] = mapped_column(sa.String(120))
    external_user_id: Mapped[str | None] = mapped_column(sa.String(120))

    auth_type: Mapped[AccountAuthType] = mapped_column(enum_col(AccountAuthType), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        enum_col(AccountStatus), nullable=False, default=AccountStatus.needs_reauth
    )

    #: Blob chiffré (jamais journalisé, jamais renvoyé par l'API).
    encrypted_credentials: Mapped[str | None] = mapped_column(sa.Text)
    credentials_updated_at: Mapped[datetime | None] = mapped_column(TimestampType)
    #: Identifiant du contexte navigateur persistant, isolé par compte.
    browser_profile_key: Mapped[str | None] = mapped_column(sa.String(200))

    last_health_check_at: Mapped[datetime | None] = mapped_column(TimestampType)
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    #: Garde-fou anti-cadence : dernière action automatisée sur ce compte.
    last_action_at: Mapped[datetime | None] = mapped_column(TimestampType)
    daily_action_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    daily_action_reset_at: Mapped[datetime | None] = mapped_column(TimestampType)

    settings: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)


class Publication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une annonce d'un article sur un compte marketplace donné."""

    __tablename__ = "publications"
    __table_args__ = (
        # Un article ne peut pas être publié deux fois sur le même compte.
        sa.UniqueConstraint(
            "article_id", "marketplace_account_id", name="uq_publications_article_account"
        ),
        # Rejeu sans doublon des jobs de publication.
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_publications_workspace_idempotency"
        ),
        sa.Index("ix_publications_workspace_status", "workspace_id", "status"),
        sa.CheckConstraint("price_cents > 0", name="price_positive"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mode: Mapped[PublicationMode] = mapped_column(
        enum_col(PublicationMode), nullable=False, default=PublicationMode.draft
    )
    status: Mapped[PublicationStatus] = mapped_column(
        enum_col(PublicationStatus), nullable=False, default=PublicationStatus.pending, index=True
    )

    #: Textes propres à cette publication : deux comptes ne doivent jamais
    #: recevoir le même titre ni la même description.
    title: Mapped[str | None] = mapped_column(sa.String(255))
    description: Mapped[str | None] = mapped_column(sa.Text)
    price_cents: Mapped[int | None] = mapped_column(sa.Integer)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False, default="EUR")

    remote_listing_id: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    remote_url: Mapped[str | None] = mapped_column(sa.String(500))
    remote_category_id: Mapped[str | None] = mapped_column(sa.String(120))
    remote_brand_id: Mapped[str | None] = mapped_column(sa.String(120))
    remote_size_id: Mapped[str | None] = mapped_column(sa.String(120))

    idempotency_key: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    #: Progression du job pour la reprise : `{"photos_uploaded": true, ...}`.
    checkpoint: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(sa.Text)

    #: Prix réellement encaissé, renseigné à la vente. Sert de base aux
    #: comparables : c'est la seule donnée de vente réelle dont on dispose.
    sale_price_cents: Mapped[int | None] = mapped_column(sa.Integer)
    #: Frais prélevés par la plateforme, et port à la charge du vendeur.
    fee_cents: Mapped[int | None] = mapped_column(sa.Integer)
    shipping_cents: Mapped[int | None] = mapped_column(sa.Integer)
    net_proceeds_cents: Mapped[int | None] = mapped_column(sa.Integer)
    #: Index du jeu de textes utilisé : deux comptes ne partagent jamais le
    #: même titre ni la même description.
    copy_variant_index: Mapped[int | None] = mapped_column(sa.Integer)

    published_at: Mapped[datetime | None] = mapped_column(TimestampType)
    sold_at: Mapped[datetime | None] = mapped_column(TimestampType)
    #: Prochaine synchronisation d'état prévue pour cette annonce.
    next_sync_at: Mapped[datetime | None] = mapped_column(TimestampType, index=True)
    unpublished_at: Mapped[datetime | None] = mapped_column(TimestampType)
    last_synced_at: Mapped[datetime | None] = mapped_column(TimestampType)
    last_relisted_at: Mapped[datetime | None] = mapped_column(TimestampType)

    views_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    favorites_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    events: Mapped[list[PublicationEvent]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )


class PublicationEvent(UUIDPrimaryKeyMixin, Base):
    """Journal immuable : chaque transition d'une publication est tracée."""

    __tablename__ = "publication_events"
    __table_args__ = (
        sa.Index("ix_publication_events_publication_created", "publication_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[PublicationEventType] = mapped_column(
        enum_col(PublicationEventType), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, server_default=sa.func.now()
    )

    publication: Mapped[Publication] = relationship(back_populates="events")


class PublicationSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Règles de remontée et de baisse de prix par paliers (étape 5)."""

    __tablename__ = "publication_schedules"

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    publication_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: `relist` (remontée) ou `price_drop` (baisse programmée).
    kind: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    #: Paliers : `[{"after_days": 14, "drop_pct": 5}, ...]`.
    steps: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    next_run_at: Mapped[datetime | None] = mapped_column(TimestampType, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(TimestampType)
    step_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)


class MessageThread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Fil de discussion unifié (étape 6)."""

    __tablename__ = "message_threads"
    __table_args__ = (
        sa.UniqueConstraint(
            "marketplace_account_id",
            "remote_thread_id",
            name="uq_message_threads_account_remote",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("marketplace_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("publications.id", ondelete="SET NULL"), index=True
    )
    remote_thread_id: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(sa.String(120))
    subject: Mapped[str | None] = mapped_column(sa.String(255))
    last_message_at: Mapped[datetime | None] = mapped_column(TimestampType, index=True)
    unread_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        sa.UniqueConstraint("thread_id", "remote_message_id", name="uq_messages_thread_remote"),
    )

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("message_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    remote_message_id: Mapped[str | None] = mapped_column(sa.String(120))
    direction: Mapped[MessageDirection] = mapped_column(enum_col(MessageDirection), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: Offre reçue le cas échéant, en centimes.
    offer_price_cents: Mapped[int | None] = mapped_column(sa.Integer)
    sent_at: Mapped[datetime | None] = mapped_column(TimestampType)
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, server_default=sa.func.now()
    )


class QuickReply(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Réponses rapides pré-enregistrées."""

    __tablename__ = "quick_replies"

    workspace_id: Mapped[uuid.UUID] = workspace_fk()
    label: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    usage_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
