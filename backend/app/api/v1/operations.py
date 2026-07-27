"""Routes des étapes 2 à 6."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status

from app.api.deps import Context, DbSession
from app.core.config import settings
from app.core.errors import ValidationError
from app.models.enums import ArticleStatus, Platform, PublicationStatus
from app.referential.importer import import_all_seeds
from app.schemas.operations import (
    AcceptNoticeRequest,
    AccountCreate,
    AccountOut,
    AnalyseRequest,
    AnalysisOut,
    CopyOut,
    CopyRequest,
    CredentialsRequest,
    MarkSoldRequest,
    MatchOut,
    MatchRequest,
    PreparePublicationRequest,
    PriceOut,
    PriceRequest,
    PublicationOut,
    QuickReplyCreate,
    QuickReplyOut,
    RememberChoiceRequest,
    ReplyRequest,
    ScheduleRequest,
    StockOut,
)
from app.services import (
    account_service,
    article_service,
    dashboard_service,
    enrichment_service,
    inbox_service,
    mapping_service,
    pricing_service,
    publication_service,
    relist_service,
    stock_service,
)

router = APIRouter(tags=["opérations"])


# ---------------------------------------------------------------------------
# Étape 2 — enrichissement
# ---------------------------------------------------------------------------


@router.post("/articles/{article_id}/analyse", response_model=AnalysisOut)
def analyse_article(
    article_id: uuid.UUID, payload: AnalyseRequest, db: DbSession, context: Context
) -> AnalysisOut:
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    analysis = enrichment_service.analyse_article(
        db,
        workspace_id=context.workspace_id,
        article=article,
        hint=payload.hint,
        overwrite=payload.overwrite,
    )
    return AnalysisOut(**analysis.to_dict())


@router.post("/articles/{article_id}/copy", response_model=CopyOut)
def generate_copy(
    article_id: uuid.UUID, payload: CopyRequest, db: DbSession, context: Context
) -> CopyOut:
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    variants = enrichment_service.generate_listing_copy(
        db,
        workspace_id=context.workspace_id,
        article=article,
        variant_count=payload.variant_count,
        niche=payload.niche,
    )
    return CopyOut(variants=variants)


# ---------------------------------------------------------------------------
# Étape 2 — référentiels et rapprochement
# ---------------------------------------------------------------------------


@router.post("/referentials/import", status_code=status.HTTP_202_ACCEPTED)
def import_referentials(db: DbSession, context: Context) -> dict:  # noqa: ARG001
    """Charge les référentiels livrés. Sûr à rejouer."""
    return import_all_seeds(db)


@router.get("/referentials/categories")
def list_categories(
    db: DbSession,
    context: Context,  # noqa: ARG001
    platform: Platform = Query(default=Platform.vinted),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=300),
) -> list[dict]:
    rows = mapping_service.search_categories(db, platform=platform, query=q, limit=limit)
    return [{"external_id": row.external_id, "name": row.name, "path": row.path} for row in rows]


@router.get("/referentials/brands")
def list_brands(
    db: DbSession,
    context: Context,  # noqa: ARG001
    platform: Platform = Query(default=Platform.vinted),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=300),
) -> list[dict]:
    rows = mapping_service.search_brands(db, platform=platform, query=q, limit=limit)
    return [{"external_id": row.external_id, "name": row.name} for row in rows]


@router.get("/referentials/sizes")
def list_sizes(
    db: DbSession,
    context: Context,  # noqa: ARG001
    category_external_id: str = Query(...),
    platform: Platform = Query(default=Platform.vinted),
) -> list[dict]:
    """Grille de tailles **de la catégorie** : « 38 » ne veut pas dire la même
    chose sur une robe et sur une paire de baskets."""
    rows = mapping_service.sizes_for_category(
        db, platform=platform, category_external_id=category_external_id
    )
    return [{"external_id": row.external_id, "name": row.name} for row in rows]


@router.post("/mapping/category", response_model=MatchOut)
def match_category(payload: MatchRequest, db: DbSession, context: Context) -> MatchOut:
    result = mapping_service.match_category(
        db,
        workspace_id=context.workspace_id,
        platform=payload.platform,
        label=payload.label,
        extra_context=payload.context,
    )
    return MatchOut(**result.as_dict())


@router.post("/mapping/brand", response_model=MatchOut)
def match_brand(payload: MatchRequest, db: DbSession, context: Context) -> MatchOut:
    result = mapping_service.match_brand(
        db, workspace_id=context.workspace_id, platform=payload.platform, label=payload.label
    )
    return MatchOut(**result.as_dict())


@router.post("/mapping/category/remember", response_model=MatchOut)
def remember_category(payload: RememberChoiceRequest, db: DbSession, context: Context) -> MatchOut:
    """Mémorise le choix de l'utilisateur : il ne sera plus jamais demandé."""
    mapping_service.remember_category_choice(
        db,
        workspace_id=context.workspace_id,
        platform=payload.platform,
        label=payload.label,
        category_external_id=payload.external_id,
    )
    result = mapping_service.match_category(
        db, workspace_id=context.workspace_id, platform=payload.platform, label=payload.label
    )
    return MatchOut(**result.as_dict())


