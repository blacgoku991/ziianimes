"""Routes d'authentification."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.api.deps import Context, DbSession
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    SessionOut,
    SimpleMessage,
    TokenResponse,
)
from app.services import auth_service

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: DbSession,
    request: Request,
    user_agent: Annotated[str | None, Header()] = None,
) -> RegisterResponse:
    user, workspace = auth_service.register_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        workspace_name=payload.workspace_name,
    )
    tokens = auth_service.issue_token_pair(
        db, user, user_agent=user_agent, ip_address=_client_ip(request)
    )
    return RegisterResponse(
        user=user,  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        tokens=TokenResponse(**tokens.__dict__),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: DbSession,
    request: Request,
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenResponse:
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    tokens = auth_service.issue_token_pair(
        db, user, user_agent=user_agent, ip_address=_client_ip(request)
    )
    return TokenResponse(**tokens.__dict__)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    _, tokens = auth_service.rotate_refresh_token(db, payload.refresh_token)
    return TokenResponse(**tokens.__dict__)


@router.post("/logout", response_model=SimpleMessage)
def logout(payload: RefreshRequest, db: DbSession) -> SimpleMessage:
    auth_service.revoke_refresh_token(db, payload.refresh_token)
    return SimpleMessage(message="session fermée")


@router.post("/password-reset", response_model=SimpleMessage)
def request_password_reset(payload: PasswordResetRequest, db: DbSession) -> SimpleMessage:
    result = auth_service.create_password_reset(db, email=payload.email)
    if result is not None:
        user, token = result
        # Étape 1 : pas d'envoi d'e-mail. Le lien est journalisé en
        # développement uniquement ; en production, brancher ici le service
        # d'e-mail transactionnel et ne jamais journaliser le jeton.
        if not settings.is_production:
            logger.info(
                "password_reset_link",
                user_id=str(user.id),
                link=f"{settings.frontend_base_url}/reset-password?token={token}",
            )
    # Réponse identique que l'adresse existe ou non.
    return SimpleMessage(message="si un compte existe, un e-mail a été envoyé")


@router.post("/password-reset/confirm", response_model=SimpleMessage)
def confirm_password_reset(payload: PasswordResetConfirm, db: DbSession) -> SimpleMessage:
    auth_service.reset_password(db, token=payload.token, new_password=payload.new_password)
    return SimpleMessage(message="mot de passe mis à jour")


@router.get("/me", response_model=SessionOut)
def me(context: Context) -> SessionOut:
    return SessionOut(user=context.user, workspace=context.workspace)  # type: ignore[arg-type]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
