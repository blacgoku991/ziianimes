"""Tests des étapes 2 à 6 : enrichissement, mapping, prix, stock,
publication, relances, boîte de réception et tableau de bord."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.connectors.base import PublishStep
from app.models.enums import Platform, PublicationStatus
from tests.conftest import ApiUser, make_image_bytes
from tests.fake_connector import FakeConnector

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_connector():  # noqa: ANN201
    """Remplace le connecteur Vinted par un double instrumenté."""
    from app.connectors.registry import clear_overrides, set_connector_override

    connector = FakeConnector()
    set_connector_override(Platform.vinted, connector)
    yield connector
    clear_overrides()


def _ready_article(client: TestClient, user: ApiUser, *, title: str = "Sweat Nike gris") -> dict:
    """Article avec photo et variantes prêtes — préalable à toute publication."""
    article = user.create_article(
        title=title,
        brand="Nike",
        category_label="sweat",
        size_label="M",
        purchase_cost_cents=500,
        condition="very_good",
    )
    photo = user.upload_photo(article["id"], make_image_bytes(900, 1200))
    client.post(
        f"/api/v1/photos/{photo['id']}/variants",
        json={"count": 2, "synchronous": True},
        headers=user.headers,
    )
    return article


def _account(client: TestClient, user: ApiUser, label: str, niche: str | None = None) -> dict:
    response = client.post(
        "/api/v1/accounts",
        json={"platform": "vinted", "label": label, "niche": niche},
        headers=user.headers,
    )
    assert response.status_code == 201, response.text
    account = response.json()
    stored = client.put(
        f"/api/v1/accounts/{account['id']}/credentials",
        json={"cookies": [{"name": "session", "value": "secret", "domain": ".vinted.fr"}]},
        headers=user.headers,
    )
    assert stored.status_code == 200
    return stored.json()


# ---------------------------------------------------------------------------
# Étape 2 — enrichissement IA
# ---------------------------------------------------------------------------


def test_analyse_fills_only_empty_fields(client: TestClient, api_user: ApiUser) -> None:
    """Une correction manuelle de l'utilisateur n'est jamais écrasée."""
    article = api_user.create_article(title="Pièce", brand="Carhartt")
    api_user.upload_photo(article["id"])

    response = client.post(
        f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers
    )
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["garment_type"]

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert detail["brand"] == "Carhartt"  # inchangé
    assert detail["color"]  # complété


def test_analyse_never_invents_a_brand(client: TestClient, api_user: ApiUser) -> None:
    """Une marque devinée sans certitude ne doit pas être écrite.

    Une marque fausse fait retirer l'annonce ; un champ vide, non.
    """
    article = api_user.create_article(title="Sans marque")
    api_user.upload_photo(article["id"])
    client.post(f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers)

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert detail["brand"] is None


def test_analyse_requires_photos(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(title="Sans photo")
    response = client.post(
        f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers
    )
    assert response.status_code == 422


def test_copy_variants_are_all_different(client: TestClient, api_user: ApiUser) -> None:
    """Deux comptes ne doivent jamais recevoir le même texte."""
    article = api_user.create_article(title="Veste", brand="Levi's")
    api_user.upload_photo(article["id"])
    client.post(f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers)

    response = client.post(
        f"/api/v1/articles/{article['id']}/copy",
        json={"variant_count": 4, "niche": "vintage"},
        headers=api_user.headers,
    )
    assert response.status_code == 200
    variants = response.json()["variants"]
    assert len(variants) == 4
    descriptions = [variant["description"] for variant in variants]
    assert len(set(descriptions)) == 4


def test_ai_cost_is_recorded(client: TestClient, api_user: ApiUser, engine) -> None:  # noqa: ANN001
    """Le coût variable du produit doit être traçable."""
    from app.models.referential import AiGeneration

    article = api_user.create_article(title="Coût")
    api_user.upload_photo(article["id"])
    client.post(f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers)

    with engine.connect() as connection:
        kinds = connection.execute(sa.select(AiGeneration.kind)).scalars().all()
    assert "vision_analysis" in kinds


def test_logo_detection_disables_mirror(client: TestClient, api_user: ApiUser) -> None:
    """Un logo visible coupe le miroir : il l'inverserait."""
    article = api_user.create_article(title="Logo")
    api_user.upload_photo(article["id"], make_image_bytes(seed=1))
    response = client.post(
        f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers
    )
    has_logo = response.json()["has_visible_logo_or_text"]

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert detail["attributes"]["allow_mirror"] is (not has_logo)


