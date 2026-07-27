"""Pipeline de génération de variantes.

Invariant central, celui qui conditionne la qualité perçue :

    décodage → (segmentation) → géométrie → composition → colorimétrie
    → mise à l'échelle → **un seul encodage**

Aucune étape intermédiaire ne repasse par un format compressé. La fonction
`render_variant` appelle `ops.encode_jpeg` exactement une fois ; un test le
vérifie en comptant les appels à `PIL.Image.Image.save`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.imaging import ops
from app.imaging.backgrounds import BY_KEY, render_background
from app.imaging.phash import hamming_distance, phash
from app.imaging.recipes import VariantRecipe, build_recipe
from app.imaging.segmentation import Segmenter, get_segmenter

logger = get_logger(__name__)


@dataclass
class SourceAnalysis:
    width: int
    height: int
    phash: str


@dataclass
class RenderResult:
    data: bytes
    content_type: str
    width: int
    height: int
    phash: str
    distance_to_source: int
    background_replaced: bool
    recipe: VariantRecipe
    render_ms: int
    attempts: int
    upscaled: bool


def analyse_source(data: bytes) -> SourceAnalysis:
    """Dimensions et empreinte perceptuelle d'une photo source."""
    decoded = ops.decode(data)
    width, height = decoded.size
    return SourceAnalysis(width=width, height=height, phash=phash(decoded.rgb))


def render_variant(
    source: bytes | ops.DecodedImage,
    recipe: VariantRecipe,
    *,
    quality: int | None = None,
    min_long_edge: int | None = None,
    max_long_edge: int | None = None,
    allow_upscale: bool | None = None,
    segmenter: Segmenter | None = None,
) -> RenderResult:
    """Rend une variante à partir de la **source pleine résolution**."""
    started = time.perf_counter()
    quality = settings.image_output_quality if quality is None else quality
    min_long_edge = settings.image_min_long_edge if min_long_edge is None else min_long_edge
    max_long_edge = settings.image_max_long_edge if max_long_edge is None else max_long_edge
    allow_upscale = settings.image_allow_upscale if allow_upscale is None else allow_upscale

    decoded = ops.decode(source) if isinstance(source, (bytes, bytearray)) else source
    source_phash = phash(decoded.rgb)
    rgb = decoded.rgb
    alpha = decoded.alpha

    # 1. Détourage. Le masque est calculé sur la source d'origine, avant
    #    toute transformation géométrique : la segmentation est plus fiable
    #    sur l'image telle qu'elle a été prise.
    background_replaced = False
    if recipe.background_key is not None and alpha is None:
        segmenter = segmenter or get_segmenter()
        mask = segmenter.alpha(rgb)
        if mask is not None:
            alpha = ops.refine_alpha(mask)

    # 2. Géométrie — appliquée conjointement aux pixels et au masque.
    if recipe.mirror:
        rgb, alpha = ops.mirror_horizontal(rgb, alpha)
    rgb, alpha = ops.rotate(rgb, alpha, recipe.rotation_deg)
    rgb, alpha = ops.crop_fractions(
        rgb,
        alpha,
        left=recipe.crop_left,
        right=recipe.crop_right,
        top=recipe.crop_top,
        bottom=recipe.crop_bottom,
    )

    # 3. Recomposition sur fond uni ou dégradé.
    if alpha is not None and recipe.background_key is not None:
        spec = BY_KEY.get(recipe.background_key)
        if spec is not None:
            background = render_background(spec, rgb.shape[1], rgb.shape[0])
            rgb = ops.composite_over(rgb, alpha, background)
            background_replaced = True
    elif alpha is not None:
        # Source déjà transparente sans fond demandé : on aplatit sur blanc,
        # sinon l'encodage JPEG produirait des zones noires.
        white = np.ones_like(rgb)
        rgb = ops.composite_over(rgb, alpha, white)

    # 4. Colorimétrie.
    rgb = ops.adjust_brightness(rgb, recipe.brightness)
    rgb = ops.adjust_temperature(rgb, recipe.temperature)
    rgb = ops.adjust_contrast(rgb, recipe.contrast)

    # 5. Mise à l'échelle finale.
    long_edge = max(rgb.shape[:2])
    upscaled = False
    if long_edge > max_long_edge:
        rgb, _ = ops.resize_long_edge(rgb, None, max_long_edge, allow_upscale=False)
    elif long_edge < min_long_edge:
        before = long_edge
        rgb, _ = ops.resize_long_edge(rgb, None, min_long_edge, allow_upscale=allow_upscale)
        upscaled = max(rgb.shape[:2]) > before

    # 6. Encodage — unique.
    data = ops.encode_jpeg(rgb, quality=quality)

    variant_phash = phash(rgb)
    return RenderResult(
        data=data,
        content_type="image/jpeg",
        width=rgb.shape[1],
        height=rgb.shape[0],
        phash=variant_phash,
        distance_to_source=hamming_distance(source_phash, variant_phash),
        background_replaced=background_replaced,
        recipe=recipe,
        render_ms=int((time.perf_counter() - started) * 1000),
        attempts=1,
        upscaled=upscaled,
    )


def render_variant_with_guarantee(
    source: bytes,
    *,
    seed: int,
    variant_index: int,
    replace_background: bool = True,
    min_distance: int | None = None,
    max_attempts: int | None = None,
    allow_mirror: bool | None = None,
    segmenter: Segmenter | None = None,
) -> RenderResult:
    """Rend une variante et **garantit** un écart perceptuel minimal.

    Si la variante reste trop proche de sa source, on ne la livre pas telle
    quelle : on rejoue avec une recette plus marquée (dans les bornes de
    qualité). Après épuisement des tentatives, on retourne la meilleure
    obtenue — l'appelant reste libre de la refuser, mais la distance
    mesurée est stockée et affichée plutôt que passée sous silence.
    """
    min_distance = settings.variant_min_phash_distance if min_distance is None else min_distance
    max_attempts = settings.variant_max_render_attempts if max_attempts is None else max_attempts
    allow_mirror = settings.variant_allow_mirror if allow_mirror is None else allow_mirror

    # Un seul décodage pour toutes les tentatives : la source n'est jamais
    # relue ni réencodée entre deux essais.
    decoded = ops.decode(source)
    best: RenderResult | None = None

    for attempt in range(1, max_attempts + 1):
        recipe = build_recipe(
            seed=seed,
            variant_index=variant_index,
            replace_background=replace_background,
            intensity=1.0 + 0.35 * (attempt - 1),
            allow_mirror=allow_mirror,
        )
        result = render_variant(
            ops.DecodedImage(rgb=decoded.rgb, alpha=decoded.alpha),
            recipe,
            segmenter=segmenter,
        )
        result.attempts = attempt
        if best is None or result.distance_to_source > best.distance_to_source:
            best = result
        if result.distance_to_source >= min_distance:
            return result
        logger.info(
            "variant_too_similar",
            variant_index=variant_index,
            attempt=attempt,
            distance=result.distance_to_source,
            required=min_distance,
        )

    assert best is not None
    best.attempts = max_attempts
    return best
