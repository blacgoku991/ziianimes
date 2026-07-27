"""Chiffrement au repos des secrets marketplace (sessions, tokens OAuth).

Le contenu n'est jamais stocké ni journalisé en clair. On utilise
AES-256-GCM avec un nonce aléatoire par message et des données
authentifiées additionnelles (AAD) liant le chiffré à son propriétaire :
un blob volé sur une ligne ne peut pas être rejoué sur une autre.

Le format sérialisé est ``v1.<nonce_b64>.<ciphertext_b64>`` afin de pouvoir
faire évoluer le schéma (rotation de clé, autre algorithme) sans migration
destructive.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_VERSION = "v1"
_NONCE_BYTES = 12


class DecryptionError(Exception):
    """Chiffré illisible : clé incorrecte, blob altéré ou AAD non concordante."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _aesgcm() -> AESGCM:
    return AESGCM(settings.encryption_key_bytes())


def encrypt_secret(plaintext: str | bytes, *, aad: str) -> str:
    """Chiffre `plaintext`. `aad` doit identifier la ligne (ex. `workspace:<id>`)."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = _aesgcm().encrypt(nonce, plaintext, aad.encode("utf-8"))
    return f"{_VERSION}.{_b64e(nonce)}.{_b64e(ciphertext)}"


def decrypt_secret(token: str, *, aad: str) -> bytes:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _VERSION:
        raise DecryptionError("format de chiffré inconnu")
    try:
        nonce, ciphertext = _b64d(parts[1]), _b64d(parts[2])
        return _aesgcm().decrypt(nonce, ciphertext, aad.encode("utf-8"))
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("déchiffrement impossible") from exc


def decrypt_secret_str(token: str, *, aad: str) -> str:
    return decrypt_secret(token, aad=aad).decode("utf-8")
