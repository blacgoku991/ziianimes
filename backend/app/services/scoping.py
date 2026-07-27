"""Accès aux entités toujours filtrés par espace de travail.

Le multi-locataire ne tient pas si chaque requête doit *penser* à ajouter
`workspace_id == ...`. Toutes les lectures d'entité passent donc par ces
helpers, et une entité introuvable *dans le bon espace* renvoie 404 — jamais
403, qui confirmerait l'existence de la ressource chez quelqu'un d'autre.
"""

from __future__ import annotations

import uuid
from typing import TypeVar

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError

T = TypeVar("T")


def scoped_query(model: type[T], workspace_id: uuid.UUID) -> sa.Select:
    return sa.select(model).where(model.workspace_id == workspace_id)  # type: ignore[attr-defined]


def get_scoped(
    db: Session,
    model: type[T],
    entity_id: uuid.UUID,
    workspace_id: uuid.UUID,
    *,
    label: str = "ressource",
) -> T:
    entity = db.execute(
        scoped_query(model, workspace_id).where(model.id == entity_id)  # type: ignore[attr-defined]
    ).scalar_one_or_none()
    if entity is None:
        raise NotFoundError(f"{label} introuvable")
    return entity