@router.post("/mapping/brand/remember", response_model=MatchOut)
def remember_brand(payload: RememberChoiceRequest, db: DbSession, context: Context) -> MatchOut:
    mapping_service.remember_brand_choice(
        db,
        workspace_id=context.workspace_id,
        platform=payload.platform,
        label=payload.label,
        brand_external_id=payload.external_id,
    )
    result = mapping_service.match_brand(
        db, workspace_id=context.workspace_id, platform=payload.platform, label=payload.label
    )
    return MatchOut(**result.as_dict())


# ---------------------------------------------------------------------------
# Étape 2 — prix
# ---------------------------------------------------------------------------


@router.post("/articles/{article_id}/price", response_model=PriceOut)
def suggest_price(
    article_id: uuid.UUID, payload: PriceRequest, db: DbSession, context: Context
) -> PriceOut:
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    advice = pricing_service.suggest_price(
        db,
        workspace_id=context.workspace_id,
        article=article,
        platform=payload.platform,
        workspace_settings=context.workspace.settings,
    )
    return PriceOut(**advice.as_dict())


# ---------------------------------------------------------------------------
# Étape 3 — stock
# ---------------------------------------------------------------------------


@router.get("/stock", response_model=StockOut)
def stock_table(
    db: DbSession,
    context: Context,
    article_status: ArticleStatus | None = Query(default=None, alias="status"),
    platform: Platform | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    stale_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> StockOut:
    rows, total = stock_service.stock_table(
        db,
        workspace_id=context.workspace_id,
        workspace_settings=context.workspace.settings,
        status=article_status,
        platform=platform,
        search=search,
        stale_only=stale_only,
        limit=limit,
        offset=offset,
    )
    return StockOut(
        items=[row.as_dict() for row in rows],
        total=total,
        summary=stock_service.stock_summary(db, workspace_id=context.workspace_id),
    )


@router.get("/stock/stale")
def stale_listings(
    db: DbSession, context: Context, days: int | None = Query(default=None, ge=1, le=365)
) -> list[dict]:
    """Annonces dormantes et baisse de prix suggérée, plancher respecté."""
    suggestions = stock_service.stale_listings(
        db,
        workspace_id=context.workspace_id,
        workspace_settings=context.workspace.settings,
        days=days,
    )
    return [suggestion.as_dict() for suggestion in suggestions]


# ---------------------------------------------------------------------------
# Étape 4 — comptes marketplace
# ---------------------------------------------------------------------------


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: DbSession, context: Context) -> AccountOut:
    account = account_service.create_account(
        db,
        workspace_id=context.workspace_id,
        platform=payload.platform,
        label=payload.label,
        niche=payload.niche,
        external_username=payload.external_username,
    )
    return AccountOut.model_validate(account)


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: DbSession, context: Context) -> list[AccountOut]:
    return [
        AccountOut.model_validate(account)
        for account in account_service.list_accounts(db, workspace_id=context.workspace_id)
    ]


@router.get("/accounts/health")
def accounts_health(db: DbSession, context: Context) -> list[dict]:
    """Écran de santé : quels comptes sont actifs, lesquels à reconnecter."""
    return account_service.health_overview(db, workspace_id=context.workspace_id)


