"""Tests de l'API articles."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import ApiUser


def test_create_article_generates_a_sku(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Sweat Nike gris", brand="Nike")
    assert article["sku"]
    assert len(article["sku"]) == 6
    assert article["status"] == "draft"
    assert article["currency"] == "EUR"
    assert article["photos"] == []


def test_create_article_accepts_an_explicit_sku(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(sku="VINT-001", title="Blouson")
    assert article["sku"] == "VINT-001"


def test_duplicate_sku_is_rejected(client: TestClient, api_user: ApiUser) -> None:
    api_user.create_article(sku="DUP-1", title="A")
    response = client.post(
        "/api/v1/articles", json={"sku": "DUP-1", "title": "B"}, headers=api_user.headers
    )
    assert response.status_code == 409


def test_same_sku_allowed_in_two_workspaces(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    """La référence est unique par espace de travail, pas globalement."""
    api_user.create_article(sku="REF-1", title="A")
    other_api_user.create_article(sku="REF-1", title="B")


def test_article_carries_cost_and_margin(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(
        title="Doudoune", purchase_cost_cents=800, target_margin_pct=60.0, floor_price_cents=1500
    )
    assert article["purchase_cost_cents"] == 800
    assert article["target_margin_pct"] == 60.0
    assert article["floor_price_cents"] == 1500


def test_update_article(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Ancien titre")
    response = client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"title": "Nouveau titre", "brand": "Levi's", "status": "listed"},
        headers=api_user.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Nouveau titre"
    assert body["brand"] == "Levi's"
    assert body["status"] == "listed"


def test_marking_sold_sets_sold_at(client: TestClient, api_user: ApiUser, engine) -> None:  # noqa: ANN001
    import sqlalchemy as sa

    from app.models.catalog import Article

    article = api_user.create_article(title="Vendu")
    client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"status": "sold"},
        headers=api_user.headers,
    )
    with engine.connect() as connection:
        sold_at = connection.execute(
            sa.select(Article.sold_at).where(Article.id == uuid.UUID(article["id"]))
        ).scalar_one()
    assert sold_at is not None


def test_soft_delete_hides_article_but_keeps_the_row(
    client: TestClient, api_user: ApiUser, engine
) -> None:  # noqa: ANN001
    import sqlalchemy as sa

    from app.models.catalog import Article

    article = api_user.create_article(title="À supprimer")
    assert (
        client.delete(f"/api/v1/articles/{article['id']}", headers=api_user.headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).status_code == 404
    )
    assert client.get("/api/v1/articles", headers=api_user.headers).json()["total"] == 0

    # La ligne survit : une annonce distante peut encore devoir être dépubliée.
    with engine.connect() as connection:
        deleted_at = connection.execute(
            sa.select(Article.deleted_at).where(Article.id == uuid.UUID(article["id"]))
        ).scalar_one()
    assert deleted_at is not None


def test_search_and_filter(client: TestClient, api_user: ApiUser) -> None:
    api_user.create_article(title="Sweat Nike", brand="Nike")
    api_user.create_article(title="Jean Levis", brand="Levi's")
    listed = api_user.create_article(title="Veste vendue")
    client.patch(
        f"/api/v1/articles/{listed['id']}", json={"status": "sold"}, headers=api_user.headers
    )

    by_brand = client.get("/api/v1/articles?search=nike", headers=api_user.headers).json()
    assert by_brand["total"] == 1

    by_status = client.get("/api/v1/articles?status=sold", headers=api_user.headers).json()
    assert by_status["total"] == 1
    assert by_status["items"][0]["title"] == "Veste vendue"


def test_pagination(client: TestClient, api_user: ApiUser) -> None:
    for index in range(5):
        api_user.create_article(title=f"Article {index}")
    page = client.get("/api/v1/articles?limit=2&offset=2", headers=api_user.headers).json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["offset"] == 2


def test_unknown_article_returns_404(client: TestClient, api_user: ApiUser) -> None:
    response = client.get(f"/api/v1/articles/{uuid.uuid4()}", headers=api_user.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
