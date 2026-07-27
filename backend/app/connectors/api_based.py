"""Connecteurs sur API officielle : eBay, Depop, Leboncoin.

Ces plateformes exposent une API : pas de navigateur, pas de sélecteur, pas
de fragilité DOM. Le squelette ci-dessous met en place l'authentification
OAuth, le rejeu et la conversion vers le contrat commun ; les points
d'appel restent à brancher sur les identifiants d'application obtenus
auprès de chaque plateforme, ce qui suppose un compte développeur validé.

Écrire ces connecteurs comme des `ApiConnector` plutôt qu'en copiant le
connecteur Vinted est délibéré : la fragilité de Vinted vient de l'absence
d'API, ce n'est pas une fatalité qu'il faut propager aux autres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.connectors.base import (
    ConnectorError,
    PublishRequest,
    PublishResult,
    PublishStep,
    StepOutcome,
)
from app.core.logging import get_logger
from app.models.enums import Platform

logger = get_logger(__name__)


@dataclass
class ApiEndpoints:
    base_url: str
    create_listing: str
    update_listing: str
    delete_listing: str
    get_listing: str
    messages: str
    me: str


class ApiConnector:
    """Base commune aux connecteurs sur API officielle."""

    platform: Platform
    endpoints: ApiEndpoints
    #: Une API officielle sait publier : pas de mode brouillon imposé.
    supports_autopublish = True

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout = timeout_seconds

    # -- Transport --------------------------------------------------------

    def _request(
        self, method: str, url: str, credentials: dict, *, json_body: dict | None = None
    ) -> dict:
        import httpx

        token = credentials.get("access_token")
        if not token:
            raise ConnectorError(
                "jeton OAuth absent : reconnectez ce compte",
                retryable=False,
                needs_reauth=True,
            )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            response = httpx.request(
                method, url, headers=headers, json=json_body, timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"appel réseau en échec : {exc}", retryable=True) from exc

        if response.status_code in (401, 403):
            raise ConnectorError(
                "autorisation refusée par la plateforme", retryable=False, needs_reauth=True
            )
        if response.status_code == 429:
            # Limitation de débit : réessayable, mais plus tard.
            raise ConnectorError("limite de débit atteinte", retryable=True)
        if response.status_code >= 500:
            raise ConnectorError(f"erreur plateforme {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ConnectorError(
                f"requête refusée ({response.status_code}) : {response.text[:200]}",
                retryable=False,
            )
        return response.json() if response.content else {}

    # -- Contrat ----------------------------------------------------------

    def build_payload(self, request: PublishRequest) -> dict[str, Any]:
        """Traduit la demande vers le format de la plateforme.

        Redéfinie par chaque plateforme — c'est le seul endroit qui diffère
        réellement d'une API à l'autre.
        """
        return {
            "title": request.title,
            "description": request.description,
            "price": {"value": request.price_cents / 100, "currency": request.currency},
            "category_id": request.category_external_id,
            "brand_id": request.brand_external_id,
            "size_id": request.size_external_id,
            "condition": request.condition,
            "images": request.image_paths,
        }

    def publish(self, request: PublishRequest, credentials: dict) -> PublishResult:
        checkpoint = dict(request.checkpoint or {})
        steps: list[StepOutcome] = []

        if request.draft_only:
            # Les API acceptent en général un statut brouillon ; à défaut,
            # on ne publie pas : mieux vaut ne rien faire que soumettre une
            # annonce que l'utilisateur pensait retenir.
            payload = {**self.build_payload(request), "status": "draft"}
        else:
            payload = self.build_payload(request)

        url = f"{self.endpoints.base_url}{self.endpoints.create_listing}"
        body = self._request("POST", url, credentials, json_body=payload)
        checkpoint[PublishStep.submit.value] = True
        steps.append(StepOutcome(PublishStep.submit, ok=True, detail="appel API accepté"))

        listing_id = str(body.get("id") or body.get("listing_id") or "") or None
        return PublishResult(
            ok=True,
            draft_ready=request.draft_only,
            remote_listing_id=listing_id,
            remote_url=body.get("url") or body.get("web_url"),
            steps=steps,
            checkpoint=checkpoint,
        )

    def unpublish(self, remote_listing_id: str, credentials: dict) -> bool:
        url = (
            f"{self.endpoints.base_url}{self.endpoints.delete_listing.format(id=remote_listing_id)}"
        )
        self._request("DELETE", url, credentials)
        return True

    def update_price(self, remote_listing_id: str, price_cents: int, credentials: dict) -> bool:
        url = (
            f"{self.endpoints.base_url}{self.endpoints.update_listing.format(id=remote_listing_id)}"
        )
        self._request("PATCH", url, credentials, json_body={"price": {"value": price_cents / 100}})
        return True

    def fetch_status(self, remote_listing_id: str, credentials: dict) -> dict:
        url = f"{self.endpoints.base_url}{self.endpoints.get_listing.format(id=remote_listing_id)}"
        body = self._request("GET", url, credentials)
        state = str(body.get("status") or body.get("state") or "").lower()
        return {
            "sold": state in ("sold", "ended", "completed"),
            "views_count": int(body.get("views") or body.get("view_count") or 0),
            "raw_status": state,
            "sale_price_cents": int(float(body.get("sale_price") or 0) * 100) or None,
        }

    def health_check(self, credentials: dict) -> tuple[bool, str]:
        try:
            body = self._request(
                "GET", f"{self.endpoints.base_url}{self.endpoints.me}", credentials
            )
        except ConnectorError as exc:
            return False, exc.message
        return True, f"connecté en tant que {body.get('username') or body.get('id') or 'inconnu'}"

    def fetch_messages(self, credentials: dict, since: str | None = None) -> list[dict]:
        url = f"{self.endpoints.base_url}{self.endpoints.messages}"
        if since:
            url = f"{url}?since={since}"
        body = self._request("GET", url, credentials)
        return list(body.get("threads") or body.get("conversations") or [])


class EbayConnector(ApiConnector):
    platform = Platform.ebay
    endpoints = ApiEndpoints(
        base_url="https://api.ebay.com",
        create_listing="/sell/inventory/v1/offer",
        update_listing="/sell/inventory/v1/offer/{id}",
        delete_listing="/sell/inventory/v1/offer/{id}",
        get_listing="/sell/inventory/v1/offer/{id}",
        messages="/post-order/v2/inquiry/search",
        me="/sell/account/v1/privilege",
    )


class DepopConnector(ApiConnector):
    platform = Platform.depop
    endpoints = ApiEndpoints(
        base_url="https://webapi.depop.com",
        create_listing="/api/v1/products",
        update_listing="/api/v1/products/{id}",
        delete_listing="/api/v1/products/{id}",
        get_listing="/api/v1/products/{id}",
        messages="/api/v1/conversations",
        me="/api/v1/me",
    )


class LeboncoinConnector(ApiConnector):
    platform = Platform.leboncoin
    endpoints = ApiEndpoints(
        base_url="https://api.leboncoin.fr",
        create_listing="/api/adfinder/v1/ads",
        update_listing="/api/adfinder/v1/ads/{id}",
        delete_listing="/api/adfinder/v1/ads/{id}",
        get_listing="/api/adfinder/v1/ads/{id}",
        messages="/api/mc/v1/conversations",
        me="/api/accounts/v1/me",
    )
