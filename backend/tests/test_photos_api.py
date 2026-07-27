"""Tests de l'import de photos."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import ApiUser, make_image_bytes


def test_upload_photo_records_dimensions_and_hash(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Sweat")
    photo = api_user.upload_photo(article["id"], make_image_bytes(900, 1200))

    assert photo["width"] == 900
    assert photo["height"] == 1200
    assert photo["content_type"] == "image/jpeg"
    assert photo["status"] == "ready"
    assert photo["position"] == 0
    assert photo["url"].startswith("/api/v1/photos/")


def test_uploaded_source_is_stored_byte_for_byte(client: TestClient, api_user: ApiUser) -> None:
    """La source ne doit jamais être recompressée à l'import.

    C'est elle qui alimente toutes les variantes : la moindre passe
    d'encodage ici se propagerait à chaque publication.
    """
    from app.services import photo_service
    from app.storage import get_storage

    original = make_image_bytes(800, 1000)
    article = api_user.create_article(title="Original")
    photo = api_user.upload_photo(article["id"], original)

    stored = get_storage().get(
        f"workspaces/{api_user.workspace_id}/articles/{article['id']}/originals/{photo['id']}.jpg"
    )
    assert stored == original
    _ = photo_service


def test_upload_multiple_photos_assigns_positions(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Multi")
    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files=[
            ("files", ("a.jpg", make_image_bytes(seed=1), "image/jpeg")),
            ("files", ("b.jpg", make_image_bytes(seed=2), "image/jpeg")),
        ],
        headers=api_user.headers,
    )
    assert response.status_code == 201
    assert [photo["position"] for photo in response.json()] == [0, 1]


def test_uploading_the_same_file_twice_is_idempotent(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Doublon")
    data = make_image_bytes(seed=11)
    first = api_user.upload_photo(article["id"], data)
    second = api_user.upload_photo(article["id"], data)

    assert first["id"] == second["id"]
    photos = client.get(f"/api/v1/articles/{article['id']}/photos", headers=api_user.headers).json()
    assert len(photos) == 1


def test_rejects_unsupported_content_type(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="PDF")
    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files={"files": ("doc.pdf", b"%PDF-1.4 pas une image", "application/pdf")},
        headers=api_user.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_rejects_corrupted_image(client: TestClient, api_user: ApiUser) -> None:
    """Un fichier qui prétend être une image est refusé à l'import.

    Mieux vaut échouer devant l'utilisateur que dans le worker, une heure
    plus tard, quand plus personne ne regarde.
    """
    article = api_user.create_article(title="Corrompu")
    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files={"files": ("photo.jpg", b"\xff\xd8\xff\xe0 tronque", "image/jpeg")},
        headers=api_user.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_image"


def test_rejects_oversized_file(client: TestClient, api_user: ApiUser, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "image_max_upload_bytes", 1024)
    article = api_user.create_article(title="Trop gros")
    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files={"files": ("photo.jpg", make_image_bytes(), "image/jpeg")},
        headers=api_user.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["max_bytes"] == 1024


def test_photo_can_be_downloaded_with_its_signed_url(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Téléchargeable")
    data = make_image_bytes(400, 500)
    photo = api_user.upload_photo(article["id"], data)

    response = client.get(photo["url"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (400, 500)


def test_reorder_photos(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Ordre")
    first = api_user.upload_photo(article["id"], make_image_bytes(seed=1))
    second = api_user.upload_photo(article["id"], make_image_bytes(seed=2))

    response = client.post(
        f"/api/v1/articles/{article['id']}/photos/reorder",
        json={"photo_ids": [second["id"], first["id"]]},
        headers=api_user.headers,
    )
    assert response.status_code == 200
    ordered = response.json()
    assert ordered[0]["id"] == second["id"]
    assert ordered[1]["id"] == first["id"]


def test_reorder_rejects_incomplete_list(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Ordre partiel")
    first = api_user.upload_photo(article["id"], make_image_bytes(seed=1))
    api_user.upload_photo(article["id"], make_image_bytes(seed=2))

    response = client.post(
        f"/api/v1/articles/{article['id']}/photos/reorder",
        json={"photo_ids": [first["id"]]},
        headers=api_user.headers,
    )
    assert response.status_code == 422


def test_delete_photo_removes_row_and_file(client: TestClient, api_user: ApiUser) -> None:
    from app.storage import get_storage

    article = api_user.create_article(title="À nettoyer")
    photo = api_user.upload_photo(article["id"])
    key = f"workspaces/{api_user.workspace_id}/articles/{article['id']}/originals/{photo['id']}.jpg"
    assert get_storage().exists(key)

    assert (
        client.delete(f"/api/v1/photos/{photo['id']}", headers=api_user.headers).status_code == 204
    )
    assert not get_storage().exists(key)
    assert (
        client.get(f"/api/v1/articles/{article['id']}/photos", headers=api_user.headers).json()
        == []
    )


def test_photo_limit_per_article(client: TestClient, api_user: ApiUser, monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_photos_per_article", 2)
    article = api_user.create_article(title="Limite")
    api_user.upload_photo(article["id"], make_image_bytes(seed=1))
    api_user.upload_photo(article["id"], make_image_bytes(seed=2))

    response = client.post(
        f"/api/v1/articles/{article['id']}/photos",
        files={"files": ("c.jpg", make_image_bytes(seed=3), "image/jpeg")},
        headers=api_user.headers,
    )
    assert response.status_code == 422
