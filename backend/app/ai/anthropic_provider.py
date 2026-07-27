"""Fournisseur Claude (analyse visuelle + rédaction).

Deux principes de coût, qui découlent directement du volume visé
(50 à 200 articles par mois et par revendeur) :

* **une seule requête par article**, pas une par photo — les images partent
  ensemble dans le même message, ce qui divise le coût par le nombre de
  vues ;
* **une seule requête pour toutes les variantes de texte** — demander N
  variantes en un appel évite de repayer l'analyse à chaque fois, et permet
  au modèle de les rendre réellement différentes entre elles puisqu'il les
  voit toutes.
"""

from __future__ import annotations

import base64
import json
import time

from app.ai.base import (
    AiProvider,
    CopyBatch,
    ListingCopy,
    ToneProfile,
    Usage,
    VisionAnalysis,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Nombre maximal d'images envoyées par article : au-delà, le coût grimpe
#: sans que l'analyse s'améliore.
MAX_IMAGES_PER_CALL = 4

_VISION_SCHEMA = {
    "name": "analyse_vetement",
    "description": "Caractéristiques d'un vêtement d'occasion à partir de ses photos.",
    "input_schema": {
        "type": "object",
        "properties": {
            "garment_type": {"type": "string", "description": "Type : sweat, jean, robe…"},
            "brand": {"type": ["string", "null"], "description": "Marque, null si illisible"},
            "brand_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "color": {"type": ["string", "null"]},
            "secondary_color": {"type": ["string", "null"]},
            "material": {"type": ["string", "null"]},
            "fit": {"type": ["string", "null"], "description": "Coupe : oversize, ajustée…"},
            "pattern": {"type": ["string", "null"]},
            "size_label": {"type": ["string", "null"], "description": "Taille lue sur l'étiquette"},
            "condition": {
                "type": "string",
                "enum": [
                    "new_with_tags",
                    "new_without_tags",
                    "very_good",
                    "good",
                    "fair",
                ],
            },
            "defects": {"type": "array", "items": {"type": "string"}},
            "has_visible_logo_or_text": {"type": "boolean"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["garment_type", "condition", "has_visible_logo_or_text"],
    },
}

_COPY_SCHEMA = {
    "name": "redaction_annonces",
    "description": "Variantes de titre et description pour une même pièce.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "maxLength": 100},
                        "description": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "description"],
                },
            }
        },
        "required": ["variants"],
    },
}


class AnthropicProvider(AiProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.ai_model
        self._client = None

    def _get_client(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from anthropic import Anthropic

            if not self._api_key:
                raise RuntimeError("ANTHROPIC_API_KEY est requis pour le fournisseur anthropic")
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    # -- Analyse visuelle -------------------------------------------------

    def analyse_photos(self, images: list[bytes], *, hint: str | None = None) -> VisionAnalysis:
        if not images:
            raise ValueError("au moins une photo est nécessaire")

        content: list[dict] = []
        for image in images[:MAX_IMAGES_PER_CALL]:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        prompt = (
            "Analyse ce vêtement d'occasion destiné à la revente en ligne. "
            "N'invente jamais une marque : si l'étiquette n'est pas lisible, "
            "renvoie null et une confiance basse. Signale les défauts visibles "
            "(bouloches, taches, trous, décoloration) — les taire provoque des "
            "litiges. Indique si un logo ou du texte est visible sur le vêtement."
        )
        if hint:
            prompt += f"\n\nIndication du vendeur : {hint}"
        content.append({"type": "text", "text": prompt})

        started = time.perf_counter()
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=1500,
            tools=[_VISION_SCHEMA],
            tool_choice={"type": "tool", "name": "analyse_vetement"},
            messages=[{"role": "user", "content": content}],
        )
        payload = _first_tool_input(response)
        usage = Usage(
            model=self.model,
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return VisionAnalysis(
            garment_type=payload.get("garment_type"),
            brand=payload.get("brand"),
            brand_confidence=float(payload.get("brand_confidence") or 0.0),
            color=payload.get("color"),
            secondary_color=payload.get("secondary_color"),
            material=payload.get("material"),
            fit=payload.get("fit"),
            pattern=payload.get("pattern"),
            size_label=payload.get("size_label"),
            condition=payload.get("condition"),
            defects=list(payload.get("defects") or []),
            has_visible_logo_or_text=bool(payload.get("has_visible_logo_or_text")),
            keywords=list(payload.get("keywords") or []),
            usage=usage,
        )

    # -- Rédaction --------------------------------------------------------

    def write_listing(
        self,
        analysis: VisionAnalysis,
        *,
        tone: ToneProfile,
        variant_count: int,
        brand: str | None = None,
        size_label: str | None = None,
    ) -> CopyBatch:
        facts = {
            "type": analysis.garment_type,
            "marque": brand or analysis.brand,
            "taille": size_label or analysis.size_label,
            "couleur": analysis.color,
            "matiere": analysis.material,
            "coupe": analysis.fit,
            "motif": analysis.pattern,
            "etat": analysis.condition,
            "defauts": analysis.defects,
        }
        prompt = (
            f"Rédige {variant_count} variante(s) d'annonce pour cette pièce, "
            "destinées à des comptes différents de la même personne.\n\n"
            f"Faits vérifiés (ne rien ajouter au-delà) :\n"
            f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
            f"Ton attendu : {tone.instructions}\n"
            f"Description : {tone.max_description_chars} caractères maximum.\n"
            "Titre : marque, modèle si connu, type, taille et matière quand elles "
            "apportent quelque chose ; 100 caractères maximum.\n\n"
            "Contraintes impératives :\n"
            "- les variantes doivent être franchement différentes les unes des "
            "autres, dans la formulation comme dans la structure — elles seront "
            "publiées côte à côte et deux textes proches se repèrent ;\n"
            "- ne jamais affirmer une marque absente des faits ;\n"
            "- mentionner les défauts listés, sans dramatiser ;\n"
            "- pas d'emoji, pas de promesse de livraison ou de prix."
        )

        started = time.perf_counter()
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=4000,
            tools=[_COPY_SCHEMA],
            tool_choice={"type": "tool", "name": "redaction_annonces"},
            messages=[{"role": "user", "content": prompt}],
        )
        payload = _first_tool_input(response)
        variants = [
            ListingCopy(
                title=str(item.get("title", ""))[:255],
                description=str(item.get("description", "")),
                keywords=list(item.get("keywords") or []),
            )
            for item in payload.get("variants", [])
        ]
        usage = Usage(
            model=self.model,
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return CopyBatch(variants=variants, usage=usage)


def _first_tool_input(response: object) -> dict:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            return dict(getattr(block, "input", {}) or {})
    raise RuntimeError("réponse du modèle sans appel d'outil exploitable")
