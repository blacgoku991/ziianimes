"""Tâches de rendu d'images."""

from __future__ import annotations

import uuid

from celery import shared_task

from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import variant_service

logger = get_logger(__name__)


@shared_task(
    name="imaging.render_variant",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=3,
)
def render_variant_task(self, workspace_id: str, variant_id: str) -> dict[str, object]:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """Rend une variante planifiée.

    La tâche est idempotente : `render_variant_row` sans `force` ne refait
    pas une variante déjà rendue, donc un rejeu après incident réseau ne
    produit ni doublon de fichier ni double facturation CPU.
    """
    with session_scope() as db:
        variant = variant_service.render_variant_row(
            db, workspace_id=uuid.UUID(workspace_id), variant_id=uuid.UUID(variant_id)
        )
        return {
            "variant_id": str(variant.id),
            "status": variant.status.value,
            "distance_to_source": variant.phash_distance_to_source,
        }