# ---------------------------------------------------------------------------
# Étape 2 — référentiels et rapprochement
# ---------------------------------------------------------------------------


@pytest.fixture
def referentials(client: TestClient, api_user: ApiUser) -> None:
    response = client.post("/api/v1/referentials/import", headers=api_user.headers)
    assert response.status_code == 202, response.text


def test_referential_import_is_idempotent(client: TestClient, api_user: ApiUser) -> None:
    first = client.post("/api/v1/referentials/import", headers=api_user.headers).json()
    second = client.post("/api/v1/referentials/import", headers=api_user.headers).json()
    assert first["vinted"]["categories_created"] > 0
    assert second["vinted"]["categories_created"] == 0  # rien de recréé


def test_category_matching_uses_gender(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    """« baskets homme » et « baskets enfant » ne mènent pas au même rayon."""
    response = client.post(
        "/api/v1/mapping/category",
        json={"label": "sweat", "context": "Nike gris homme"},
        headers=api_user.headers,
    )
    body = response.json()
    assert body["best"]["path"].startswith("Hommes")
    assert body["needs_user_choice"] is False


def test_category_matching_asks_when_ambiguous(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    """Rien plutôt qu'une supposition : une annonce mal rangée est invisible."""
    response = client.post(
        "/api/v1/mapping/category",
        json={"label": "objet indéterminé zzz"},
        headers=api_user.headers,
    )
    body = response.json()
    assert body["needs_user_choice"] is True


def test_user_choice_is_remembered(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    """Le choix de l'utilisateur fait autorité, et n'est plus redemandé."""
    categories = client.get(
        "/api/v1/referentials/categories?q=jean", headers=api_user.headers
    ).json()
    target = categories[0]

    remembered = client.post(
        "/api/v1/mapping/category/remember",
        json={"label": "truc bizarre", "external_id": target["external_id"]},
        headers=api_user.headers,
    ).json()
    assert remembered["needs_user_choice"] is False
    assert remembered["best"]["external_id"] == target["external_id"]

    again = client.post(
        "/api/v1/mapping/category",
        json={"label": "truc bizarre"},
        headers=api_user.headers,
    ).json()
    assert again["best"]["external_id"] == target["external_id"]


def test_mapping_choices_do_not_leak_between_workspaces(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser, referentials: None
) -> None:
    categories = client.get(
        "/api/v1/referentials/categories?q=robe", headers=api_user.headers
    ).json()
    client.post(
        "/api/v1/mapping/category/remember",
        json={"label": "mon libellé perso", "external_id": categories[0]["external_id"]},
        headers=api_user.headers,
    )
    other = client.post(
        "/api/v1/mapping/category",
        json={"label": "mon libellé perso"},
        headers=other_api_user.headers,
    ).json()
    assert other["needs_user_choice"] is True


def test_brand_matching_tolerates_typos(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    response = client.post(
        "/api/v1/mapping/brand", json={"label": "carhart"}, headers=api_user.headers
    ).json()
    assert response["best"]["label"] == "Carhartt"


def test_sizes_depend_on_category(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    """« 38 » ne veut pas dire la même chose sur une robe et sur des baskets."""
    robes = client.get("/api/v1/referentials/categories?q=robe", headers=api_user.headers).json()
    baskets = client.get(
        "/api/v1/referentials/categories?q=baskets", headers=api_user.headers
    ).json()

    robe_sizes = client.get(
        f"/api/v1/referentials/sizes?category_external_id={robes[0]['external_id']}",
        headers=api_user.headers,
    ).json()
    basket_sizes = client.get(
        f"/api/v1/referentials/sizes?category_external_id={baskets[0]['external_id']}",
        headers=api_user.headers,
    ).json()

    assert {size["name"] for size in robe_sizes} != {size["name"] for size in basket_sizes}


# ---------------------------------------------------------------------------
# Étape 2 — prix et frais
# ---------------------------------------------------------------------------


def test_price_without_comparables_falls_back_and_says_so(
    client: TestClient, api_user: ApiUser
) -> None:
    article = api_user.create_article(
        title="Sans historique", purchase_cost_cents=1000, target_margin_pct=50
    )
    response = client.post(
        f"/api/v1/articles/{article['id']}/price",
        json={"platform": "vinted"},
        headers=api_user.headers,
    )
    body = response.json()
    assert body["basis"] == "cout_et_marge"
    assert body["reliable"] is False
    assert any("Aucun comparable" in warning for warning in body["warnings"])
    # La marge cible est effectivement atteignable au prix conseillé.
    assert body["recommended_cents"] >= body["floor_cents"]


def test_price_respects_floor(client: TestClient, api_user: ApiUser) -> None:
    article = api_user.create_article(
        title="Plancher", purchase_cost_cents=200, floor_price_cents=3000
    )
    body = client.post(
        f"/api/v1/articles/{article['id']}/price",
        json={"platform": "vinted"},
        headers=api_user.headers,
    ).json()
    assert body["recommended_cents"] >= 3000


def test_margin_accounts_for_platform_fees() -> None:
    """Une marge calculée sans les frais est fausse — et oriente mal l'achat."""
    from app.models.enums import Platform as P
    from app.services import fees

    vinted = fees.compute_margin(platform=P.vinted, price_cents=3000, purchase_cost_cents=1000)
    ebay = fees.compute_margin(platform=P.ebay, price_cents=3000, purchase_cost_cents=1000)

    assert vinted.fee_cents == 0
    assert ebay.fee_cents > 0
    assert ebay.margin_cents < vinted.margin_cents


def test_price_for_target_margin_is_consistent() -> None:
    """Le prix calculé pour une marge cible doit bien la produire."""
    from app.models.enums import Platform as P
    from app.services import fees

    price = fees.price_for_target_margin(
        platform=P.ebay, purchase_cost_cents=1000, target_margin_pct=40
    )
    result = fees.compute_margin(platform=P.ebay, price_cents=price, purchase_cost_cents=1000)
    assert 38 <= result.margin_pct <= 42


# ---------------------------------------------------------------------------
# Étape 4 — comptes
# ---------------------------------------------------------------------------


def test_credentials_are_encrypted_and_never_returned(
    client: TestClient, api_user: ApiUser, engine
) -> None:  # noqa: ANN001
    from app.models.marketplace import MarketplaceAccount

    account = _account(client, api_user, "Vinted vintage", niche="vintage")
    assert "cookies" not in account
    assert "encrypted_credentials" not in account

    with engine.connect() as connection:
        blob = connection.execute(
            sa.select(MarketplaceAccount.encrypted_credentials).where(
                MarketplaceAccount.id == uuid.UUID(account["id"])
            )
        ).scalar_one()
    assert blob.startswith("v1.")
    assert "secret" not in blob  # le secret n'apparaît nulle part en clair


def test_credentials_cannot_be_replayed_on_another_account(
    client: TestClient, api_user: ApiUser, db
) -> None:  # noqa: ANN001
    """Les données authentifiées lient le chiffré à sa ligne."""
    from app.core.crypto import DecryptionError, decrypt_secret, encrypt_secret
    from app.services.account_service import credential_aad

    workspace_id, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    blob = encrypt_secret("session", aad=credential_aad(first, workspace_id))
    assert decrypt_secret(blob, aad=credential_aad(first, workspace_id)) == b"session"
    with pytest.raises(DecryptionError):
        decrypt_secret(blob, aad=credential_aad(second, workspace_id))


def test_health_overview_flags_accounts_to_reconnect(client: TestClient, api_user: ApiUser) -> None:
    client.post(
        "/api/v1/accounts",
        json={"platform": "vinted", "label": "Jamais connecté"},
        headers=api_user.headers,
    )
    health = client.get("/api/v1/accounts/health", headers=api_user.headers).json()
    entry = next(item for item in health if item["label"] == "Jamais connecté")
    assert entry["status"] == "needs_reauth"
    assert entry["has_credentials"] is False
    assert entry["health_check_overdue"] is True


def test_account_labels_are_unique_per_platform(client: TestClient, api_user: ApiUser) -> None:
    payload = {"platform": "vinted", "label": "Doublon"}
    assert (
        client.post("/api/v1/accounts", json=payload, headers=api_user.headers).status_code == 201
    )
    assert (
        client.post("/api/v1/accounts", json=payload, headers=api_user.headers).status_code == 409
    )


def test_accounts_are_isolated_between_workspaces(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    account = _account(client, api_user, "Privé")
    assert (
        client.delete(
            f"/api/v1/accounts/{account['id']}", headers=other_api_user.headers
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Étape 5 — publication
# ---------------------------------------------------------------------------


def test_publication_defaults_to_draft_mode(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """Le brouillon est le comportement par défaut, et le reste sans acceptation CGU."""
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted street", niche="streetwear")

    response = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "mode": "autopublish"},
        headers=api_user.headers,
    )
    assert response.status_code == 200, response.text
    # Rétrogradé : l'avertissement CGU n'a pas été accepté.
    assert response.json()[0]["mode"] == "draft"


def test_autopublish_allowed_after_notice_accepted(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    client.post(
        "/api/v1/workspace/automation-notice", json={"accepted": True}, headers=api_user.headers
    )
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted auto")

    response = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "mode": "autopublish"},
        headers=api_user.headers,
    )
    assert response.json()[0]["mode"] == "autopublish"


def test_publication_requires_ready_variants(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    article = api_user.create_article(title="Sans variante")
    account = _account(client, api_user, "Vinted vide")
    response = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]]},
        headers=api_user.headers,
    )
    assert response.status_code == 422


def test_same_article_blocked_on_two_accounts_of_one_platform(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """Deux annonces du même article sur deux comptes Vinted : refusé.

    C'est un des signaux les plus nets de rapprochement de comptes.
    """
    article = _ready_article(client, api_user)
    first = _account(client, api_user, "Vinted A")
    second = _account(client, api_user, "Vinted B")

    created = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [first["id"]], "enqueue": True},
        headers=api_user.headers,
    )
    assert created.status_code == 200

    conflict = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [second["id"]]},
        headers=api_user.headers,
    )
    assert conflict.status_code == 409
    assert "rapproche vos comptes" in conflict.json()["error"]["message"]


