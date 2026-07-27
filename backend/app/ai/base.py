"""Contrat des fournisseurs d'IA.

Le reste du code ne connaît que ce module. Deux raisons : pouvoir changer de
modèle sans toucher au métier, et pouvoir faire tourner toute la suite de
tests sans clé d'API ni appel réseau.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Usage:
    """Consommation d'un appel, pour la traçabilité de coût."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    def cost_micros(self, *, input_per_mtok: float, output_per_mtok: float) -> int:
        """Coût en millionièmes d'euro, arrondi à l'entier supérieur."""
        cost = (
            self.input_tokens * input_per_mtok + self.output_tokens * output_per_mtok
        ) / 1_000_000.0
        return int(round(cost * 1_000_000))


@dataclass
class VisionAnalysis:
    """Ce que l'analyse des photos permet de déduire d'un vêtement."""

    garment_type: str | None = None
    brand: str | None = None
    #: L'IA ne lit pas toujours l'étiquette : on distingue « deviné » de « lu ».
    brand_confidence: float = 0.0
    color: str | None = None
    secondary_color: str | None = None
    material: str | None = None
    fit: str | None = None
    pattern: str | None = None
    size_label: str | None = None
    condition: str | None = None
    #: Défauts visibles à mentionner dans l'annonce — un vendeur qui les tait
    #: se fait ouvrir un litige.
    defects: list[str] = field(default_factory=list)
    #: Présence de texte ou de logo : coupe le miroir horizontal, qui les
    #: inverserait.
    has_visible_logo_or_text: bool = False
    keywords: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def to_dict(self) -> dict:
        data = {key: value for key, value in self.__dict__.items() if key != "usage"}
        return data


@dataclass
class ListingCopy:
    """Un jeu de textes destiné à **une** publication."""

    title: str
    description: str
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"title": self.title, "description": self.description, "keywords": self.keywords}


@dataclass
class CopyBatch:
    variants: list[ListingCopy]
    usage: Usage = field(default_factory=Usage)


@dataclass
class ToneProfile:
    """Ton et longueur, paramétrables par niche."""

    key: str = "neutre"
    label: str = "Neutre"
    instructions: str = "Ton factuel et sobre, sans superlatif."
    max_description_chars: int = 900

    @classmethod
    def for_niche(cls, niche: str | None) -> ToneProfile:
        return TONE_PROFILES.get((niche or "").lower(), TONE_PROFILES["neutre"])


TONE_PROFILES: dict[str, ToneProfile] = {
    "neutre": ToneProfile(),
    "vintage": ToneProfile(
        key="vintage",
        label="Vintage",
        instructions=(
            "Ton chaleureux. Situer la pièce dans son époque quand c'est visible, "
            "mentionner la coupe et la matière. Pas de jargon de collectionneur."
        ),
        max_description_chars=1100,
    ),
    "streetwear": ToneProfile(
        key="streetwear",
        label="Streetwear",
        instructions=(
            "Ton direct et court. Modèle et coloris d'abord, coupe ensuite. "
            "Pas de phrases décoratives."
        ),
        max_description_chars=700,
    ),
    "sport": ToneProfile(
        key="sport",
        label="Sport",
        instructions=(
            "Ton factuel. Insister sur la matière technique, la respirabilité et "
            "l'état des impressions."
        ),
        max_description_chars=700,
    ),
    "grandes_tailles": ToneProfile(
        key="grandes_tailles",
        label="Grandes tailles",
        instructions=(
            "Ton rassurant. Donner les mesures à plat quand elles sont connues, "
            "préciser la coupe et le tombé."
        ),
        max_description_chars=1000,
    ),
}


class AiProvider(Protocol):
    """Fournisseur d'analyse visuelle et de rédaction."""

    name: str

    def analyse_photos(self, images: list[bytes], *, hint: str | None = None) -> VisionAnalysis: ...

    def write_listing(
        self,
        analysis: VisionAnalysis,
        *,
        tone: ToneProfile,
        variant_count: int,
        brand: str | None = None,
        size_label: str | None = None,
    ) -> CopyBatch: ...
