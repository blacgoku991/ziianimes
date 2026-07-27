"""Point d'entrée FastAPI."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger

configure_logging(json_logs=settings.is_production)
logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ziia — préparation et publication d'annonces",
        version="0.1.0",
        description=(
            "Étape 1 : espaces de travail, articles, photos sources et "
            "variantes. Aucune publication automatique à ce stade."
        ),
        docs_url="/docs" if not settings.is_production else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, path=request.url.path, method=request.method
        )
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["système"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
