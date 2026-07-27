"""Tests d'authentification et de gestion de session."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.conftest import ApiUser


def test_register_creates_user_workspace_and_trial(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Nouveau@Example.COM",
            "password": "un-mot-de-passe-long",
            "full_name": "Camille",
            "workspace_name": "Friperie Camille",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "nouveau@example.com"  # normalisé en minuscules
    assert body["workspace"]["name"] == "Friperie Camille"
    assert body["workspace"]["slug"] == "friperie-camille"
    assert body["workspace"]["subscription_status"] == "trialing"
    assert body["workspace"]["trial_ends_at"] is not None
    # L'avertissement CGU n'est pas accepté à l'inscription.
    assert body["workspace"]["automation_notice_accepted_at"] is None
    assert body["tokens"]["access_token"] and body["tokens"]["refresh_token"]


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    payload = {"email": "double@example.com", "password": "un-mot-de-passe-long"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    conflict = client.post("/api/v1/auth/register", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "court@example.com", "password": "court"}
    )
    assert response.status_code == 422


def test_workspace_slugs_are_unique(client: TestClient) -> None:
    first = client.post(
        "/api/v1/auth/register",
        json={
            "email": "a@example.com",
            "password": "mot-de-passe-long",
            "workspace_name": "Vintage",
        },
    ).json()
    second = client.post(
        "/api/v1/auth/register",
        json={
            "email": "b@example.com",
            "password": "mot-de-passe-long",
            "workspace_name": "Vintage",
        },
    ).json()
    assert first["workspace"]["slug"] != second["workspace"]["slug"]


def test_login_and_me(client: TestClient, api_user: ApiUser) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": api_user.email, "password": api_user.password}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == api_user.email


def test_login_rejects_wrong_password(client: TestClient, api_user: ApiUser) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": api_user.email, "password": "mauvais-mot-de-passe"}
    )
    assert response.status_code == 401


def test_login_does_not_reveal_unknown_accounts(client: TestClient, api_user: ApiUser) -> None:
    """Même code et même message pour un compte inconnu et un mauvais mot de passe."""
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "inconnu@example.com", "password": "peu-importe-long"}
    )
    wrong = client.post(
        "/api/v1/auth/login", json={"email": api_user.email, "password": "mauvais-mot-de-passe"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_protected_route_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nawak"}).status_code == 401
    )


def test_refresh_rotates_and_revokes_previous_token(client: TestClient, api_user: ApiUser) -> None:
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": api_user.refresh_token})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]
    assert new_refresh != api_user.refresh_token

    # Le jeton d'origine ne doit plus fonctionner.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": api_user.refresh_token})
    assert replay.status_code == 401

    # Et le rejeu détecté révoque toute la famille : le nouveau jeton aussi.
    after_reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after_reuse.status_code == 401


def test_logout_revokes_refresh_token(client: TestClient, api_user: ApiUser) -> None:
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": api_user.refresh_token}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": api_user.refresh_token}
        ).status_code
        == 401
    )


def test_password_reset_flow(client: TestClient, api_user: ApiUser, engine) -> None:  # noqa: ANN001
    from app.models.identity import PasswordResetToken, User

    response = client.post("/api/v1/auth/password-reset", json={"email": api_user.email})
    assert response.status_code == 200

    # Le jeton en clair n'existe pas en base : seule son empreinte est stockée.
    with engine.connect() as connection:
        stored = connection.execute(
            sa.select(PasswordResetToken.token_hash, PasswordResetToken.user_id)
        ).all()
    assert len(stored) == 1
    assert len(stored[0][0]) == 64

    # On rejoue le jeton en le recalculant comme le ferait le lien e-mail.
    from app.core.config import get_settings
    from app.core.security import generate_opaque_token, hash_opaque_token
    from app.db.session import build_engine

    # Génération d'un jeton connu pour la suite du test.
    known = generate_opaque_token()
    with build_engine(get_settings().database_url).begin() as connection:
        connection.execute(
            sa.update(PasswordResetToken).values(token_hash=hash_opaque_token(known))
        )

    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": known, "new_password": "nouveau-mot-de-passe"},
    )
    assert confirm.status_code == 200

    assert (
        client.post(
            "/api/v1/auth/login", json={"email": api_user.email, "password": api_user.password}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": api_user.email, "password": "nouveau-mot-de-passe"},
        ).status_code
        == 200
    )
    # Les sessions ouvertes sont fermées par le changement de mot de passe.
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": api_user.refresh_token}
        ).status_code
        == 401
    )
    _ = User  # silence l'analyseur : import utilisé pour la lisibilité du test


def test_password_reset_is_not_an_account_oracle(client: TestClient) -> None:
    known = client.post("/api/v1/auth/password-reset", json={"email": "fantome@example.com"})
    assert known.status_code == 200
    assert "message" in known.json()


def test_password_reset_token_cannot_be_reused(client: TestClient, api_user: ApiUser) -> None:
    from app.core.config import get_settings
    from app.core.security import generate_opaque_token, hash_opaque_token
    from app.db.session import build_engine
    from app.models.identity import PasswordResetToken

    client.post("/api/v1/auth/password-reset", json={"email": api_user.email})
    known = generate_opaque_token()
    with build_engine(get_settings().database_url).begin() as connection:
        connection.execute(
            sa.update(PasswordResetToken).values(token_hash=hash_opaque_token(known))
        )

    payload = {"token": known, "new_password": "encore-un-mot-de-passe"}
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 200
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 401


def test_media_token_cannot_be_used_as_credentials(client: TestClient, api_user: ApiUser) -> None:
    """Un jeton d'image ne doit pas ouvrir l'API."""
    from app.services.media import create_media_token

    token = create_media_token(
        kind="photo", object_id=api_user.user_id, workspace_id=api_user.workspace_id
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
