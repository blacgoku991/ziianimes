"""Cycle de vie des articles (étape 1 : création, édition, suppression logique)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.catalog import Article
from app.models.enums import ArticleStatus

_SKU_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans I, O, 0, 1


def generate_sku(db: Session, workspace_id: uuid.UUID) -> str:
    """Référence courte, lisible à l'oral et unique dans l'espace de travail."""
    for _ in range(20):
        candidate = "".join(secrets.choice(_SKU_ALPHABET) for _ in range(6))
        exists = db.execute(
            sa.select(Article.id).where(
                Article.workspace_id == workspace_id, Article.sku == candidate
            )
        ).first()
        if exists is None:
            return candidate
    raise ConflictError("impossible de générer une référence article")


def create_article(db: Session, *, workspace_id: uuid.UUID, data: dict[str, Any]) -> Article:
    payload = dict(data)
    sku = payload.pop("sku", None) or generate_sku(db, workspace_id)
    article = Article(workspace_id=workspace_id, sku=sku, **payload)
    db.add(article)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("cette référence est déjà utilisée") from exc
    return article


def get_article(db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID) -> Article:
    article = db.execute(
        sa.select(Article).where(
            Article.id == article_id,
            Article.workspace_id == workspace_id,
            Article.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if article is None:
        raise NotFoundError("article introuvable")
    return article


def list_articles(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    status: ArticleStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Article], int]:
    conditions = [Article.workspace_id == workspace_id, Article.deleted_at.is_(None)]
    if status is not None:
        conditions.append(Article.status == status)
    if search:
        pattern = f"%{search.strip().lower()}%"
        conditions.append(
            sa.or_(
                sa.func.lower(Article.title).like(pattern),
                sa.func.lower(Article.brand).like(pattern),
                sa.func.lower(Article.sku).like(pattern),
            )
        )

    total = db.execute(
        sa.select(sa.func.count()).select_from(Article).where(*conditions)
    ).scalar_one()
    rows = (
        db.execute(
            sa.select(Article)
            .where(*conditions)
            .order_by(Article.created_at.desc())
            .limit(min(limit, 200))
            .offset(max(offset, 0))
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


def update_article(
    db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID, data: dict[str, Any]
) -> Article:
    article = get_article(db, workspace_id=workspace_id, article_id=article_id)
    for key, value in data.items():
        if value is not None or key in _NULLABLE_FIELDS:
            setattr(article, key, value)
    if article.status == ArticleStatus.sold and article.sold_at is None:
        article.sold_at = datetime.now(UTC)
    db.flush()
    return article


_NULLABLE_FIELDS = {"notes", "floor_price_cents", "target_margin_pct"}


def soft_delete_article(db: Session, *, workspace_id: uuid.UUID, article_id: uuid.UUID) -> None:
    """Suppression logique.

    Les publications distantes survivent à la suppression locale ; garder la
    ligne permet de savoir quoi dépublier plutôt que d'orpheliner une
    annonce en ligne.
    """
    article = get_article(db, workspace_id=workspace_id, article_id=article_id)
    article.deleted_at = datetime.now(UTC)
    db.flush()
