"""Tests du pipeline de variantes.

Ces tests portent sur les promesses faites dans la spécification :
une seule passe d'encodage, pas de dégradation visible, un écart
perceptuel réel avec la source, et des recettes reproductibles.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.imaging import ops
from app.imaging.backgrounds import PALETTE, BackgroundSpec, render_background
from app.imaging.phash import hamming_distance, phash
from app.imaging.pipeline import (
    analyse_source,
    render_variant,
    render_variant_with_guarantee,
)
from app.imaging.recipes import (
    MAX_ROTATION_DEG,
    MAX_TOTAL_CROP,
    VariantRecipe,
    build_recipe,
)
from app.imaging.segmentation import NullSegmenter
from tests.conftest import make_image_bytes


class _FakeSegmenter:
    """Segmenteur déterministe : masque rectangulaire centré."""

    available = True

    def alpha(self, rgb: np.ndarray) -> np.ndarray:
        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), dtype=np.float32)
        mask[int(height * 0.15) : int(height * 0.85), int(width * 0.15) : int(width * 0.85)] = 1.0
        return mask


# ---------------------------------------------------------------------------
# Encodage unique
# ---------------------------------------------------------------------------


def test_pipeline_encodes_exactly_once(image_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    """Une variante = une seule écriture compressée.

    C'est l'invariant qui protège la qualité : tout encodage intermédiaire
    ferait passer les pixels par une quantification JPEG supplémentaire.
    """
    calls: list[str] = []
    original_save = Image.Image.save

    def counting_save(self, fp, format=None, **params):  # type: ignore[no-untyped-def]
        calls.append(format or "?")
        return original_save(self, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", counting_save)

    recipe = build_recipe(seed=1234, variant_index=0, replace_background=False)
    render_variant(image_bytes, recipe, segmenter=NullSegmenter())

    assert calls == ["JPEG"], f"encodages observés : {calls}"


def test_pipeline_with_background_still_encodes_once(
    image_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Même avec détourage et recomposition, un seul encodage en sortie."""
    calls: list[str] = []
    original_save = Image.Image.save

    def counting_save(self, fp, format=None, **params):  # type: ignore[no-untyped-def]
        calls.append(format or "?")
        return original_save(self, fp, format=format, **params)

    monkeypatch.setattr(Image.Image, "save", counting_save)

    recipe = build_recipe(seed=99, variant_index=1, replace_background=True)
    result = render_variant(image_bytes, recipe, segmenter=_FakeSegmenter())

    assert result.background_replaced is True
    assert calls == ["JPEG"]


# ---------------------------------------------------------------------------
# Qualité de sortie
# ---------------------------------------------------------------------------


def test_variant_output_is_clean_jpeg(image_bytes: bytes) -> None:
    recipe = build_recipe(seed=5, variant_index=0, replace_background=False)
    result = render_variant(
        image_bytes, recipe, quality=93, min_long_edge=1600, segmenter=NullSegmenter()
    )

    with Image.open(io.BytesIO(result.data)) as out:
        assert out.format == "JPEG"
        assert out.mode == "RGB"
        assert not dict(out.getexif()), "les métadonnées EXIF doivent être supprimées"
        assert out.size == (result.width, result.height)


def test_variant_respects_minimum_long_edge(image_bytes: bytes) -> None:
    recipe = build_recipe(seed=5, variant_index=0, replace_background=False)
    result = render_variant(
        image_bytes,
        recipe,
        min_long_edge=1600,
        allow_upscale=True,
        segmenter=NullSegmenter(),
    )
    assert max(result.width, result.height) >= 1600


def test_small_source_is_not_upscaled_when_disallowed() -> None:
    small = make_image_bytes(400, 500)
    recipe = build_recipe(seed=5, variant_index=0, replace_background=False)
    result = render_variant(
        small, recipe, min_long_edge=1600, allow_upscale=False, segmenter=NullSegmenter()
    )
    assert max(result.width, result.height) < 1600
    assert result.upscaled is False


def test_variant_does_not_degrade_visibly(image_bytes: bytes) -> None:
    """Contrôle de non-dégradation.

    On compare la variante à la source recadrée de la même façon : l'écart
    photométrique moyen doit rester faible et le niveau de détail (variance
    laplacienne, proxy de netteté) ne doit pas s'effondrer.
    """
    import cv2

    source = ops.decode(image_bytes).rgb
    # Recette purement géométrique douce, sans miroir ni fond, pour pouvoir
    # comparer les mêmes pixels.
    recipe = VariantRecipe(
        seed=1,
        variant_index=0,
        mirror=False,
        rotation_deg=0.0,
        crop_left=0.05,
        crop_right=0.03,
        crop_top=0.04,
        crop_bottom=0.02,
        brightness=1.0,
        temperature=0.0,
        contrast=1.0,
        background_key=None,
    )
    result = render_variant(
        image_bytes, recipe, quality=93, min_long_edge=64, segmenter=NullSegmenter()
    )
    variant = ops.decode(result.data).rgb

    reference, _ = ops.crop_fractions(source, None, left=0.05, right=0.03, top=0.04, bottom=0.02)
    assert variant.shape == reference.shape

    mean_abs_error = float(np.abs(variant - reference).mean())
    assert mean_abs_error < 0.02, f"écart photométrique trop élevé : {mean_abs_error}"

    def sharpness(array: np.ndarray) -> float:
        gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_32F).var())

    assert sharpness(variant) > 0.5 * sharpness(reference)


# ---------------------------------------------------------------------------
# Écart perceptuel
# ---------------------------------------------------------------------------


def test_variant_diverges_from_source(image_bytes: bytes) -> None:
    result = render_variant_with_guarantee(
        image_bytes, seed=42, variant_index=0, replace_background=False, min_distance=10
    )
    assert result.distance_to_source >= 10
    assert result.attempts >= 1


