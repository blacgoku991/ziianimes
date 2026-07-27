"""Jetons d'accès média à durée courte.

Une balise `<img>` ne peut pas porter d'en-tête `Authorization`. Plutôt que
d'exposer les fichiers en clair ou de basculer sur des cookies (et leur lot
de CSRF), chaque URL d'image embarque un jeton signé, lié à l'objet, à
l'espace de travail et à une expiration courte.
"""

from __future__ import annotations

import uuid
from typing import Literal

from app.core.errors import AuthenticationError
from app.core.security import TokenError, create_token, decode_token

MediaKind = Literal["photo", "variant"]
MEDIA_TOKEN_TTL_SECONDS = 15 * 60


def create_media_token(*, kind: MediaKind, object_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    token, _, _ = create_token(
        subject=object_id,
        token_type="access",
        ttl_seconds=MEDIA_TOKEN_TTL_SECONDS,
        extra_claims={"scope": "media", "kind": kind, "ws": str(workspace_id)},
    )
    return token


def verify_media_token(token: str, *, kind: MediaKind, object_id: uuid.UUID) -> uuid.UUID:
    """Retourne l'identifiant d'espace de travail autorisé par le jeton."""
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise AuthenticationError("jeton média invalide") from exc
    if payload.get("scope") != "media" or payload.get("kind") != kind:
        raise AuthenticationError("jeton média invalide")
    if payload.get("sub") != str(object_id):
        raise AuthenticationError("jeton média invalide")
    try:
        return uuid.UUID(str(payload.get("ws")))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("jeton média invalide") from exc


def media_url(*, kind: MediaKind, object_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    token = create_media_token(kind=kind, object_id=object_id, workspace_id=workspace_id)
    path = "photos" if kind == "photo" else "variants"
    return f"/api/v1/{path}/{object_id}/file?token={token}"
