"""Rattachement des comptes marketplace **que l'utilisateur possède déjà**.

Aucune création de compte, aucun contournement de CAPTCHA, aucune réception
de SMS : l'utilisateur connecte des comptes existants, et c'est la ligne qui
sépare un outil professionnel d'un outil de fraude.

Deux points de sécurité structurants :

* les secrets (cookies de session, jetons OAuth) sont chiffrés au repos avec
  l'identifiant du compte en données authentifiées — un blob volé sur une
  ligne ne peut pas être rejoué sur une autre ;
* chaque compte a un **profil navigateur strictement isolé**, dérivé de son
  identifiant. Deux comptes ne partagent jamais un contexte : c'est ce qui
  ferait le lien entre eux du point de vue de la plateforme.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import DecryptionError, decrypt_secret_str, encrypt_secret
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.enums import AccountAuthType, AccountStatus, Platform
from app.models.marketplace import MarketplaceAccount

logger = get_logger(__name__)

#: Plateformes disposant d'une API officielle : OAuth, pas de navigateur.
OAUTH_PLATFORMS = {Platform.ebay, Platform.depop}


def credential_aad(account_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    """Données authentifiées liant un chiffré à sa ligne."""
    return f"marketplace_account:{account_id}:workspace:{workspace_id}"


def create_account(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    platform: Platform,
    label: str,
    niche: str | None = None,
    external_username: str | None = None,
) -> MarketplaceAccount:
    auth_type = (
        AccountAuthType.oauth if platform in OAUTH_PLATFORMS else AccountAuthType.browser_session
    )
    account = MarketplaceAccount(
        workspace_id=workspace_id,
        platform=platform,
        label=label.strip(),
        niche=niche,
        external_username=external_username,
        auth_type=auth_type,
        status=AccountStatus.needs_reauth,
    )
    account.browser_profile_key = f"{workspace_id}/{account.id}"
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("un compte porte déjà ce nom sur cette plateforme") from exc
    logger.info(
        "marketplace_account_created",
        account_id=str(account.id),
        platform=platform.value,
        auth_type=auth_type.value,
    )
    return account


def get_account(
    db: Session, *, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> MarketplaceAccount:
    account = db.execute(
        sa.select(MarketplaceAccount).where(
            MarketplaceAccount.id == account_id,
            MarketplaceAccount.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("compte marketplace introuvable")
    return account


def list_accounts(
    db: Session, *, workspace_id: uuid.UUID, platform: Platform | None = None
) -> list[MarketplaceAccount]:
    statement = sa.select(MarketplaceAccount).where(MarketplaceAccount.workspace_id == workspace_id)
    if platform is not None:
        statement = statement.where(MarketplaceAccount.platform == platform)
    return list(
        db.execute(statement.order_by(MarketplaceAccount.platform, MarketplaceAccount.label))
        .scalars()
        .all()
    )


def store_credentials(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    account: MarketplaceAccount,
    payload: dict[str, Any],
) -> MarketplaceAccount:
    """Chiffre et enregistre les secrets d'un compte.

    Le contenu n'est jamais journalisé, jamais renvoyé par l'API, et n'est
    déchiffré que dans le worker au moment d'ouvrir le navigateur.
    """
    if not payload:
        raise ValidationError("aucun secret fourni")
    account.encrypted_credentials = encrypt_secret(
        json.dumps(payload, ensure_ascii=False),
        aad=credential_aad(account.id, workspace_id),
    )
    account.credentials_updated_at = datetime.now(UTC)
    account.status = AccountStatus.active
    account.last_error = None
    db.flush()
    logger.info(
        "marketplace_credentials_stored",
        account_id=str(account.id),
        keys=sorted(payload.keys()),  # les clés, jamais les valeurs
    )
    return account


def load_credentials(
    *, account: MarketplaceAccount, workspace_id: uuid.UUID
) -> dict[str, Any] | None:
    if not account.encrypted_credentials:
        return None
    try:
        raw = decrypt_secret_str(
            account.encrypted_credentials, aad=credential_aad(account.id, workspace_id)
        )
    except DecryptionError:
        logger.error("marketplace_credentials_undecipherable", account_id=str(account.id))
        return None
    return json.loads(raw)


def mark_needs_reauth(
    db: Session, *, account: MarketplaceAccount, reason: str
) -> MarketplaceAccount:
    """Passe un compte en « reconnexion nécessaire ».

    Les secrets sont effacés : une session expirée n'a aucune valeur, et la
    garder augmente la surface d'exposition sans rien apporter.
    """
    account.status = AccountStatus.needs_reauth
    account.last_error = reason[:500]
    account.encrypted_credentials = None
    account.credentials_updated_at = None
    db.flush()
    logger.warning("marketplace_account_needs_reauth", account_id=str(account.id), reason=reason)
    return account


def record_health_check(
    db: Session, *, account: MarketplaceAccount, healthy: bool, detail: str | None = None
) -> MarketplaceAccount:
    account.last_health_check_at = datetime.now(UTC)
    if healthy:
        account.status = AccountStatus.active
        account.last_error = None
    else:
        account.status = AccountStatus.needs_reauth
        account.last_error = (detail or "contrôle de santé en échec")[:500]
    db.flush()
    return account


def health_overview(db: Session, *, workspace_id: uuid.UUID) -> list[dict]:
    """Écran de santé des connexions."""
    accounts = list_accounts(db, workspace_id=workspace_id)
    now = datetime.now(UTC)
    overview = []
    for account in accounts:
        stale_check = account.last_health_check_at is None or (
            now - account.last_health_check_at
        ) > timedelta(days=1)
        overview.append(
            {
                "id": str(account.id),
                "platform": account.platform.value,
                "label": account.label,
                "niche": account.niche,
                "external_username": account.external_username,
                "auth_type": account.auth_type.value,
                "status": account.status.value,
                "has_credentials": bool(account.encrypted_credentials),
                "credentials_updated_at": (
                    account.credentials_updated_at.isoformat()
                    if account.credentials_updated_at
                    else None
                ),
                "last_health_check_at": (
                    account.last_health_check_at.isoformat()
                    if account.last_health_check_at
                    else None
                ),
                "health_check_overdue": stale_check,
                "last_error": account.last_error,
                "daily_action_count": account.daily_action_count,
                "daily_action_cap": settings.publish_daily_cap_per_account,
            }
        )
    return overview


def browser_profile_dir(account: MarketplaceAccount) -> Path:
    """Répertoire de profil navigateur, strictement propre au compte.

    À monter en `tmpfs` en production : le profil contient la session en
    clair pendant toute la durée du job — c'est la fenêtre d'exposition
    réelle, bien plus que la table Postgres. Voir `docs/REVUE_SPEC.md` §3.2.
    """
    key = account.browser_profile_key or f"{account.workspace_id}/{account.id}"
    path = Path(settings.browser_profiles_root).resolve() / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def delete_account(db: Session, *, workspace_id: uuid.UUID, account_id: uuid.UUID) -> None:
    account = get_account(db, workspace_id=workspace_id, account_id=account_id)
    profile = browser_profile_dir(account)
    db.delete(account)
    db.flush()
    # Le profil navigateur part avec le compte : il contient la session.
    import shutil

    shutil.rmtree(profile, ignore_errors=True)
    logger.info("marketplace_account_deleted", account_id=str(account_id))
