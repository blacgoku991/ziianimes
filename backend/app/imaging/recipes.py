"""Recettes de variantes : paramètres tirés de façon déterministe.

Deux propriétés recherchées :

1. **Reproductibilité** — la recette est entièrement déterminée par
   `(seed, variant_index, intensity)` et sérialisée en base. On peut donc
   rejouer un rendu à l'identique, comparer deux rendus, ou déboguer une
   variante livrée il y a trois semaines.
2. **Bornes de qualité** — les amplitudes sont plafonnées dans le code, pas
   dans l'appelant. Même en escalade, une variante ne dépassera jamais 3°
   de rotation ni 10 % de recadrage : au-delà, la photo est visiblement
   dégradée et le vêtement commence à être coupé.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any

from app.imaging.backgrounds import PALETTE

# Bornes dures — voir docstring.
MAX_ROTATION_DEG = 3.0
MIN_ROTATION_DEG = 1.0
MAX_TOTAL_CROP = 0.10
MIN_TOTAL_CROP = 0.05
MAX_BRIGHTNESS_DELTA = 0.03
MAX_TEMPERATURE_DELTA = 0.02
MAX_CONTRAST_DELTA = 0.04


@dataclass(frozen=True)
class VariantRecipe:
    seed: int
    variant_index: int
    intensity: float = 1.0

    mirror: bool = False
    rotation_deg: float = 0.0
    crop_left: float = 0.0
    crop_right: float = 0.0
    crop_top: float = 0.0
    crop_bottom: float = 0.0

    brightness: float = 1.0
    temperature: float = 0.0
    contrast: float = 1.0

    #: Clé de fond dans `backgrounds.PALETTE`, ou None pour conserver le fond.
    background_key: str | None = None

    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VariantRecipe:
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**known)


def build_recipe(
    *,
    seed: int,
    variant_index: int,
    replace_background: bool = True,
    intensity: float = 1.0,
    allow_mirror: bool = True,
) -> VariantRecipe:
    """Tire une recette déterministe pour une variante donnée.

    `intensity` (≥ 1) sert à l'escalade quand la variante rendue reste trop
    proche de la source au sens du pHash ; elle pousse rotation et
    recadrage vers leurs bornes sans jamais les franchir.

    `allow_mirror` mérite une explication. Le miroir horizontal est la
    transformation la moins coûteuse et la plus efficace sur une empreinte
    perceptuelle — mais il **inverse les logos et les textes**. Un swoosh
    Nike retourné ou une étiquette illisible se voient immédiatement et
    décrédibilisent l'annonce. Il reste activé par défaut car il est sans
    danger sur des vêtements unis, et doit être désactivé pour les niches
    où la marque est visible sur le vêtement (streetwear, sport).
    """
    intensity = max(1.0, float(intensity))
    rng = random.Random(_mix(seed, variant_index))

    rotation_span = MAX_ROTATION_DEG - MIN_ROTATION_DEG
    rotation = MIN_ROTATION_DEG + rng.random() * rotation_span
    rotation = min(MAX_ROTATION_DEG, rotation * intensity)
    if rng.random() < 0.5:
        rotation = -rotation

    crop_span = MAX_TOTAL_CROP - MIN_TOTAL_CROP
    total_h = min(MAX_TOTAL_CROP, (MIN_TOTAL_CROP + rng.random() * crop_span) * intensity)
    total_v = min(MAX_TOTAL_CROP, (MIN_TOTAL_CROP + rng.random() * crop_span) * intensity)
    # Répartition franchement asymétrique : un recadrage centré ne déplace
    # pas le sujet et laisse l'empreinte perceptuelle presque intacte.
    split_h = rng.uniform(0.2, 0.8)
    split_v = rng.uniform(0.2, 0.8)

    background_key = None
    if replace_background:
        # Le décalage ne dépend que de la graine, jamais de l'index : c'est
        # ce qui fait de `index -> fond` une bijection, et donc ce qui
        # garantit que deux variantes d'une même photo ne reçoivent jamais
        # le même fond tant qu'il en reste dans la palette.
        offset = _mix(seed, 0) % len(PALETTE)
        background_key = PALETTE[(offset + variant_index) % len(PALETTE)].key

    return VariantRecipe(
        seed=seed,
        variant_index=variant_index,
        intensity=intensity,
        # Le tirage a lieu dans tous les cas : désactiver le miroir ne doit
        # pas décaler toutes les autres valeurs de la recette.
        mirror=(rng.random() < 0.5) and allow_mirror,
        rotation_deg=round(rotation, 3),
        crop_left=round(total_h * split_h, 4),
        crop_right=round(total_h * (1.0 - split_h), 4),
        crop_top=round(total_v * split_v, 4),
        crop_bottom=round(total_v * (1.0 - split_v), 4),
        brightness=round(1.0 + rng.uniform(-MAX_BRIGHTNESS_DELTA, MAX_BRIGHTNESS_DELTA), 4),
        temperature=round(rng.uniform(-MAX_TEMPERATURE_DELTA, MAX_TEMPERATURE_DELTA), 4),
        contrast=round(1.0 + rng.uniform(-MAX_CONTRAST_DELTA, MAX_CONTRAST_DELTA), 4),
        background_key=background_key,
    )


def _mix(seed: int, variant_index: int) -> int:
    """Mélange seed et index pour éviter les corrélations entre variantes."""
    return (int(seed) * 0x9E3779B1 + int(variant_index) * 0x85EBCA77) & 0xFFFFFFFFFFFF
