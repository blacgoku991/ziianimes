"""Tests du parcours de génération et de validation des variantes."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.imaging.phash import hamming_distance
from tests.conftest import ApiUser, make_image_bytes


def _generate(client: TestClient, user: ApiUser, photo_id: str, count: int = 3) -> dict:
    response = client.post(
        f"/api/v1/photos/{photo_id}/variants",
        json={"count": count, "synchronous": True},
        headers=user.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_generate_variants_end_to_end(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Sweat")
    photo = api_user.upload_photo(article["id"], make_image_bytes(1000, 1300))

    body = _generate(client, api_user, photo["id"], count=3)
    assert body["queued"] is False
    assert len(body["variants"]) == 3

    for variant in body["variants"]:
        assert variant["status"] == "ready"
        assert variant["url"]
        assert variant["byte_size"] > 0
        assert variant["render_count"] == 1
        assert variant["recipe"]["variant_index"] == variant["variant_index"]


def test_variants_are_perceptually_distant_from_the_source(
    client: TestClient, api_user: ApiUser
) -> None:
    """La promesse produit, vérifiée bout en bout."""
    article = api_user.create_article(title="Écart")
    photo = api_user.upload_photo(article["id"], make_image_bytes(1000, 1300))
    body = _generate(client, api_user, photo["id"], count=3)

    for variant in body["variants"]:
        assert variant["phash_distance_to_source"] is not None
        assert variant["phash_distance_to_source"] >= 10, variant


def test_variants_differ_from_each_other(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Sœurs")
    photo = api_user.upload_photo(article["id"], make_image_bytes(1000, 1300))
    body = _generate(client, api_user, photo["id"], count=3)

    hashes = [variant["phash"] for variant in body["variants"]]
    assert len(set(hashes)) == 3
    for left in range(len(hashes)):
        for right in range(left + 1, len(hashes)):
            assert hamming_distance(hashes[left], hashes[right]) >= 8


def test_variant_files_are_distinct_and_valid_jpeg(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Fichiers")
    photo = api_user.upload_photo(article["id"], make_image_bytes(1000, 1300))
    body = _generate(client, api_user, photo["id"], count=2)

    payloads = []
    for variant in body["variants"]:
        response = client.get(variant["url"])
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.format == "JPEG"
            assert not dict(image.getexif())
        payloads.append(response.content)

    assert payloads[0] != payloads[1]


def test_preview_exposes_source_and_variant_together(client: TestClient, api_user: ApiUser) -> None:
    """L'écran avant/après a tout ce qu'il lui faut en un seul appel."""
    article = api_user.create_article(title="Avant/après")
    photo = api_user.upload_photo(article["id"])
    _generate(client, api_user, photo["id"], count=2)

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert len(detail["photos"]) == 1
    stored = detail["photos"][0]
    assert stored["url"]  # « avant »
    assert len(stored["variants"]) == 2
    assert all(variant["url"] for variant in stored["variants"])  # « après »


def test_generation_is_idempotent_without_force(client: TestClient, api_user: ApiUser) -> None:
    """Relancer la génération ne refait pas le travail déjà accompli."""
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.db.session import build_engine
    from app.services import variant_service

    article = api_user.create_article(title="Idempotence")
    photo = api_user.upload_photo(article["id"])
    body = _generate(client, api_user, photo["id"], count=2)
    variant_id = body["variants"][0]["id"]

    factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
    with factory() as session:
        import uuid

        before = variant_service.get_variant(
            session, workspace_id=api_user.workspace_id, variant_id=uuid.UUID(variant_id)
        )
        assert before.render_count == 1
        again = variant_service.render_variant_row(
            session, workspace_id=api_user.workspace_id, variant_id=uuid.UUID(variant_id)
        )
        assert again.render_count == 1  # inchangé


def test_regenerate_produces_a_new_render(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Régénération")
    photo = api_user.upload_photo(article["id"])
    body = _generate(client, api_user, photo["id"], count=1)
    first = body["variants"][0]

    response = client.post(f"/api/v1/variants/{first['id']}/regenerate", headers=api_user.headers)
    assert response.status_code == 200
    second = response.json()

    assert second["id"] == first["id"]
    assert second["render_count"] == 2
    assert second["recipe"]["seed"] != first["recipe"]["seed"]
    assert second["status"] == "ready"


def test_regeneration_removes_the_previous_file(client: TestClient, api_user: ApiUser) -> None:
    from app.storage import get_storage

    article = api_user.create_article(title="Nettoyage")
    photo = api_user.upload_photo(article["id"])
    first = _generate(client, api_user, photo["id"], count=1)["variants"][0]
    old_key = (
        f"workspaces/{api_user.workspace_id}/articles/{article['id']}/variants/{first['id']}-r1.jpg"
    )
    assert get_storage().exists(old_key)

    client.post(f"/api/v1/variants/{first['id']}/regenerate", headers=api_user.headers)
    assert not get_storage().exists(old_key)


def test_accept_and_reject_a_variant(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Décision")
    photo = api_user.upload_photo(article["id"])
    variants = _generate(client, api_user, photo["id"], count=2)["variants"]

    accepted = client.post(
        f"/api/v1/variants/{variants[0]['id']}/decision",
        json={"accepted": True},
        headers=api_user.headers,
    ).json()
    assert accepted["status"] == "accepted"

    rejected = client.post(
        f"/api/v1/variants/{variants[1]['id']}/decision",
        json={"accepted": False},
        headers=api_user.headers,
    ).json()
    assert rejected["status"] == "rejected"


def test_deleting_a_photo_removes_its_variants(client: TestClient, api_user: ApiUser) -> None:
    from app.storage import get_storage

    article = api_user.create_article(title="Cascade")
    photo = api_user.upload_photo(article["id"])
    variants = _generate(client, api_user, photo["id"], count=2)["variants"]
    keys = [
        f"workspaces/{api_user.workspace_id}/articles/{article['id']}/variants/{v['id']}-r1.jpg"
        for v in variants
    ]
    assert all(get_storage().exists(key) for key in keys)

    client.delete(f"/api/v1/photos/{photo['id']}", headers=api_user.headers)

    assert not any(get_storage().exists(key) for key in keys)
    assert (
        client.get(f"/api/v1/articles/{article['id']}/variants", headers=api_user.headers).json()
        == []
    )


def test_variant_count_is_bounded(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Bornes")
    photo = api_user.upload_photo(article["id"])
    response = client.post(
        f"/api/v1/photos/{photo['id']}/variants",
        json={"count": 99, "synchronous": True},
        headers=api_user.headers,
    )
    assert response.status_code == 422


def test_asynchronous_mode_reports_queued_state(
    client: TestClient, api_user: ApiUser, monkeypatch
) -> None:  # noqa: ANN001
    """En mode file, l'API répond « en cours » sans bloquer la requête."""
    calls: list[tuple[str, str]] = []

    class _FakeTask:
        @staticmethod
        def delay(workspace_id: str, variant_id: str) -> None:
            calls.append((workspace_id, variant_id))

    import app.workers.tasks.imaging as imaging_tasks
    from app.core.config import get_settings

    monkeypatch.setattr(imaging_tasks, "render_variant_task", _FakeTask)
    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)

    article = api_user.create_article(title="File")
    photo = api_user.upload_photo(article["id"])
    response = client.post(
        f"/api/v1/photos/{photo['id']}/variants",
        json={"count": 2, "synchronous": False},
        headers=api_user.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is True
    assert all(variant["status"] == "pending" for variant in body["variants"])
    assert len(calls) == 2