@pytest.mark.parametrize("index", [0, 1, 2])
def test_sibling_variants_differ_from_each_other(image_bytes: bytes, index: int) -> None:
    """Deux variantes de la même photo doivent aussi différer entre elles."""
    hashes = [
        render_variant_with_guarantee(
            image_bytes, seed=1000 + i, variant_index=i, replace_background=False
        ).phash
        for i in range(3)
    ]
    others = [h for i, h in enumerate(hashes) if i != index]
    for other in others:
        assert hamming_distance(hashes[index], other) > 0


def test_guarantee_escalates_when_needed(image_bytes: bytes) -> None:
    """Une exigence irréaliste épuise les tentatives sans jamais planter."""
    result = render_variant_with_guarantee(
        image_bytes,
        seed=7,
        variant_index=0,
        replace_background=False,
        min_distance=64,  # inatteignable par construction
        max_attempts=2,
    )
    assert result.attempts == 2
    assert result.distance_to_source < 64  # la valeur réelle est remontée, pas masquée


def test_analyse_source_reports_dimensions_and_hash(image_bytes: bytes) -> None:
    analysis = analyse_source(image_bytes)
    assert (analysis.width, analysis.height) == (900, 1200)
    assert len(analysis.phash) == 16
    assert analysis.phash == phash(ops.decode(image_bytes).rgb)


# ---------------------------------------------------------------------------
# Recettes
# ---------------------------------------------------------------------------


def test_recipe_is_deterministic() -> None:
    first = build_recipe(seed=777, variant_index=2)
    second = build_recipe(seed=777, variant_index=2)
    assert first == second


def test_recipe_varies_with_index() -> None:
    recipes = [build_recipe(seed=777, variant_index=i) for i in range(4)]
    assert len({r.background_key for r in recipes}) == 4
    assert len({(r.rotation_deg, r.crop_left) for r in recipes}) == 4


def test_recipe_stays_within_quality_bounds() -> None:
    """Même poussée à fond, l'escalade ne dégrade pas l'image."""
    for index in range(6):
        for intensity in (1.0, 2.0, 10.0):
            recipe = build_recipe(seed=index * 13, variant_index=index, intensity=intensity)
            assert abs(recipe.rotation_deg) <= MAX_ROTATION_DEG
            assert recipe.crop_left + recipe.crop_right <= MAX_TOTAL_CROP + 1e-9
            assert recipe.crop_top + recipe.crop_bottom <= MAX_TOTAL_CROP + 1e-9
            assert 0.97 <= recipe.brightness <= 1.03
            assert abs(recipe.temperature) <= 0.02
            assert 0.96 <= recipe.contrast <= 1.04


def test_recipe_round_trips_through_json() -> None:
    recipe = build_recipe(seed=31, variant_index=1)
    assert VariantRecipe.from_dict(recipe.to_dict()) == recipe


def test_render_is_reproducible_from_a_stored_recipe(image_bytes: bytes) -> None:
    """Une recette stockée en base permet de rejouer le rendu à l'identique."""
    recipe = build_recipe(seed=2024, variant_index=1, replace_background=False)
    first = render_variant(image_bytes, recipe, segmenter=NullSegmenter())
    replayed = render_variant(
        image_bytes, VariantRecipe.from_dict(recipe.to_dict()), segmenter=NullSegmenter()
    )
    assert first.data == replayed.data


# ---------------------------------------------------------------------------
# Fonds
# ---------------------------------------------------------------------------


def test_backgrounds_render_at_requested_size() -> None:
    for spec in PALETTE:
        canvas = render_background(spec, 60, 40)
        assert canvas.shape == (40, 60, 3)
        assert float(canvas.min()) >= 0.0 and float(canvas.max()) <= 1.0


def test_gradient_background_actually_varies() -> None:
    spec = BackgroundSpec("g", "g", (255, 255, 255), color_to=(200, 200, 200))
    canvas = render_background(spec, 20, 100)
    assert float(canvas[0].mean()) > float(canvas[-1].mean())


def test_pipeline_without_segmenter_keeps_original_background(image_bytes: bytes) -> None:
    """Sans détourage disponible, on ne prétend pas avoir remplacé le fond."""
    recipe = build_recipe(seed=3, variant_index=0, replace_background=True)
    result = render_variant(image_bytes, recipe, segmenter=NullSegmenter())
    assert result.background_replaced is False
    assert len(result.data) > 0


def test_mirror_can_be_disabled_without_shifting_the_recipe() -> None:
    """Couper le miroir ne doit pas changer le reste de la recette.

    Le miroir inverse logos et textes ; pour les niches où la marque est
    visible sur le vêtement, on le coupe. Les autres paramètres doivent
    rester identiques, sinon désactiver une option changerait silencieusement
    tous les rendus déjà validés.
    """
    with_mirror = build_recipe(seed=4242, variant_index=0, allow_mirror=True)
    without = build_recipe(seed=4242, variant_index=0, allow_mirror=False)

    assert without.mirror is False
    assert (without.rotation_deg, without.crop_left, without.brightness) == (
        with_mirror.rotation_deg,
        with_mirror.crop_left,
        with_mirror.brightness,
    )


def test_disabled_mirror_still_reaches_the_required_distance(image_bytes: bytes) -> None:
    """Sans miroir, l'écart perceptuel doit rester atteignable."""
    result = render_variant_with_guarantee(
        image_bytes,
        seed=8,
        variant_index=0,
        replace_background=False,
        allow_mirror=False,
        min_distance=10,
    )
    assert result.recipe.mirror is False
    assert result.distance_to_source >= 10
