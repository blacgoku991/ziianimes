"""Routes articles."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import Context, DbSession
from app.api.serializers import serialize_article, serialize_article_detail
from app.models.enums import ArticleStatus
from app.schemas.catalog import (
    ArticleCreate,
    ArticleDetailOut,
    ArticleListOut,
    ArticleOut,
    ArticleUpdate,
)
from app.services import article_service

router = APIRouter(prefix="/articles", tags=["articles"])


@router.post("", response_model=ArticleDetailOut, status_code=status.HTTP_201_CREATED)
def create_article(payload: ArticleCreate, db: DbSession, context: Context) -> ArticleDetailOut:
    article = article_service.create_article(
        db, workspace_id=context.workspace_id, data=payload.model_dump(exclude_none=True)
    )
    return serialize_article_detail(article, context.workspace_id)


@router.get("", response_model=ArticleListOut)
def list_articles(
    db: DbSession,
    context: Context,
    status_filter: ArticleStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ArticleListOut:
    items, total = article_service.list_articles(
        db,
        workspace_id=context.workspace_id,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ArticleListOut(
        items=[serialize_article(article) for article in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{article_id}", response_model=ArticleDetailOut)
def get_article(article_id: uuid.UUID, db: DbSession, context: Context) -> ArticleDetailOut:
    article = article_service.get_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
    return serialize_article_detail(article, context.workspace_id)


@router.patch("/{article_id}", response_model=ArticleOut)
def update_article(
    article_id: uuid.UUID, payload: ArticleUpdate, db: DbSession, context: Context
) -> ArticleOut:
    article = article_service.update_article(
        db,
        workspace_id=context.workspace_id,
        article_id=article_id,
        data=payload.model_dump(exclude_unset=True),
    )
    return serialize_article(article)


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_article(article_id: uuid.UUID, db: DbSession, context: Context) -> None:
    article_service.soft_delete_article(
        db, workspace_id=context.workspace_id, article_id=article_id
    )
