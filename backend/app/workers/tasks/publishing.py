"""Tâches de publication, synchronisation, relances et santé."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from celery import shared_task

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import AccountStatus, PublicationStatus
from app.models.marketplace import MarketplaceAccount, Publication
from app.services import account_service, publication_service, publish_runner, relist_service

logger = get_logger(__name__)


@shared_task(name="publish.run", bind=True, max_retries=0)
def run_publication_task(self, workspace_id: str, publication_id: str) -> dict:  # type: ignore[no-untyped-def]  # noqa: ARG001
    """Exécute une publication.

    Pas de `autoretry_for` : les reprises sont décidées par le métier, pas
    par Celery. Une erreur non réessayable (catégorie absente, marque
    inconnue) ne doit pas être rejouée trois fois contre la plateforme.
    """
    with session_scope() as db:
        outcome = publish_runner.run_publication(
            db, workspace_id=uuid.UUID(workspace_id), publication_id=uuid.UUID(publication_id)
        )
    if outcome.status is PublicationStatus.queued:
        # Compte occupé ou cadence non respectée : on repasse plus tard,
        # avec le délai aléatoire prévu.
        run_publication_task.apply_async(
            args=[workspace_id, publication_id],
            countdown=publication_service.next_delay_seconds(),
        )
    return outcome.as_dict()


@shared_task(name="publish.drain_queue")
def drain_queue_task(limit: int = 50) -> dict:
    """Reprend les publications en file dont le compte est de nouveau libre."""
    dispatched = 0
    with session_scope() as db:
        rows = (
            db.execute(
                sa.select(Publication)
                .where(Publication.status == PublicationStatus.queued)
                .order_by(Publication.created_at)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for publication in rows:
            run_publication_task.apply_async(
                args=[str(publication.workspace_id), str(publication.id)],
                countdown=publication_service.next_delay_seconds(),
            )
            dispatched += 1
    return {"dispatched": dispatched}


@shared_task(name="publish.sync_listings")
def sync_listings_task(limit: int = 100) -> dict:
    """Synchronise l'état des annonces en ligne.

    C'est ce qui déclenche la dépublication croisée à la vente. L'intervalle
    entre deux passages est la **fenêtre de survente** : deux acheteurs
    peuvent acheter la même pièce sur deux plateformes entre deux
    synchronisations.
    """
    horizon = datetime.now(UTC) - timedelta(seconds=settings.sync_interval_seconds)
    checked, sold = 0, 0
    with session_scope() as db:
        rows = (
            db.execute(
                sa.select(Publication)
                .where(
                    Publication.status == PublicationStatus.published,
                    Publication.remote_listing_id.is_not(None),
                    sa.or_(
                        Publication.last_synced_at.is_(None),
                        Publication.last_synced_at <= horizon,
                    ),
                )
                .order_by(Publication.last_synced_at.nullsfirst())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for publication in rows:
            try:
                result = publish_runner.sync_publication(
                    db, workspace_id=publication.workspace_id, publication_id=publication.id
                )
            except Exception as exc:
                logger.warning(
                    "sync_failed", publication_id=str(publication.id), error=str(exc)[:200]
                )
                continue
            checked += 1
            if result.get("sold"):
                sold += 1
                if result.get("oversold"):
                    logger.error(
                        "oversold_detected",
                        publication_id=str(publication.id),
                        detail="même article vendu deux fois — réconciliation nécessaire",
                    )
    return {"checked": checked, "sold": sold}


@shared_task(name="publish.run_schedules")
def run_schedules_task() -> dict:
    """Applique les relances et baisses de prix arrivées à échéance."""
    applied = 0
    with session_scope() as db:
        for schedule in relist_service.due_schedules(db):
            try:
                outcome = relist_service.run_schedule(db, schedule=schedule)
            except Exception as exc:
                logger.warning(
                    "schedule_failed", schedule_id=str(schedule.id), error=str(exc)[:200]
                )
                continue
            if outcome.applied:
                applied += 1
    return {"applied": applied}


@shared_task(name="publish.health_check")
def health_check_task() -> dict:
    """Contrôle quotidien des connexions et du formulaire.

    Le contrôle ouvre réellement le formulaire de publication et vérifie la
    présence de chaque cible : c'est ce qui permet d'être prévenu le jour où
    la plateforme change son DOM, au lieu de le découvrir trois semaines
    plus tard en constatant que rien ne part.
    """
    from app.connectors.registry import get_connector

    healthy, broken = 0, []
    with session_scope() as db:
        accounts = (
            db.execute(
                sa.select(MarketplaceAccount).where(
                    MarketplaceAccount.status != AccountStatus.disabled
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            credentials = account_service.load_credentials(
                account=account, workspace_id=account.workspace_id
            )
            if credentials is None:
                account_service.record_health_check(
                    db, account=account, healthy=False, detail="aucun identifiant enregistré"
                )
                broken.append({"account_id": str(account.id), "reason": "identifiants absents"})
                continue
            try:
                ok, detail = get_connector(account).health_check(credentials)
            except Exception as exc:
                ok, detail = False, str(exc)[:300]
            account_service.record_health_check(db, account=account, healthy=ok, detail=detail)
            if ok:
                healthy += 1
            else:
                broken.append({"account_id": str(account.id), "reason": detail})
                logger.error(
                    "account_health_failed", account_id=str(account.id), detail=detail[:200]
                )
    return {"healthy": healthy, "broken": broken}


@shared_task(name="publish.sync_inbox")
def sync_inbox_task(limit: int = 20) -> dict:
    """Rapatrie les messages de tous les comptes actifs."""
    from app.connectors.registry import get_connector
    from app.services import inbox_service

    total = 0
    with session_scope() as db:
        accounts = (
            db.execute(
                sa.select(MarketplaceAccount)
                .where(MarketplaceAccount.status == AccountStatus.active)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        for account in accounts:
            credentials = account_service.load_credentials(
                account=account, workspace_id=account.workspace_id
            )
            if credentials is None:
                continue
            try:
                payload = get_connector(account).fetch_messages(credentials)
            except Exception as exc:
                logger.warning(
                    "inbox_fetch_failed", account_id=str(account.id), error=str(exc)[:200]
                )
                continue
            report = inbox_service.ingest_threads(
                db, workspace_id=account.workspace_id, account=account, payload=payload
            )
            total += report.messages_created
    return {"messages_created": total}