@router.put("/accounts/{account_id}/credentials", response_model=AccountOut)
def store_credentials(
    account_id: uuid.UUID, payload: CredentialsRequest, db: DbSession, context: Context
) -> AccountOut:
    """Enregistre les secrets d'un compte, chiffrés au repos.

    Ils ne ressortent jamais de l'API et ne sont jamais journalisés.
    """
    account = account_service.get_account(
        db, workspace_id=context.workspace_id, account_id=account_id
    )
    secrets = {
        key: value
        for key, value in payload.model_dump(exclude_none=True).items()
        if value not in (None, [], {})
    }
    if not secrets:
        raise ValidationError("aucun secret fourni")
    account_service.store_credentials(
        db, workspace_id=context.workspace_id, account=account, payload=secrets
    )
    return AccountOut.model_validate(account)


@router.delete(
    "/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
def delete_account(account_id: uuid.UUID, db: DbSession, context: Context) -> None:
    account_service.delete_account(db, workspace_id=context.workspace_id, account_id=account_id)


@router.post("/workspace/automation-notice")
def accept_automation_notice(payload: AcceptNoticeRequest, db: DbSession, context: Context) -> dict:
    """Acceptation de l'avertissement CGU.

    Tant qu'elle n'est pas donnée, toute publication est rétrogradée en
    mode brouillon.
    """
    context.workspace.automation_notice_accepted_at = (
        datetime.now(UTC) if payload.accepted else None
    )
    db.flush()
    return {
        "accepted": payload.accepted,
        "accepted_at": (
            context.workspace.automation_notice_accepted_at.isoformat()
            if context.workspace.automation_notice_accepted_at
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Étape 5 — publications
# ---------------------------------------------------------------------------


@router.post("/articles/{article_id}/publications", response_model=list[PublicationOut])
def prepare_publications(
    article_id: uuid.UUID,
    payload: PreparePublicationRequest,
    db: DbSession,
    context: Context,
) -> list[PublicationOut]:
    """Prépare la publication d'un article sur un ou plusieurs comptes.

    Ne publie pas : la mise en file est une décision distincte, ce qui
    permet de préparer un lot puis de le lâcher d'un coup.
    """
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    publications = []
    for account_id in payload.account_ids:
        account = account_service.get_account(
            db, workspace_id=context.workspace_id, account_id=account_id
        )
        publication = publication_service.prepare_publication(
            db,
            workspace=context.workspace,
            article=article,
            account=account,
            mode=payload.mode,
            price_cents=payload.price_cents,
        )
        if payload.enqueue:
            publication_service.enqueue(
                db, workspace_id=context.workspace_id, publication=publication
            )
        publications.append(publication)
    return [PublicationOut.model_validate(publication) for publication in publications]


@router.get("/publications", response_model=list[PublicationOut])
def list_publications(
    db: DbSession,
    context: Context,
    article_id: uuid.UUID | None = Query(default=None),
    publication_status: PublicationStatus | None = Query(default=None, alias="status"),
) -> list[PublicationOut]:
    rows = publication_service.list_publications(
        db,
        workspace_id=context.workspace_id,
        article_id=article_id,
        status=publication_status,
    )
    return [PublicationOut.model_validate(row) for row in rows]


@router.post("/publications/{publication_id}/enqueue", response_model=PublicationOut)
def enqueue_publication(
    publication_id: uuid.UUID, db: DbSession, context: Context
) -> PublicationOut:
    """Met une publication en file.

    Ce n'est pas instantané : un job = un article + un compte, une
    publication à la fois par compte, avec des délais entre les actions.
    Le statut renseigne sur l'avancement.
    """
    publication = publication_service.get_publication(
        db, workspace_id=context.workspace_id, publication_id=publication_id
    )
    publication_service.enqueue(db, workspace_id=context.workspace_id, publication=publication)

    if publication.status is PublicationStatus.queued and not settings.celery_task_always_eager:
        from app.workers.tasks.publishing import run_publication_task

        db.commit()
        run_publication_task.delay(str(context.workspace_id), str(publication.id))
    return PublicationOut.model_validate(publication)


@router.post("/publications/{publication_id}/sold", response_model=dict)
def mark_sold(
    publication_id: uuid.UUID, payload: MarkSoldRequest, db: DbSession, context: Context
) -> dict:
    """Enregistre une vente et dépublie les autres annonces de l'article."""
    publication = publication_service.get_publication(
        db, workspace_id=context.workspace_id, publication_id=publication_id
    )
    outcome = publication_service.mark_sold(
        db,
        workspace=context.workspace,
        publication=publication,
        sale_price_cents=payload.sale_price_cents,
        shipping_cents=payload.shipping_cents,
    )
    return outcome.as_dict()


@router.post("/publications/{publication_id}/returned", response_model=PublicationOut)
def mark_returned(publication_id: uuid.UUID, db: DbSession, context: Context) -> PublicationOut:
    publication = publication_service.get_publication(
        db, workspace_id=context.workspace_id, publication_id=publication_id
    )
    publication_service.mark_returned(db, publication=publication)
    return PublicationOut.model_validate(publication)


@router.get("/publications/{publication_id}/events")
def publication_events(publication_id: uuid.UUID, db: DbSession, context: Context) -> list[dict]:
    """Journal d'une publication : traçabilité de bout en bout."""
    import sqlalchemy as sa

    from app.models.marketplace import PublicationEvent

    publication_service.get_publication(
        db, workspace_id=context.workspace_id, publication_id=publication_id
    )
    rows = (
        db.execute(
            sa.select(PublicationEvent)
            .where(PublicationEvent.publication_id == publication_id)
            .order_by(PublicationEvent.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "event_type": row.event_type.value,
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/publications/{publication_id}/schedules")
def create_schedule(
    publication_id: uuid.UUID, payload: ScheduleRequest, db: DbSession, context: Context
) -> dict:
    """Programme une relance ou une baisse de prix par paliers."""
    publication = publication_service.get_publication(
        db, workspace_id=context.workspace_id, publication_id=publication_id
    )
    schedule = relist_service.create_schedule(
        db,
        workspace_id=context.workspace_id,
        publication=publication,
        kind=payload.kind,
        steps=payload.steps,
    )
    return {
        "id": str(schedule.id),
        "kind": schedule.kind,
        "steps": schedule.steps,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
    }


# ---------------------------------------------------------------------------
# Étape 6 — boîte de réception
# ---------------------------------------------------------------------------


@router.get("/inbox")
def inbox(
    db: DbSession,
    context: Context,
    account_id: uuid.UUID | None = Query(default=None),
    unread_only: bool = Query(default=False),
    with_offers_only: bool = Query(default=False),
) -> list[dict]:
    return inbox_service.list_threads(
        db,
        workspace_id=context.workspace_id,
        account_id=account_id,
        unread_only=unread_only,
        with_offers_only=with_offers_only,
    )


@router.get("/inbox/{thread_id}")
def thread_messages(thread_id: uuid.UUID, db: DbSession, context: Context) -> list[dict]:
    return inbox_service.thread_messages(db, workspace_id=context.workspace_id, thread_id=thread_id)


@router.post("/inbox/{thread_id}/reply")
def reply(thread_id: uuid.UUID, payload: ReplyRequest, db: DbSession, context: Context) -> dict:
    return inbox_service.queue_reply(
        db, workspace_id=context.workspace_id, thread_id=thread_id, body=payload.body
    )


@router.get("/quick-replies", response_model=list[QuickReplyOut])
def list_quick_replies(db: DbSession, context: Context) -> list[QuickReplyOut]:
    inbox_service.seed_quick_replies(db, workspace_id=context.workspace_id)
    return [
        QuickReplyOut.model_validate(row)
        for row in inbox_service.list_quick_replies(db, workspace_id=context.workspace_id)
    ]


@router.post("/quick-replies", response_model=QuickReplyOut, status_code=status.HTTP_201_CREATED)
def create_quick_reply(payload: QuickReplyCreate, db: DbSession, context: Context) -> QuickReplyOut:
    reply = inbox_service.create_quick_reply(
        db, workspace_id=context.workspace_id, label=payload.label, body=payload.body
    )
    return QuickReplyOut.model_validate(reply)


# ---------------------------------------------------------------------------
# Étape 6 — tableau de bord
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(db: DbSession, context: Context, days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Chiffres clés. Tous les montants sont **nets** de frais."""
    return {
        "overview": dashboard_service.overview(db, workspace_id=context.workspace_id, days=days),
        "by_account": dashboard_service.by_account(db, workspace_id=context.workspace_id),
        "top_brands": dashboard_service.top_brands(db, workspace_id=context.workspace_id),
        "top_categories": dashboard_service.top_categories(db, workspace_id=context.workspace_id),
        "timeline": dashboard_service.sales_timeline(db, workspace_id=context.workspace_id),
        "sync_interval_seconds": settings.sync_interval_seconds,
    }
