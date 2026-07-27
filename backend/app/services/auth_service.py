"""Inscription, connexion, rafraîchissement et réinitialisation de mot de passe."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, ValidationError
from app.core.logging import get_logger
from app.core.security import (
    create_token,
    decode_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    utcnow,
    verify_password,
)
from app.models.enums import SubscriptionStatus, WorkspaceRole
from app.models.identity import (
    PasswordResetToken,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMember,
)

logger = get_logger(__name__)

MIN_PASSWORD_LENGTH = 10


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "espace"


def validate_password(password: str) -> None:
    """Politique volontairement simple : longueur d'abord.

    Les règles de composition (majuscule, chiffre, caractère spécial)
    poussent à des mots de passe courts et prévisibles ; la longueur
    minimale est la contrainte qui apporte réellement de l'entropie.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères"
        )
    if len(password) > 200:
        raise ValidationError("mot de passe trop long")


def register_user(
    db: Session, *, email: str, password: str, full_name: str | None, workspace_name: str | None
) -> tuple[User, Workspace]:
    email = normalize_email(email)
    validate_password(password)

    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("un compte existe déjà pour cette adresse") from exc

    workspace = Workspace(
        name=workspace_name or (full_name or email.split("@")[0]),
        slug=_unique_slug(db, slugify(workspace_name or email.split("@")[0])),
        subscription_status=SubscriptionStatus.trialing,
        trial_ends_at=utcnow() + timedelta(days=settings.trial_period_days),
    )
    db.add(workspace)
    db.flush()

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner))
    db.flush()
    logger.info("user_registered", user_id=str(user.id), workspace_id=str(workspace.id))
    return user, workspace


def _unique_slug(db: Session, base: str) -> str:
    slug = base
    suffix = 1
    while db.execute(sa.select(Workspace.id).where(Workspace.slug == slug)).first() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
        if suffix > 10_000:  # garde-fou
            slug = f"{base}-{uuid.uuid4().hex[:8]}"
            break
    return slug


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.execute(
        sa.select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()
    if user is None:
        # Coût de vérification appliqué même sans utilisateur : sinon le
        # temps de réponse révèle quelles adresses sont enregistrées.
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("identifiants invalides")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("identifiants invalides")
    if not user.is_active:
        raise AuthenticationError("compte désactivé")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    db.flush()
    return user


_DUMMY_HASH = hash_password("mot-de-passe-factice-pour-egaliser-le-temps")


def issue_token_pair(
    db: Session, user: User, *, user_agent: str | None = None, ip_address: str | None = None
) -> TokenPair:
    access, _, _ = create_token(subject=user.id, token_type="access")
    refresh, jti, expires_at = create_token(subject=user.id, token_type="refresh")
    db.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            token_hash=hash_opaque_token(refresh),
            expires_at=expires_at,
            user_agent=(user_agent or "")[:400] or None,
            ip_address=ip_address,
        )
    )
    db.flush()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[User, TokenPair]:
    """Échange un jeton de rafraîchissement contre une nouvelle paire.

    La rotation est stricte : l'ancien jeton est révoqué immédiatement. Un
    jeton déjà révoqué qu'on tente de rejouer indique un vol — on révoque
    alors toute la famille de sessions de l'utilisateur.
    """
    from app.core.security import TokenError

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise AuthenticationError("jeton de rafraîchissement invalide") from exc

    stored = db.execute(
        sa.select(RefreshToken).where(RefreshToken.jti == payload["jti"])
    ).scalar_one_or_none()
    if stored is None or stored.token_hash != hash_opaque_token(refresh_token):
        raise AuthenticationError("jeton de rafraîchissement invalide")
    if stored.revoked_at is not None:
        # Rejouer un jeton déjà consommé signale un vol : on ferme toutes
        # les sessions de l'utilisateur. La révocation est validée
        # explicitement, car la requête se termine ensuite par une erreur —
        # et le rollback de fin de requête annulerait justement la mesure
        # de sécurité qu'on vient de prendre.
        revoke_all_for_user(db, stored.user_id)
        db.commit()
        logger.warning("refresh_token_reuse_detected", user_id=str(stored.user_id))
        raise AuthenticationError("jeton de rafraîchissement révoqué")
    if stored.expires_at <= utcnow():
        raise AuthenticationError("jeton de rafraîchissement expiré")

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("compte indisponible")

    stored.revoked_at = utcnow()
    db.flush()
    return user, issue_token_pair(
        db, user, user_agent=stored.user_agent, ip_address=stored.ip_address
    )


def revoke_refresh_token(db: Session, refresh_token: str) -> None:
    from app.core.security import TokenError

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenError:
        return  # déconnexion idempotente
    stored = db.execute(
        sa.select(RefreshToken).where(RefreshToken.jti == payload["jti"])
    ).scalar_one_or_none()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = utcnow()
        db.flush()


def revoke_all_for_user(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        sa.update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.flush()


def create_password_reset(db: Session, *, email: str) -> tuple[User, str] | None:
    """Retourne `(utilisateur, jeton en clair)` ou None si l'adresse est inconnue.

    L'API ne doit pas répercuter ce None : la réponse est identique dans
    les deux cas pour ne pas transformer le formulaire en oracle d'existence
    de comptes.
    """
    user = db.execute(
        sa.select(User).where(User.email == normalize_email(email))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    token = generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_opaque_token(token),
            expires_at=utcnow() + timedelta(seconds=settings.password_reset_ttl_seconds),
        )
    )
    db.flush()
    return user, token


def reset_password(db: Session, *, token: str, new_password: str) -> User:
    validate_password(new_password)
    stored = db.execute(
        sa.select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_opaque_token(token)
        )
    ).scalar_one_or_none()
    if stored is None or stored.used_at is not None or stored.expires_at <= utcnow():
        raise AuthenticationError("jeton de réinitialisation invalide ou expiré")

    user = db.get(User, stored.user_id)
    if user is None:
        raise AuthenticationError("jeton de réinitialisation invalide ou expiré")

    user.password_hash = hash_password(new_password)
    stored.used_at = utcnow()
    # Un changement de mot de passe doit fermer les sessions ouvertes.
    revoke_all_for_user(db, user.id)
    db.flush()
    return user


def get_primary_workspace(db: Session, user: User) -> Workspace:
    workspace = db.execute(
        sa.select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if workspace is None:
        raise AuthenticationError("aucun espace de travail associé")
    return workspace
