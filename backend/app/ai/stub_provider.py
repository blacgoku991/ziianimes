"""Fournisseur déterministe, sans réseau.

Sert à trois choses : faire tourner la suite de tests sans clé d'API,
permettre à un développeur de dérouler le produit entier hors ligne, et
servir de repli explicite quand aucune clé n'est configurée — plutôt que de
faire échouer l'enrichissement sans que personne comprenne pourquoi.

Les sorties sont dérivées des octets des images : deux articles différents
donnent des résultats différents, le même article donne toujours le même.
"""

from __future__ import annotations

import hashlib

from app.ai.base import CopyBatch, ListingCopy, ToneProfile, Usage, VisionAnalysis

_TYPES = ["sweat", "jean", "veste", "robe", "chemise", "pull", "t-shirt", "manteau"]
_COLORS = ["gris", "noir", "bleu marine", "beige", "kaki", "bordeaux", "écru"]
_MATERIALS = ["coton", "laine mélangée", "denim", "polyester recyclé", "lin"]
_FITS = ["coupe droite", "coupe oversize", "coupe ajustée", "coupe droite courte"]
_CONDITIONS = ["very_good", "good", "new_without_tags", "very_good", "good"]


class StubProvider:
    name = "stub"

    def __init__(self, model: str = "stub-1") -> None:
        self.model = model

    def _seed(self, images: list[bytes]) -> int:
        digest = hashlib.sha256(b"".join(images[:2]) or b"vide").digest()
        return int.from_bytes(digest[:6], "big")

    def analyse_photos(
        self,
        images: list[bytes],
        *,
        hint: str | None = None,  # noqa: ARG002 — le bouchon ignore l'indication
    ) -> VisionAnalysis:
        seed = self._seed(images)
        garment = _TYPES[seed % len(_TYPES)]
        color = _COLORS[(seed // 7) % len(_COLORS)]
        material = _MATERIALS[(seed // 13) % len(_MATERIALS)]
        return VisionAnalysis(
            garment_type=garment,
            brand=None,  # jamais de marque inventée, même en bouchon
            brand_confidence=0.0,
            color=color,
            material=material,
            fit=_FITS[(seed // 17) % len(_FITS)],
            condition=_CONDITIONS[(seed // 23) % len(_CONDITIONS)],
            defects=[] if seed % 3 else ["légères bouloches sous les bras"],
            has_visible_logo_or_text=bool(seed % 2),
            keywords=[garment, color, material],
            usage=Usage(model=self.model, input_tokens=0, output_tokens=0, latency_ms=1),
        )

    def write_listing(
        self,
        analysis: VisionAnalysis,
        *,
        tone: ToneProfile,
        variant_count: int,
        brand: str | None = None,
        size_label: str | None = None,
    ) -> CopyBatch:
        marque = brand or analysis.brand
        base = " ".join(
            part for part in [marque, analysis.garment_type, analysis.color, size_label] if part
        )
        # Chaque variante part d'une amorce différente : deux comptes ne
        # reçoivent jamais le même texte, y compris en mode hors ligne.
        openings = [
            f"{base}.",
            f"À saisir : {base.lower()}.",
            f"{analysis.garment_type or 'Pièce'} {analysis.color or ''} — {base}.".replace(
                "  ", " "
            ),
            f"Pièce sélectionnée : {base.lower()}.",
            f"{base} en {analysis.material or 'matière mélangée'}.",
            f"Disponible — {base.lower()}.",
        ]
        variants = []
        for index in range(variant_count):
            opening = openings[index % len(openings)]
            details = [
                f"Matière : {analysis.material}." if analysis.material else "",
                f"Coupe : {analysis.fit}." if analysis.fit else "",
                ("Défauts signalés : " + ", ".join(analysis.defects) + ".")
                if analysis.defects
                else "État conforme aux photos.",
            ]
            description = " ".join([opening, *[d for d in details if d]])[
                : tone.max_description_chars
            ]
            variants.append(
                ListingCopy(
                    title=(base or "Article")[:100],
                    description=description,
                    keywords=analysis.keywords,
                )
            )
        return CopyBatch(
            variants=variants,
            usage=Usage(model=self.model, input_tokens=0, output_tokens=0, latency_ms=1),
        )
