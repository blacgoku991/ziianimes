"""Sélection du fournisseur d'IA."""

from __future__ import annotations

import functools

from app.ai.base import (
    TONE_PROFILES,
    AiProvider,
    CopyBatch,
    ListingCopy,
    ToneProfile,
    Usage,
    VisionAnalysis,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "TONE_PROFILES",
    "AiProvider",
    "CopyBatch",
    "ListingCopy",
    "ToneProfile",
    "Usage",
    "VisionAnalysis",
    "get_ai_provider",
    "reset_ai_provider",
]


@functools.lru_cache(maxsize=1)
def get_ai_provider() -> AiProvider:
    backend = settings.ai_provider
    if backend == "stub":
        from app.ai.stub_provider import StubProvider

        return StubProvider()

    if backend == "anthropic" or (backend == "auto" and settings.anthropic_api_key):
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider()

    # `auto` sans clé : on bascule sur le bouchon en le disant clairement,
    # plutôt que de faire échouer chaque enrichissement avec une erreur
    # d'authentification incompréhensible côté utilisateur.
    from app.ai.stub_provider import StubProvider

    logger.warning("ai_provider_fallback_stub", reason="ANTHROPIC_API_KEY absente")
    return StubProvider()


def reset_ai_provider() -> None:
    get_ai_provider.cache_clear()
