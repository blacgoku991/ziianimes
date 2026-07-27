"""Fixtures de test.

Par défaut la suite tourne sur SQLite en fichier temporaire : rapide, sans
service externe. En positionnant `TEST_DATABASE_URL` sur une base Postgres,
la même suite s'exécute sur le moteur de production, migrations comprises —
c'est ce que fait `make test-pg`.
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SEGMENTATION_BACKEND", "none")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")


@pytest.fixture(scope="session", autouse=True)
def _configure_settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    from app.core.config import get_settings

    storage_root = tmp_path_factory.mktemp("storage")
    db_path = tmp_path_factory.mktemp("db") / "test.sqlite"
    settings = get_settings()
    settings.environment = "test"
    settings.storage_backend = "local"
    settings.storage_local_root = str(storage_root)
    settings.segmentation_backend = "none"
    settings.celery_task_always_eager = True
    settings.database_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{db_path}"
    # Rendu plus rapide en test : on ne cherche pas la qualité d'impression.
    settings.image_min_long_edge = 512
    settings.image_max_long_edge = 1600

    from app.storage import reset_storage

    reset_storage()
    yield


@pytest.fixture(scope="session")
def engine(_configure_settings: None):  # noqa: ANN201
    from app.core.config import get_settings
    from app.db.session import build_engine
    from app.models import Base

    settings = get_settings()
    engine = build_engine(settings.database_url)
    if settings.database_url.startswith("postgresql"):
        # Sur Postgres on valide le chemin réel : migrations Alembic.
        from alembic.config import Config

        from alembic import command

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", settings.database_url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        command.upgrade(config, "head")
    else:
        Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:  # noqa: ANN001
    """Session isolée : chaque test s'exécute dans une transaction annulée."""
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(engine) -> Iterator[TestClient]:  # noqa: ANN001
    """Client HTTP branché sur une base réelle, nettoyée entre les tests."""
    from app.db.session import get_db
    from app.main import create_app
    from app.models import Base

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    def override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


# ---------------------------------------------------------------------------
# Fabriques d'images
# ---------------------------------------------------------------------------


def make_image_bytes(
    width: int = 900, height: int = 1200, *, fmt: str = "JPEG", seed: int = 7
) -> bytes:
    """Photo synthétique avec du contenu structuré.

    Un bruit uniforme donnerait des pHash instables : on génère un dégradé,
    une forme centrale et une texture, ce qui se rapproche du signal d'une
    vraie photo de vêtement.
    """
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:height, 0:width]
    background = (0.75 + 0.15 * (ys / height)).astype(np.float32)
    canvas = np.stack([background, background * 0.97, background * 0.93], axis=-1)

    # Sujet : rectangle arrondi sombre au centre, avec une texture.
    cy, cx = height // 2, width // 2
    half_h, half_w = int(height * 0.32), int(width * 0.28)
    subject = (np.abs(ys - cy) < half_h) & (np.abs(xs - cx) < half_w)
    texture = rng.normal(0.0, 0.03, size=(height, width)).astype(np.float32)
    canvas[subject] = np.stack(
        [
            0.22 + texture[subject],
            0.28 + texture[subject],
            0.45 + texture[subject],
        ],
        axis=-1,
    )
    # Bande contrastée : donne de l'énergie hautes fréquences au pHash.
    canvas[cy - 10 : cy + 10, cx - half_w : cx + half_w] = 0.95

    array = np.clip(canvas, 0, 1)
    image = Image.fromarray((array * 255).astype(np.uint8), mode="RGB")
    buffer = io.BytesIO()
    options = {"quality": 98} if fmt in ("JPEG", "WEBP") else {}
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


@pytest.fixture
def image_bytes() -> bytes:
    return make_image_bytes()


# ---------------------------------------------------------------------------
# Utilisateurs et espaces de travail
# ---------------------------------------------------------------------------


class ApiUser:
    """Utilisateur enregistré avec ses en-têtes d'authentification."""

    def __init__(self, client: TestClient, email: str, password: str) -> None:
        self.client = client
        self.email = email
        self.password = password
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "workspace_name": f"ws-{email}"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        self.user_id = uuid.UUID(body["user"]["id"])
        self.workspace_id = uuid.UUID(body["workspace"]["id"])
        self.access_token = body["tokens"]["access_token"]
        self.refresh_token = body["tokens"]["refresh_token"]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def create_article(self, **payload: object) -> dict:
        response = self.client.post("/api/v1/articles", json=payload, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()

    def upload_photo(self, article_id: str, data: bytes | None = None) -> dict:
        response = self.client.post(
            f"/api/v1/articles/{article_id}/photos",
            files={"files": ("photo.jpg", data or make_image_bytes(), "image/jpeg")},
            headers=self.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()[0]


@pytest.fixture
def api_user(client: TestClient) -> ApiUser:
    return ApiUser(client, "revendeur@example.com", "motdepasse-solide-1")


@pytest.fixture
def other_api_user(client: TestClient) -> ApiUser:
    return ApiUser(client, "autre@example.com", "motdepasse-solide-2")
