"""Contrat des connecteurs marketplace.

Un connecteur transforme une `PublishRequest` en annonce distante. Le point
important est le **découpage en étapes nommées** : la publication n'est pas
un appel unique mais une séquence, et chaque étape franchie est enregistrée
dans `publications.checkpoint`.

C'est ce qui rend la reprise idempotente possible : si le job casse à
l'étape « catégorie », le rejeu ne recommence pas l'envoi des photos, qui
est l'étape longue et celle qui, rejouée, créerait des doublons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.models.enums import Platform


class PublishStep(StrEnum):
    """Étapes d'une publication, dans l'ordre d'exécution."""

    open_form = "open_form"
    upload_photos = "upload_photos"
    fill_title = "fill_title"
    fill_description = "fill_description"
    select_category = "select_category"
    select_brand = "select_brand"
    select_size = "select_size"
    select_condition = "select_condition"
    select_colour = "select_colour"
    select_material = "select_material"
    set_price = "set_price"
    review = "review"
    submit = "submit"


#: Ordre canonique. Une étape non gérée par une plateforme est simplement
#: absente de sa propre séquence.
DEFAULT_STEP_ORDER: tuple[PublishStep, ...] = tuple(PublishStep)


@dataclass
class PublishRequest:
    """Tout ce dont un connecteur a besoin, sans accès à la base."""

    publication_id: str
    title: str
    description: str
    price_cents: int
    currency: str
    #: Chemins locaux des fichiers image à envoyer, dans l'ordre.
    image_paths: list[str]
    category_external_id: str | None = None
    brand_external_id: str | None = None
    size_external_id: str | None = None
    condition: str | None = None
    colour: str | None = None
    material: str | None = None
    #: Mode brouillon : on remplit tout et on s'arrête avant la soumission.
    draft_only: bool = True
    #: Étapes déjà franchies lors d'une tentative précédente.
    checkpoint: dict = field(default_factory=dict)


@dataclass
class StepOutcome:
    step: PublishStep
    ok: bool
    detail: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class PublishResult:
    ok: bool
    #: Vrai quand le formulaire est rempli mais volontairement non soumis.
    draft_ready: bool = False
    remote_listing_id: str | None = None
    remote_url: str | None = None
    steps: list[StepOutcome] = field(default_factory=list)
    checkpoint: dict = field(default_factory=dict)
    error: str | None = None
    #: Vrai quand l'échec vient d'une session expirée : le compte doit
    #: repasser en « reconnexion nécessaire » plutôt qu'être réessayé.
    needs_reauth: bool = False

    def completed_steps(self) -> list[str]:
        return [outcome.step.value for outcome in self.steps if outcome.ok]


class ConnectorError(Exception):
    """Échec d'un connecteur, avec la distinction réessayable / définitif."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        needs_reauth: bool = False,
        checkpoint: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.needs_reauth = needs_reauth
        #: Étapes franchies avant l'échec. Sans elles, une reprise
        #: recommencerait l'envoi des photos — l'étape longue, et celle qui
        #: rejouée créerait des doublons.
        self.checkpoint = checkpoint or {}


class Connector(Protocol):
    """Interface commune aux connecteurs, API ou navigateur."""

    platform: Platform
    #: Le connecteur sait-il soumettre, ou s'arrête-t-il au brouillon ?
    supports_autopublish: bool

    def publish(self, request: PublishRequest, credentials: dict) -> PublishResult: ...

    def unpublish(self, remote_listing_id: str, credentials: dict) -> bool: ...

    def update_price(self, remote_listing_id: str, price_cents: int, credentials: dict) -> bool: ...

    def fetch_status(self, remote_listing_id: str, credentials: dict) -> dict: ...

    def health_check(self, credentials: dict) -> tuple[bool, str]: ...

    def fetch_messages(self, credentials: dict, since: str | None = None) -> list[dict]: ...
