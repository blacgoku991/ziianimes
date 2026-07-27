"""Isolation multi-locataire.

Ces tests valent plus que les autres : une fuite entre espaces de travail
expose les photos, les coûts d'achat et les marges d'un revendeur à un
autre. Chaque ressource exposée par l'API est vérifiée depuis un compte
tiers.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import ApiUser


def test_article_of_another_workspace_is_not_readable(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    article = api_user.create_article(title="Sweat Nike gris")

    response = client.get(f"/api/v1/articles/{article['id']}", headers=other_api_user.headers)
    # 404 et non 403 : confirmer l'existence renseignerait déjà l'attaquant.
    assert response.status_code == 404


def test_article_listing_is_scoped(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    api_user.create_article(title="Veste Carhartt")
    other_api_user.create_article(title="Robe Sézane")

    mine = client.get("/api/v1/articles", headers=api_user.headers).json()
    theirs = client.get("/api/v1/articles", headers=other_api_user.headers).json()

    assert mine["total"] == 1 and theirs["total"] == 1
    assert mine["items"][0]["title"] == "Veste Carhartt"
    assert theirs["items"][0]["title"] == "Robe Sézane"


def test_cannot_modify_or_delete_another_workspace_article(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    article = api_user.create_article(title="Pull laine")

    patch = client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"title": "détourné"},
        headers=other_api_user.headers,
    )
    assert patch.status_code == 404

    delete = client.delete(f"/api/v1/articles/{article['id']}", headers=other_api_user.headers)
    assert delete.status_code == 404

    unchanged = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert unchanged["title"] == "Pull laine"


def test_cannot_upload_into_another_workspace_article(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    article = api_user.create_article(title="Chemise")
    from tests.conftest import make_image_bytes

    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files={"files": ("photo.jpg", make_image_bytes(), "image/jpeg")},
        headers=other_api_user.headers,
    )
    assert response.status_code == 404


def test_cannot_read_another_workspace_photo(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    article = api_user.create_article(title="Jean")
    photo = api_user.upload_photo(article["id"])

    assert (
        client.delete(f"/api/v1/photos/{photo['id']}", headers=other_api_user.headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/photos/{photo['id']}/variants", headers=other_api_user.headers).json()
        == []
    )


def test_media_token_is_bound_to_its_object(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    """Le jeton d'une photo ne donne pas accès à une autre photo."""
    mine = api_user.upload_photo(api_user.create_article(title="A")["id"])
    theirs = other_api_user.upload_photo(other_api_user.create_article(title="B")["id"])

    token = mine["url"].split("token=")[1]
    stolen = client.get(f"/api/v1/photos/{theirs['id']}/file?token={token}")
    assert stolen.status_code == 401


def test_media_endpoint_requires_a_token(client: TestClient, api_user: ApiUser) -> None:
    photo = api_user.upload_photo(api_user.create_article(title="C")["id"])
    assert client.get(f"/api/v1/photos/{photo['id']}/file").status_code == 422
    assert client.get(f"/api/v1/photos/{photo['id']}/file?token=faux").status_code == 401


def test_workspace_header_cannot_target_a_foreign_workspace(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    """`X-Workspace-Id` est vérifié contre l'appartenance réelle, pas cru sur parole."""
    headers = {**api_user.headers, "X-Workspace-Id": str(other_api_user.workspace_id)}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


def test_unknown_workspace_header_is_rejected(client: TestClient, api_user: ApiUser) -> None:
    headers = {**api_user.headers, "X-Workspace-Id": str(uuid.uuid4())}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_service_layer_scoping_helper(db) -> None:  # noqa: ANN001
    """La couche service refuse aussi l'accès croisé, hors de tout contrôleur."""
    import pytest

    from app.core.errors import NotFoundError
    from app.models.catalog import Article
    from app.models.identity import Workspace
    from app.services.scoping import get_scoped

    workspace = Workspace(name="Scoping", slug=f"scoping-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    db.flush()
    article = Article(workspace_id=workspace.id, sku="TEST01", title="X")
    db.add(article)
    db.flush()

    assert get_scoped(db, Article, article.id, workspace.id).id == article.id
    with pytest.raises(NotFoundError):
        get_scoped(db, Article, article.id, uuid.uuid4())
