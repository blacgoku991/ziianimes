"""Application Celery.

Les workers d'imagerie et (plus tard) les workers Playwright tournent dans
des conteneurs distincts du backend applicatif : ils sont gourmands en CPU
et en mémoire, et un crash de navigateur ne doit pas emporter l'API.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(json_logs=settings.is_production)

celery_app = Celery(
    "ziia",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks.imaging", "app.workers.tasks.publishing"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    # Une tâche perdue vaut mieux qu'une tâche rejouée à l'aveugle sur une
    # action distante ; les tâches critiques portent leur propre idempotence.
    task_reject_on_worker_lost=False,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_time_limit=15 * 60,
    task_soft_time_limit=13 * 60,
    result_expires=60 * 60 * 24,
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "imaging.*": {"queue": "imaging"},
        "publish.*": {"queue": "publish"},
    },
    beat_schedule={
        # Fenêtre de survente : c'est cet intervalle qui borne le délai
        # pendant lequel un article vendu reste en ligne ailleurs.
        "sync-listings": {
            "task": "publish.sync_listings",
            "schedule": float(settings.sync_interval_seconds),
        },
        # Reprise des publications qui attendaient un compte libre.
        "drain-queue": {"task": "publish.drain_queue", "schedule": 120.0},
        # Relances et baisses de prix.
        "run-schedules": {"task": "publish.run_schedules", "schedule": 3600.0},
        # Contrôle quotidien du formulaire : alerte le jour où le DOM change.
        "health-check": {"task": "publish.health_check", "schedule": 24 * 3600.0},
        "sync-inbox": {"task": "publish.sync_inbox", "schedule": 900.0},
    },
)
