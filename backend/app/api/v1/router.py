"""Assemblage des routes v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import articles, auth, operations, photos, variants

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(articles.router)
api_router.include_router(photos.router)
api_router.include_router(variants.router)
api_router.include_router(operations.router)
