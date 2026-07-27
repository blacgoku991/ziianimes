"""Hachage de mots de passe et émission/vérification de jetons JWT."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        # Hash corrompu ou schéma inconnu : on refuse sans faire tomber l'API.
        return False


def needs_rehash(password_hash: str) -> bool:
    return _pwd_context.needs_update(password_hash)


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_token(
    *,
    subject: uuid.UUID | str,
    token_type: TokenType,
    ttl_seconds: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Retourne `(jeton_encodé, jti, expiration)`.

    Le `jti` est renvoyé pour permettre le stockage/la révocation côté base
    des jetons de rafraîchissement.
    """
    if ttl_seconds is None:
        ttl_seconds = (
            settings.access_token_ttl_seconds
            if token_type == "access"
            else settings.refresh_token_ttl_seconds
        )
    issued_at = utcnow()
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "jti": jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    encoded = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded, jti, expires_at


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Décode et valide un jeton. Lève `TokenError` si invalide."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # signature, expiration, format
        raise TokenError(str(exc)) from exc
    if expected_type is not None and payload.get("typ") != expected_type:
        raise TokenError("type de jeton inattendu")
    return payload


class TokenError(Exception):
    """Jeton illisible, expiré ou de type inattendu."""


def generate_opaque_token(nbytes: int = 32) -> str:
    """Jeton opaque (réinitialisation de mot de passe, invitations)."""
    return secrets.token_urlsafe(nbytes)


def hash_opaque_token(token: str) -> str:
    """Empreinte stockée en base : le jeton en clair ne persiste jamais."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
