"""Dépendances FastAPI : session base, utilisateur courant, espace de travail."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError
from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.identity import User, Workspace, WorkspaceMember

DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class CurrentContext:
    """Contexte d'appel : qui agit, dans quel espace de travail."""

    user: User
    workspace: Workspace
    role: str

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id


def get_current_user(db: DbSession, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("authentification requise")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise AuthenticationError("jeton invalide ou expiré") from exc
    # Les jetons média n'ouvrent que l'accès à un fichier précis : ils ne
    # doivent jamais servir d'authentification générale.
    if payload.get("scope") == "media":
        raise AuthenticationError("jeton invalide ou expiré")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("jeton invalide") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("compte indisponible")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_context(
    db: DbSession,
    user: CurrentUser,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> CurrentContext:
    """Résout l'espace de travail actif.

    En-tête `X-Workspace-Id` optionnel : sans lui, on prend le premier
    espace de l'utilisateur. L'appartenance est vérifiée en base à chaque
    requête — jamais déduite du jeton, qui pourrait être antérieur à une
    révocation d'accès.
    """
    query = (
        sa.select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
    )
    if x_workspace_id:
        try:
            query = query.where(Workspace.id == uuid.UUID(x_workspace_id))
        except ValueError as exc:
            raise AuthenticationError("identifiant d'espace de travail invalide") from exc
    else:
        query = query.order_by(WorkspaceMember.created_at.asc())

    row = db.execute(query.limit(1)).first()
    if row is None:
        raise AuthenticationError("aucun espace de travail accessible")
    workspace, role = row
    return CurrentContext(user=user, workspace=workspace, role=str(getattr(role, "value", role)))


Context = Annotated[CurrentContext, Depends(get_context)]
