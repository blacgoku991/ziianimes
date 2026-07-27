"""Mixins partagés par les modèles."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.types import TimestampType, UUIDType


class UUIDPrimaryKeyMixin:
    """Clés primaires UUID : générées côté application.

    Les identifiants circulent dans les URL et les webhooks ; un entier
    séquentiel exposerait le volume d'activité et faciliterait l'énumération
    entre locataires.
    """

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampType,
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class WorkspaceScopedMixin:
    """Toute donnée métier porte son `workspace_id`.

    C'est la colonne sur laquelle repose l'isolation multi-locataire : elle
    est non nulle, indexée, et fait partie des contraintes d'unicité
    composées. Aucune requête métier ne doit s'en passer — voir
    `app.services.scoping`.
    """

    @property
    def _fk_workspace(self) -> None:  # pragma: no cover - documentation
        return None


def workspace_fk(**kwargs: object) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUIDType,
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        **kwargs,  # type: ignore[arg-type]
    )
