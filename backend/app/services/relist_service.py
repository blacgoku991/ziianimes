"""Relances : remontées et baisses de prix par paliers.

Deux contraintes tenues ici, dans cet ordre :

* **le plancher l'emporte toujours.** Une baisse programmée ne descend
  jamais sous le prix de revient de l'article : brader n'est pas une
  stratégie de rotation ;
* **la fréquence est plafonnée.** Remonter une annonce tous les jours est
  le meilleur moyen de se faire limiter. `relist_min_interval_days` borne
  la cadence, et le palier suivant ne s'applique qu'après son délai.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.catalog import Article
from app.models.enums import PublicationEventType, PublicationStatus
from app.models.identity import Workspace
from app.models.marketplace import MarketplaceAccount, Publication, PublicationSchedule
from app.services import fees, publication_service

logger = get_logger(__name__)

KIND_PRICE_DROP = "price_drop"
KIND_RELIST = "relist"


@dataclass
class ScheduleOutcome:
    publication_id: uuid.UUID
    action: str
    applied: bool
    detail: str
    old_price_cents: int | None = None
    new_price_cents: int | None = None

    def as_dict(self) -> dict:
        return {
            "publication_id": str(self.publication_id),
            "action": self.action,
            "applied": self.applied,
            "detail": self.detail,
            "old_price_cents": self.old_price_cents,
            "new_price_cents": self.new_price_cents,
        }


def create_schedule(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    publication: Publication,
    kind: str,
    steps: list[dict] | None = None,
) -> PublicationSchedule:
    if kind not in (KIND_PRICE_DROP, KIND_RELIST):
        raise ValidationError(f"type de relance inconnu : {kind}")

    steps = steps or (
        settings.default_price_drop_steps
        if kind == KIND_PRICE_DROP
        else [{"after_days": settings.relist_min_interval_days}]
    )
    _validate_steps(kind, steps)

    existing = db.execute(
        sa.select(PublicationSchedule).where(
            PublicationSchedule.publication_id == publication.id,
            PublicationSchedule.kind == kind,
        )
    ).scalar_one_or_none()
    reference = publication.published_at or datetime.now(UTC)
    first_delay = int(steps[0].get("after_days", settings.relist_min_interval_days))

    if existing is not None:
        existing.steps = steps
        existing.is_active = True
        existing.step_index = 0
        existing.next_run_at = reference + timedelta(days=first_delay)
        db.flush()
        return existing

    schedule = PublicationSchedule(
        workspace_id=workspace_id,
        publication_id=publication.id,
        kind=kind,
        steps=steps,
        step_index=0,
        next_run_at=reference + timedelta(days=first_delay),
        is_active=True,
    )
    db.add(schedule)
    db.flush()
    return schedule


def _validate_steps(kind: str, steps: list[dict]) -> None:
    if not steps:
        raise ValidationError("au moins un palier est nécessaire")
    previous_days = -1
    for step in steps:
        days = int(step.get("after_days", 0))
        if days <= previous_days:
            raise ValidationError("les paliers doivent être strictement croissants en jours")
        previous_days = days
        if kind == KIND_PRICE_DROP:
            drop = float(step.get("drop_pct", 0))
            if not 0 < drop <= 50:
                raise ValidationError("une baisse de palier doit être comprise entre 0 et 50 %")


def due_schedules(db: Session, *, limit: int = 200) -> list[PublicationSchedule]:
    now = datetime.now(UTC)
    return list(
        db.execute(
            sa.select(PublicationSchedule)
            .where(
                PublicationSchedule.is_active.is_(True),
                PublicationSchedule.next_run_at.is_not(None),
                PublicationSchedule.next_run_at <= now,
            )
            .order_by(PublicationSchedule.next_run_at)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def run_schedule(db: Session, *, schedule: PublicationSchedule) -> ScheduleOutcome:
    publication = db.get(Publication, schedule.publication_id)
    if publication is None:
        schedule.is_active = False
        db.flush()
        raise NotFoundError("publication introuvable")

    if publication.status is not PublicationStatus.published:
        # Vendue ou retirée : la relance n'a plus d'objet.
        schedule.is_active = False
        db.flush()
        return ScheduleOutcome(publication.id, schedule.kind, False, "publication plus en ligne")

    if schedule.kind == KIND_PRICE_DROP:
        outcome = _apply_price_drop(db, schedule=schedule, publication=publication)
    else:
        outcome = _apply_relist(db, publication=publication)

    _advance(schedule)
    db.flush()
    return outcome


def _apply_price_drop(
    db: Session, *, schedule: PublicationSchedule, publication: Publication
) -> ScheduleOutcome:
    steps = list(schedule.steps or [])
    if schedule.step_index >= len(steps):
        schedule.is_active = False
        return ScheduleOutcome(publication.id, KIND_PRICE_DROP, False, "paliers épuisés")

    step = steps[schedule.step_index]
    drop_pct = float(step.get("drop_pct", 0))
    current = publication.price_cents or 0
    if current <= 0:
        return ScheduleOutcome(publication.id, KIND_PRICE_DROP, False, "prix inconnu")

    article = db.get(Article, publication.article_id)
    workspace = db.get(Workspace, publication.workspace_id)
    account = db.get(MarketplaceAccount, publication.marketplace_account_id)
    floor = _floor_price(article, account, workspace)

    target = max(floor, int(round(current * (1 - drop_pct / 100))))
    if target >= current:
        # Le plancher est déjà atteint : on arrête la série plutôt que de
        # relancer indéfiniment sans effet.
        schedule.is_active = False
        return ScheduleOutcome(
            publication.id,
            KIND_PRICE_DROP,
            False,
            "plancher atteint, baisses interrompues",
            old_price_cents=current,
            new_price_cents=current,
        )

    publication.price_cents = target
    publication_service.record_event(
        db,
        publication,
        PublicationEventType.price_updated,
        {"from_cents": current, "to_cents": target, "drop_pct": drop_pct, "floor_cents": floor},
    )
    logger.info(
        "price_drop_applied",
        publication_id=str(publication.id),
        from_cents=current,
        to_cents=target,
    )
    return ScheduleOutcome(
        publication.id,
        KIND_PRICE_DROP,
        True,
        f"baisse de {drop_pct} %",
        old_price_cents=current,
        new_price_cents=target,
    )


def _apply_relist(db: Session, *, publication: Publication) -> ScheduleOutcome:
    now = datetime.now(UTC)
    if publication.last_relisted_at is not None:
        elapsed = now - publication.last_relisted_at
        if elapsed < timedelta(days=settings.relist_min_interval_days):
            # Plafond de fréquence : on ne remonte pas, et on reprogramme.
            return ScheduleOutcome(
                publication.id,
                KIND_RELIST,
                False,
                f"remontée trop récente ({elapsed.days} j)",
            )

    publication.last_relisted_at = now
    publication_service.record_event(
        db, publication, PublicationEventType.relisted, {"at": now.isoformat()}
    )
    return ScheduleOutcome(publication.id, KIND_RELIST, True, "remontée programmée")


def _advance(schedule: PublicationSchedule) -> None:
    steps = list(schedule.steps or [])
    schedule.last_run_at = datetime.now(UTC)
    schedule.step_index += 1
    if schedule.step_index >= len(steps):
        if schedule.kind == KIND_RELIST:
            # Une remontée se répète indéfiniment, à cadence plafonnée.
            schedule.step_index = len(steps) - 1
            schedule.next_run_at = datetime.now(UTC) + timedelta(
                days=settings.relist_min_interval_days
            )
        else:
            schedule.is_active = False
            schedule.next_run_at = None
        return

    reference = schedule.last_run_at
    previous_days = int(steps[schedule.step_index - 1].get("after_days", 0))
    next_days = int(steps[schedule.step_index].get("after_days", 0))
    gap = max(next_days - previous_days, settings.relist_min_interval_days)
    schedule.next_run_at = reference + timedelta(days=gap)


def _floor_price(
    article: Article | None, account: MarketplaceAccount | None, workspace: Workspace | None
) -> int:
    if article is None or account is None:
        return 100
    candidates = [100]
    if article.floor_price_cents:
        candidates.append(article.floor_price_cents)
    if article.target_margin_pct is not None:
        candidates.append(
            fees.price_for_target_margin(
                platform=account.platform,
                purchase_cost_cents=article.purchase_cost_cents,
                target_margin_pct=article.target_margin_pct,
                workspace_settings=workspace.settings if workspace else None,
            )
        )
    return max(candidates)