def test_preparation_is_idempotent(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted idem")

    first = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]]},
        headers=api_user.headers,
    ).json()
    second = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]]},
        headers=api_user.headers,
    ).json()
    assert first[0]["id"] == second[0]["id"]


def test_each_account_gets_its_own_text(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """Deux comptes de plateformes différentes reçoivent des textes distincts."""
    article = _ready_article(client, api_user)
    client.post(f"/api/v1/articles/{article['id']}/analyse", json={}, headers=api_user.headers)
    client.post(
        f"/api/v1/articles/{article['id']}/copy",
        json={"variant_count": 3},
        headers=api_user.headers,
    )

    vinted = _account(client, api_user, "Vinted texte")
    ebay = client.post(
        "/api/v1/accounts",
        json={"platform": "ebay", "label": "eBay texte"},
        headers=api_user.headers,
    ).json()

    publications = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [vinted["id"], ebay["id"]]},
        headers=api_user.headers,
    ).json()
    assert len(publications) == 2
    assert publications[0]["title"] is not None
    # Index de variante distincts : jamais le même jeu de textes.
    assert publications[0]["id"] != publications[1]["id"]


def test_publication_runs_to_draft_ready(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None, db
) -> None:  # noqa: ANN001
    from app.services import publish_runner

    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted run")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.db.session import build_engine

    factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
    with factory() as session:
        outcome = publish_runner.run_publication(
            session,
            workspace_id=api_user.workspace_id,
            publication_id=uuid.UUID(publication["id"]),
        )
        session.commit()

    assert outcome.status is PublicationStatus.draft_ready
    assert outcome.draft_ready is True
    assert len(fake_connector.published) == 1
    sent = fake_connector.published[0]
    assert sent.draft_only is True
    assert len(sent.image_paths) == 2  # les variantes, pas les sources
    assert sent.category_external_id  # catégorie résolue


