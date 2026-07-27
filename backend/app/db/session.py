"""Fabrique de moteur et de sessions SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def build_engine(url: str | None = None, **kwargs: object) -> Engine:
    url = url or settings.database_url
    options: dict[str, object] = {"echo": settings.db_echo, "future": True}
    if url.startswith("sqlite"):
        # SQLite : partage de connexion entre threads (TestClient) et
        # activation des clés étrangères, désactivées par défaut.
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    options.update(kwargs)
    engine = create_engine(url, **options)  # type: ignore[arg-type]
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, rollback sur erreur."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Contexte transactionnel pour les tâches Celery et les scripts."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
