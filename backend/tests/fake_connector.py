"""Connecteur de remplacement pour les tests et la démonstration.

Permet de dérouler tout le moteur de publication — file, verrou par compte,
reprise idempotente, dépublication croisée, relances — sans toucher à une
plateforme réelle. Il enregistre ce qu'on lui demande, ce qui rend
vérifiable ce que le moteur envoie vraiment.
"""

from __future__ import annotations

from app.connectors.base import (
    ConnectorError,
    PublishRequest,
    PublishResult,
    PublishStep,
    StepOutcome,
)
from app.models.enums import Platform


class FakeConnector:
    platform = Platform.vinted
    supports_autopublish = True

    def __init__(self, *, fail_at: PublishStep | None = None, needs_reauth: bool = False) -> None:
        self.published: list[PublishRequest] = []
        self.unpublished: list[str] = []
        self.price_updates: list[tuple[str, int]] = []
        self.fail_at = fail_at
        self.needs_reauth = needs_reauth
        self.sold_ids: set[str] = set()
        self.counter = 0
        self.messages: list[dict] = []

    def publish(self, request: PublishRequest, credentials: dict) -> PublishResult:  # noqa: ARG002
        if self.needs_reauth:
            raise ConnectorError("session expirée", retryable=False, needs_reauth=True)

        checkpoint = dict(request.checkpoint or {})
        steps: list[StepOutcome] = []
        for step in (
            PublishStep.open_form,
            PublishStep.upload_photos,
            PublishStep.fill_title,
            PublishStep.select_category,
            PublishStep.set_price,
        ):
            if self.fail_at is step and not checkpoint.get(step.value):
                # L'échec conserve les étapes déjà franchies : c'est ce qui
                # permet à la reprise de ne pas réenvoyer les photos.
                raise ConnectorError(
                    f"échec simulé à {step.value}", retryable=True, checkpoint=checkpoint
                )
            checkpoint[step.value] = True
            steps.append(StepOutcome(step, ok=True))

        self.published.append(request)
        if request.draft_only:
            return PublishResult(
                ok=True,
                draft_ready=True,
                steps=steps,
                checkpoint=checkpoint,
                remote_url="https://exemple.test/brouillon",
            )

        self.counter += 1
        listing_id = f"listing-{self.counter}"
        return PublishResult(
            ok=True,
            draft_ready=False,
            remote_listing_id=listing_id,
            remote_url=f"https://exemple.test/items/{listing_id}",
            steps=steps,
            checkpoint=checkpoint,
        )

    def unpublish(self, remote_listing_id: str, credentials: dict) -> bool:  # noqa: ARG002
        self.unpublished.append(remote_listing_id)
        return True

    def update_price(self, remote_listing_id: str, price_cents: int, credentials: dict) -> bool:  # noqa: ARG002
        self.price_updates.append((remote_listing_id, price_cents))
        return True

    def fetch_status(self, remote_listing_id: str, credentials: dict) -> dict:  # noqa: ARG002
        sold = remote_listing_id in self.sold_ids
        return {
            "sold": sold,
            "views_count": 42,
            "sale_price_cents": 2500 if sold else None,
        }

    def health_check(self, credentials: dict) -> tuple[bool, str]:  # noqa: ARG002
        if self.needs_reauth:
            return False, "session expirée"
        return True, "connecteur de test opérationnel"

    def fetch_messages(self, credentials: dict, since: str | None = None) -> list[dict]:  # noqa: ARG002
        return self.messages