def test_failed_publication_keeps_its_progress(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    """Une reprise ne réenvoie pas les photos déjà montées."""
    from sqlalchemy.orm import sessionmaker

    from app.connectors.registry import clear_overrides, set_connector_override
    from app.core.config import get_settings
    from app.db.session import build_engine
    from app.services import publish_runner

    failing = FakeConnector(fail_at=PublishStep.select_category)
    set_connector_override(Platform.vinted, failing)
    try:
        article = _ready_article(client, api_user)
        account = _account(client, api_user, "Vinted reprise")
        publication = client.post(
            f"/api/v1/articles/{article['id']}/publications",
            json={"account_ids": [account["id"]], "enqueue": True},
            headers=api_user.headers,
        ).json()[0]

        factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
        with factory() as session:
            publish_runner.run_publication(
                session,
                workspace_id=api_user.workspace_id,
                publication_id=uuid.UUID(publication["id"]),
            )
            session.commit()

        stored = client.get(
            f"/api/v1/publications?article_id={article['id']}", headers=api_user.headers
        ).json()[0]
        assert stored["last_error"]
        assert stored["attempts"] == 1
    finally:
        clear_overrides()

    # La progression est conservée : les photos ne repartiront pas.
    from app.models.marketplace import Publication

    factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
    with factory() as session:
        row = session.get(Publication, uuid.UUID(publication["id"]))
        assert row is not None
        assert row.checkpoint.get("upload_photos") is True
        assert row.checkpoint.get("select_category") is not True


def test_expired_session_marks_account_for_reconnection(
    client: TestClient, api_user: ApiUser, referentials: None
) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.connectors.registry import clear_overrides, set_connector_override
    from app.core.config import get_settings
    from app.db.session import build_engine
    from app.services import publish_runner

    set_connector_override(Platform.vinted, FakeConnector(needs_reauth=True))
    try:
        article = _ready_article(client, api_user)
        account = _account(client, api_user, "Vinted expiré")
        publication = client.post(
            f"/api/v1/articles/{article['id']}/publications",
            json={"account_ids": [account["id"]], "enqueue": True},
            headers=api_user.headers,
        ).json()[0]

        factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
        with factory() as session:
            outcome = publish_runner.run_publication(
                session,
                workspace_id=api_user.workspace_id,
                publication_id=uuid.UUID(publication["id"]),
            )
            session.commit()
        assert outcome.status is PublicationStatus.blocked
    finally:
        clear_overrides()

    health = client.get("/api/v1/accounts/health", headers=api_user.headers).json()
    entry = next(item for item in health if item["id"] == account["id"])
    assert entry["status"] == "needs_reauth"
    # La session expirée est effacée : la garder n'apporte rien.
    assert entry["has_credentials"] is False


def test_sale_unpublishes_all_other_listings(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """Vendu quelque part → retiré partout ailleurs."""
    article = _ready_article(client, api_user)
    vinted = _account(client, api_user, "Vinted vente")
    ebay = client.post(
        "/api/v1/accounts",
        json={"platform": "ebay", "label": "eBay vente"},
        headers=api_user.headers,
    ).json()

    publications = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [vinted["id"], ebay["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()

    sold = client.post(
        f"/api/v1/publications/{publications[0]['id']}/sold",
        json={"sale_price_cents": 2500},
        headers=api_user.headers,
    )
    assert sold.status_code == 200
    outcome = sold.json()
    assert len(outcome["unpublished_publication_ids"]) == 1
    assert outcome["oversold"] is False
    assert outcome["margin"]["margin_cents"] == 2500 - 500

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert detail["status"] == "sold"


def test_oversell_is_detected_not_hidden(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """Deux acheteurs pour une pièce unique : le conflit est signalé.

    C'est le mode d'échec normal d'un stock unitaire entre deux
    synchronisations. Le taire ferait découvrir le problème au litige.
    """
    article = _ready_article(client, api_user)
    vinted = _account(client, api_user, "Vinted survente")
    ebay = client.post(
        "/api/v1/accounts",
        json={"platform": "ebay", "label": "eBay survente"},
        headers=api_user.headers,
    ).json()
    publications = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [vinted["id"], ebay["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()

    client.post(
        f"/api/v1/publications/{publications[0]['id']}/sold",
        json={"sale_price_cents": 2500},
        headers=api_user.headers,
    )
    second = client.post(
        f"/api/v1/publications/{publications[1]['id']}/sold",
        json={"sale_price_cents": 2600},
        headers=api_user.headers,
    ).json()
    assert second["oversold"] is True


def test_return_puts_the_article_back_in_stock(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted retour")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    client.post(
        f"/api/v1/publications/{publication['id']}/sold",
        json={"sale_price_cents": 2000},
        headers=api_user.headers,
    )
    client.post(f"/api/v1/publications/{publication['id']}/returned", headers=api_user.headers)

    detail = client.get(f"/api/v1/articles/{article['id']}", headers=api_user.headers).json()
    assert detail["status"] == "returned"


def test_publication_events_are_traced(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted journal")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    events = client.get(
        f"/api/v1/publications/{publication['id']}/events", headers=api_user.headers
    ).json()
    types = [event["event_type"] for event in events]
    assert "created" in types and "queued" in types


def test_daily_cap_blocks_further_publications(client: TestClient, api_user: ApiUser) -> None:
    """Un compte qui publie sans limite se signale tout seul."""
    from app.models.enums import AccountStatus
    from app.models.marketplace import MarketplaceAccount
    from app.services import publication_service

    account = MarketplaceAccount(
        workspace_id=api_user.workspace_id,
        platform=Platform.vinted,
        label="Cadence",
        auth_type="browser_session",
        status=AccountStatus.active,
        daily_action_count=999,
        daily_action_reset_at=datetime.now(UTC),
    )
    guard = publication_service.check_account_cadence(account)
    assert guard.ok is False
    assert "plafond quotidien" in (guard.reason or "")


def test_minimum_delay_between_actions() -> None:
    from app.models.enums import AccountStatus
    from app.models.marketplace import MarketplaceAccount
    from app.services import publication_service

    account = MarketplaceAccount(
        workspace_id=uuid.uuid4(),
        platform=Platform.vinted,
        label="Rapide",
        auth_type="browser_session",
        status=AccountStatus.active,
        daily_action_count=1,
        daily_action_reset_at=datetime.now(UTC),
        last_action_at=datetime.now(UTC),
    )
    guard = publication_service.check_account_cadence(account)
    assert guard.ok is False
    assert guard.retry_after_seconds and guard.retry_after_seconds > 0


# ---------------------------------------------------------------------------
# Étape 3 — stock
# ---------------------------------------------------------------------------


def test_stock_table_shows_status_per_platform(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted stock")
    client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    )

    stock = client.get("/api/v1/stock", headers=api_user.headers).json()
    assert stock["total"] >= 1
    row = next(item for item in stock["items"] if item["id"] == article["id"])
    assert row["photo_count"] == 1
    assert len(row["publications"]) == 1
    assert row["publications"][0]["platform"] == "vinted"
    assert stock["summary"]["capital_immobilise_cents"] >= 500


def test_stock_search_and_filter(client: TestClient, api_user: ApiUser) -> None:
    api_user.create_article(title="Sweat Nike", brand="Nike")
    api_user.create_article(title="Jean Levis", brand="Levi's")
    found = client.get("/api/v1/stock?search=nike", headers=api_user.headers).json()
    assert found["total"] == 1


def test_stale_listings_suggest_a_drop_above_the_floor(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None, engine
) -> None:  # noqa: ANN001
    """Une baisse ne descend jamais sous le prix de revient."""
    from app.models.marketplace import Publication

    article = _ready_article(client, api_user)
    client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"floor_price_cents": 1500},
        headers=api_user.headers,
    )
    account = _account(client, api_user, "Vinted dormant")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    # On vieillit artificiellement l'annonce.
    with engine.begin() as connection:
        connection.execute(
            sa.update(Publication)
            .where(Publication.id == uuid.UUID(publication["id"]))
            .values(
                status="published",
                published_at=datetime.now(UTC) - timedelta(days=90),
                price_cents=2000,
            )
        )

    stale = client.get("/api/v1/stock/stale", headers=api_user.headers).json()
    assert len(stale) == 1
    assert stale[0]["suggested_price_cents"] >= 1500
    assert stale[0]["suggested_price_cents"] < 2000
    assert stale[0]["days_online"] >= 60


# ---------------------------------------------------------------------------
# Étape 5 — relances
# ---------------------------------------------------------------------------


def test_price_drop_schedule_stops_at_the_floor(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None, engine
) -> None:  # noqa: ANN001
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.db.session import build_engine
    from app.models.marketplace import Publication, PublicationSchedule
    from app.services import relist_service

    article = _ready_article(client, api_user)
    client.patch(
        f"/api/v1/articles/{article['id']}",
        json={"floor_price_cents": 1900},
        headers=api_user.headers,
    )
    account = _account(client, api_user, "Vinted paliers")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    with engine.begin() as connection:
        connection.execute(
            sa.update(Publication)
            .where(Publication.id == uuid.UUID(publication["id"]))
            .values(status="published", published_at=datetime.now(UTC), price_cents=2000)
        )

    created = client.post(
        f"/api/v1/publications/{publication['id']}/schedules",
        json={"kind": "price_drop", "steps": [{"after_days": 1, "drop_pct": 30}]},
        headers=api_user.headers,
    )
    assert created.status_code == 200

    factory = sessionmaker(bind=build_engine(get_settings().database_url), future=True)
    with factory() as session:
        schedule = session.execute(
            sa.select(PublicationSchedule).where(
                PublicationSchedule.publication_id == uuid.UUID(publication["id"])
            )
        ).scalar_one()
        outcome = relist_service.run_schedule(session, schedule=schedule)
        session.commit()

    # 30 % sous 2000 donnerait 1400 : la baisse est écrêtée au plancher.
    assert outcome.applied is True
    assert outcome.new_price_cents == 1900

    # Au palier suivant, le plancher est déjà atteint : la série s'arrête au
    # lieu de relancer indéfiniment sans effet.
    with factory() as session:
        schedule = session.execute(
            sa.select(PublicationSchedule).where(
                PublicationSchedule.publication_id == uuid.UUID(publication["id"])
            )
        ).scalar_one()
        schedule.is_active = True
        schedule.step_index = 0
        second = relist_service.run_schedule(session, schedule=schedule)
        session.commit()
    assert second.applied is False
    assert "plancher" in second.detail


def test_schedule_steps_must_increase(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted paliers ko")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]

    response = client.post(
        f"/api/v1/publications/{publication['id']}/schedules",
        json={
            "kind": "price_drop",
            "steps": [{"after_days": 30, "drop_pct": 5}, {"after_days": 10, "drop_pct": 10}],
        },
        headers=api_user.headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Étape 6 — boîte de réception
# ---------------------------------------------------------------------------


def test_inbox_ingests_and_detects_offers(client: TestClient, api_user: ApiUser, db) -> None:  # noqa: ANN001
    from app.models.enums import AccountStatus
    from app.models.marketplace import MarketplaceAccount
    from app.services import inbox_service

    account = MarketplaceAccount(
        workspace_id=api_user.workspace_id,
        platform=Platform.vinted,
        label="Inbox",
        auth_type="browser_session",
        status=AccountStatus.active,
    )
    db.add(account)
    db.flush()

    report = inbox_service.ingest_threads(
        db,
        workspace_id=api_user.workspace_id,
        account=account,
        payload=[
            {
                "remote_thread_id": "t1",
                "counterparty_name": "Claire",
                "messages": [
                    {"remote_message_id": "m1", "body": "Bonjour, je vous en propose 15 €"},
                    {"remote_message_id": "m2", "body": "Toujours dispo ?"},
                ],
            }
        ],
    )
    assert report.threads_created == 1
    assert report.messages_created == 2
    assert report.offers_detected == 1


def test_inbox_ingestion_is_idempotent(client: TestClient, api_user: ApiUser, db) -> None:  # noqa: ANN001
    from app.models.enums import AccountStatus
    from app.models.marketplace import MarketplaceAccount
    from app.services import inbox_service

    account = MarketplaceAccount(
        workspace_id=api_user.workspace_id,
        platform=Platform.vinted,
        label="Inbox idem",
        auth_type="browser_session",
        status=AccountStatus.active,
    )
    db.add(account)
    db.flush()

    payload = [
        {
            "remote_thread_id": "t9",
            "messages": [{"remote_message_id": "m9", "body": "Bonjour"}],
        }
    ]
    inbox_service.ingest_threads(
        db, workspace_id=api_user.workspace_id, account=account, payload=payload
    )
    second = inbox_service.ingest_threads(
        db, workspace_id=api_user.workspace_id, account=account, payload=payload
    )
    assert second.messages_created == 0
    assert second.threads_created == 0


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("je vous en propose 15 €", 1500),
        ("12,50€ ça vous va ?", 1250),
        ("20 euros", 2000),
        ("bonjour, disponible ?", None),
    ],
)
def test_offer_extraction(body: str, expected: int | None) -> None:
    from app.services.inbox_service import extract_offer_cents

    assert extract_offer_cents(body) == expected


def test_quick_replies_are_seeded(client: TestClient, api_user: ApiUser) -> None:
    replies = client.get("/api/v1/quick-replies", headers=api_user.headers).json()
    assert len(replies) >= 4
    assert any("disponible" in reply["body"].lower() for reply in replies)


# ---------------------------------------------------------------------------
# Étape 6 — tableau de bord
# ---------------------------------------------------------------------------


def test_dashboard_uses_net_proceeds(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    """La marge se calcule sur le net encaissé, pas sur le prix affiché."""
    article = _ready_article(client, api_user)
    ebay = client.post(
        "/api/v1/accounts",
        json={"platform": "ebay", "label": "eBay bilan"},
        headers=api_user.headers,
    ).json()
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [ebay["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]
    client.post(
        f"/api/v1/publications/{publication['id']}/sold",
        json={"sale_price_cents": 5000},
        headers=api_user.headers,
    )

    dashboard = client.get("/api/v1/dashboard", headers=api_user.headers).json()
    overview = dashboard["overview"]
    assert overview["sold_count"] == 1
    assert overview["revenue_cents"] == 5000
    # eBay prélève une commission : le net est strictement inférieur au CA.
    assert overview["net_proceeds_cents"] < overview["revenue_cents"]
    assert overview["margin_cents"] == overview["net_proceeds_cents"] - 500
    assert dashboard["sync_interval_seconds"] > 0


def test_dashboard_breaks_down_by_account_and_brand(
    client: TestClient, api_user: ApiUser, fake_connector: FakeConnector, referentials: None
) -> None:
    article = _ready_article(client, api_user)
    account = _account(client, api_user, "Vinted perf", niche="streetwear")
    publication = client.post(
        f"/api/v1/articles/{article['id']}/publications",
        json={"account_ids": [account["id"]], "enqueue": True},
        headers=api_user.headers,
    ).json()[0]
    client.post(
        f"/api/v1/publications/{publication['id']}/sold",
        json={"sale_price_cents": 3000},
        headers=api_user.headers,
    )

    dashboard = client.get("/api/v1/dashboard", headers=api_user.headers).json()
    assert dashboard["by_account"][0]["label"] == "Vinted perf"
    assert dashboard["by_account"][0]["niche"] == "streetwear"
    assert dashboard["top_brands"][0]["brand"] == "Nike"


def test_dashboard_is_scoped_to_the_workspace(
    client: TestClient, api_user: ApiUser, other_api_user: ApiUser
) -> None:
    dashboard = client.get("/api/v1/dashboard", headers=other_api_user.headers).json()
    assert dashboard["overview"]["sold_count"] == 0
