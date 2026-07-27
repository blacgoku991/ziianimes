"""Étape 6 — tableau de bord.

Tous les montants passent par le produit **net** (`net_proceeds_cents`),
jamais par le prix affiché : commissions, frais d'encaissement et port à la
charge du vendeur sont déduits. Un tableau de bord qui additionne des prix
de vente donne un chiffre d'affaires juste et une marge fausse.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.catalog import Article
from app.models.enums import ArticleStatus, PublicationStatus
from app.models.marketplace import MarketplaceAccount, Publication
from app.models.referential import AiGeneration


def _sold_query(workspace_id: uuid.UUID, since: datetime):  # type: ignore[no-untyped-def]
    return (
        sa.select(Publication, Article, MarketplaceAccount)
        .join(Article, Article.id == Publication.article_id)
        .join(MarketplaceAccount, MarketplaceAccount.id == Publication.marketplace_account_id)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.status == PublicationStatus.sold,
            Publication.sold_at.is_not(None),
            Publication.sold_at >= since,
        )
    )


def overview(db: Session, *, workspace_id: uuid.UUID, days: int = 30) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(_sold_query(workspace_id, since)).all()

    revenue = sum(int(p.sale_price_cents or 0) for p, _, _ in rows)
    net = sum(int(p.net_proceeds_cents or p.sale_price_cents or 0) for p, _, _ in rows)
    cost = sum(int(a.purchase_cost_cents or 0) for _, a, _ in rows)
    margin = net - cost

    delays = [
        (p.sold_at - a.first_listed_at).days
        for p, a, _ in rows
        if p.sold_at and a.first_listed_at and p.sold_at >= a.first_listed_at
    ]

    live = db.execute(
        sa.select(sa.func.count())
        .select_from(Publication)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.status == PublicationStatus.published,
        )
    ).scalar_one()

    in_stock = db.execute(
        sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(Article.purchase_cost_cents), 0))
        .select_from(Article)
        .where(
            Article.workspace_id == workspace_id,
            Article.deleted_at.is_(None),
            Article.status.notin_([ArticleStatus.sold, ArticleStatus.withdrawn]),
        )
    ).one()

    ai_cost = db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(AiGeneration.cost_micros), 0)).where(
            AiGeneration.workspace_id == workspace_id, AiGeneration.created_at >= since
        )
    ).scalar_one()

    return {
        "period_days": days,
        "sold_count": len(rows),
        "revenue_cents": revenue,
        "net_proceeds_cents": net,
        "purchase_cost_cents": cost,
        "margin_cents": margin,
        "margin_pct": round(margin / net * 100, 2) if net else 0.0,
        "average_sale_cents": int(revenue / len(rows)) if rows else 0,
        "average_days_to_sale": round(sum(delays) / len(delays), 1) if delays else None,
        "live_publications": int(live),
        "articles_in_stock": int(in_stock[0]),
        "capital_immobilise_cents": int(in_stock[1]),
        #: Coût variable réel du produit sur la période, en millionièmes d'euro.
        "ai_cost_micros": int(ai_cost),
    }


def by_account(db: Session, *, workspace_id: uuid.UUID, days: int = 90) -> list[dict]:
    """Performance par compte, donc par niche."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(_sold_query(workspace_id, since)).all()

    grouped: dict[uuid.UUID, dict] = {}
    for publication, article, account in rows:
        bucket = grouped.setdefault(
            account.id,
            {
                "account_id": str(account.id),
                "label": account.label,
                "niche": account.niche,
                "platform": account.platform.value,
                "sold_count": 0,
                "revenue_cents": 0,
                "net_proceeds_cents": 0,
                "purchase_cost_cents": 0,
                "days_to_sale": [],
            },
        )
        bucket["sold_count"] += 1
        bucket["revenue_cents"] += int(publication.sale_price_cents or 0)
        bucket["net_proceeds_cents"] += int(
            publication.net_proceeds_cents or publication.sale_price_cents or 0
        )
        bucket["purchase_cost_cents"] += int(article.purchase_cost_cents or 0)
        if publication.sold_at and article.first_listed_at:
            bucket["days_to_sale"].append((publication.sold_at - article.first_listed_at).days)

    result = []
    for bucket in grouped.values():
        delays = bucket.pop("days_to_sale")
        margin = bucket["net_proceeds_cents"] - bucket["purchase_cost_cents"]
        bucket["margin_cents"] = margin
        bucket["margin_pct"] = (
            round(margin / bucket["net_proceeds_cents"] * 100, 2)
            if bucket["net_proceeds_cents"]
            else 0.0
        )
        bucket["average_days_to_sale"] = round(sum(delays) / len(delays), 1) if delays else None
        result.append(bucket)

    result.sort(key=lambda item: -item["margin_cents"])
    return result


def top_brands(
    db: Session, *, workspace_id: uuid.UUID, days: int = 180, limit: int = 10
) -> list[dict]:
    """Marques les plus rentables — pas les plus vendues.

    Le volume ne dit pas où gagner de l'argent : une marque qui part vite à
    petite marge occupe du temps sans rapporter.
    """
    return _top_by(
        db, workspace_id=workspace_id, days=days, limit=limit, field=Article.brand, key="brand"
    )


def top_categories(
    db: Session, *, workspace_id: uuid.UUID, days: int = 180, limit: int = 10
) -> list[dict]:
    return _top_by(
        db,
        workspace_id=workspace_id,
        days=days,
        limit=limit,
        field=Article.category_label,
        key="category",
    )


def _top_by(
    db: Session, *, workspace_id: uuid.UUID, days: int, limit: int, field, key: str
) -> list[dict]:  # type: ignore[no-untyped-def]
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        sa.select(
            field,
            sa.func.count(),
            sa.func.coalesce(
                sa.func.sum(
                    sa.func.coalesce(Publication.net_proceeds_cents, Publication.sale_price_cents)
                ),
                0,
            ),
            sa.func.coalesce(sa.func.sum(Article.purchase_cost_cents), 0),
        )
        .select_from(Publication)
        .join(Article, Article.id == Publication.article_id)
        .where(
            Publication.workspace_id == workspace_id,
            Publication.status == PublicationStatus.sold,
            Publication.sold_at >= since,
            field.is_not(None),
        )
        .group_by(field)
    ).all()

    items = []
    for label, count, net, cost in rows:
        margin = int(net) - int(cost)
        items.append(
            {
                key: label,
                "sold_count": int(count),
                "net_proceeds_cents": int(net),
                "purchase_cost_cents": int(cost),
                "margin_cents": margin,
                "margin_per_item_cents": int(margin / count) if count else 0,
            }
        )
    items.sort(key=lambda item: -item["margin_cents"])
    return items[:limit]


def sales_timeline(db: Session, *, workspace_id: uuid.UUID, days: int = 90) -> list[dict]:
    """Ventes agrégées par jour, pour la courbe."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        sa.select(
            sa.func.date(Publication.sold_at),
            sa.func.count(),
            sa.func.coalesce(
                sa.func.sum(
                    sa.func.coalesce(Publication.net_proceeds_cents, Publication.sale_price_cents)
                ),
                0,
            ),
        )
        .where(
            Publication.workspace_id == workspace_id,
            Publication.status == PublicationStatus.sold,
            Publication.sold_at >= since,
        )
        .group_by(sa.func.date(Publication.sold_at))
        .order_by(sa.func.date(Publication.sold_at))
    ).all()
    return [
        {"date": str(day), "sold_count": int(count), "net_proceeds_cents": int(net)}
        for day, count, net in rows
    ]
