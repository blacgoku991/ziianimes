"""Utilisateurs, espaces de travail et jetons d'authentification."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import JSONType, TimestampType, UUIDType
from app.models.enums import SubscriptionStatus, WorkspaceRole
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def enum_col(enum_cls: type, **kwargs: object) -> sa.Enum:
    """Colonne d'énumération : `VARCHAR` + contrainte `CHECK`.

    `create_constraint=True` est explicite : SQLAlchemy 2.0 ne crée aucune
    contrainte par défaut, et la validation resterait alors purement
    applicative. Or les workers écrivent dans les mêmes tables que l'API —
    la base doit refuser une valeur inconnue quelle qu'en soit la source.

    Le nom de la contrainte est dérivé de la colonne plutôt que du nom de
    la classe Python : une énumération renommée en Python ne doit pas
    déclencher une migration de contrainte.
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=32,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [item.value for item in e],
        **kwargs,  # type: ignore[arg-type]
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    #: Toujours stocké en minuscules — l'unicité doit être insensible à la casse.
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(sa.String(200))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(TimestampType)
    last_login_at: Mapped[datetime | None] = mapped_column(TimestampType)

    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Frontière d'isolation : un revendeur = un espace de travail."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    slug: Mapped[str] = mapped_column(sa.String(140), nullable=False, unique=True)

    # -- Facturation (colonnes posées dès maintenant, Stripe branché plus tard)
    plan: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="trial")
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        enum_col(SubscriptionStatus), nullable=False, default=SubscriptionStatus.trialing
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(TimestampType)
    stripe_customer_id: Mapped[str | None] = mapped_column(sa.String(80), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(sa.String(80), unique=True)

    #: Horodatage de l'acceptation de l'avertissement « automatisation vs CGU ».
    #: Tant qu'il est nul, aucune publication automatique n'est autorisée.
    automation_notice_accepted_at: Mapped[datetime | None] = mapped_column(TimestampType)

    settings: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        enum_col(WorkspaceRole), nullable=False, default=WorkspaceRole.owner
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jetons de rafraîchissement révocables.

    Seule l'empreinte est stockée : une fuite de la base ne permet pas de
    rejouer une session.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TimestampType)
    user_agent: Mapped[str | None] = mapped_column(sa.String(400))
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TimestampType)
