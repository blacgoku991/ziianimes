"""Tests des opérations image de bas niveau."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.core.errors import UnprocessableImageError
from app.imaging import ops
from app.imaging.phash import hamming_distance, phash
from tests.conftest import make_image_bytes


def test_decode_returns_float_rgb_in_unit_range(image_bytes: bytes) -> None:
    decoded = ops.decode(image_bytes)
    assert decoded.rgb.dtype == np.float32
    assert decoded.rgb.ndim == 3 and decoded.rgb.shape[2] == 3
    assert float(decoded.rgb.min()) >= 0.0 and float(decoded.rgb.max()) <= 1.0
    assert decoded.alpha is None
    assert decoded.size == (900, 1200)


def test_decode_keeps_alpha_channel() -> None:
    image = Image.new("RGBA", (40, 60), (120, 30, 30, 128))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    decoded = ops.decode(buffer.getvalue())
    assert decoded.alpha is not None
    assert pytest.approx(float(decoded.alpha.mean()), abs=0.01) == 128 / 255


def test_decode_rejects_garbage() -> None:
    with pytest.raises(UnprocessableImageError):
        ops.decode(b"ceci n'est pas une image")


def test_decode_applies_exif_orientation() -> None:
    """Une photo prise en portrait ne doit pas ressortir couchée."""
    image = Image.new("RGB", (100, 40), (200, 200, 200))
    exif = image.getexif()
    exif[274] = 6  # rotation 90° horaire
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    decoded = ops.decode(buffer.getvalue())
    assert decoded.size == (40, 100)


def test_mirror_is_involutive(image_bytes: bytes) -> None:
    rgb = ops.decode(image_bytes).rgb
    once, _ = ops.mirror_horizontal(rgb, None)
    twice, _ = ops.mirror_horizontal(once, None)
    assert np.array_equal(rgb, twice)
    assert not np.array_equal(rgb, once)


@pytest.mark.parametrize("angle", [1.0, -2.0, 3.0])
def test_rotation_leaves_no_border_artifacts(image_bytes: bytes, angle: float) -> None:
    """Le recadrage intérieur garantit l'absence de coins vides.

    On vérifie qu'aucun bord n'est noir : c'est le symptôme classique d'une
    rotation sans recadrage.
    """
    rgb = ops.decode(image_bytes).rgb
    rotated, _ = ops.rotate(rgb, None, angle)

    height, width = rotated.shape[:2]
    assert height < rgb.shape[0] and width < rgb.shape[1]
    borders = np.concatenate(
        [
            rotated[0, :].ravel(),
            rotated[-1, :].ravel(),
            rotated[:, 0].ravel(),
            rotated[:, -1].ravel(),
        ]
    )
    assert float(borders.min()) > 0.02, "coin noir détecté après rotation"


def test_largest_inscribed_rect_shrinks_with_angle() -> None:
    wide, high = ops.largest_inscribed_rect(1000, 1000, 0.0)
    assert (wide, high) == (1000, 1000)
    for angle in (1.0, 3.0, 8.0):
        w, h = ops.largest_inscribed_rect(1000, 1000, angle)
        assert w < 1000 and h < 1000


def test_crop_fractions_are_asymmetric(image_bytes: bytes) -> None:
    rgb = ops.decode(image_bytes).rgb
    cropped, _ = ops.crop_fractions(rgb, None, left=0.08, right=0.02, top=0.05, bottom=0.03)
    expected_w = rgb.shape[1] - round(rgb.shape[1] * 0.08) - round(rgb.shape[1] * 0.02)
    assert cropped.shape[1] == expected_w


def test_crop_never_removes_more_than_half(image_bytes: bytes) -> None:
    """Garde-fou : un recadrage aberrant ne doit pas couper le vêtement."""
    rgb = ops.decode(image_bytes).rgb
    cropped, _ = ops.crop_fractions(rgb, None, left=0.9, right=0.9, top=0.9, bottom=0.9)
    assert cropped.shape[0] >= rgb.shape[0] // 2
    assert cropped.shape[1] >= rgb.shape[1] // 2


def test_resize_long_edge_respects_upscale_flag() -> None:
    small = np.full((200, 150, 3), 0.5, dtype=np.float32)
    kept, _ = ops.resize_long_edge(small, None, 1600, allow_upscale=False)
    assert kept.shape[:2] == (200, 150)
    grown, _ = ops.resize_long_edge(small, None, 1600, allow_upscale=True)
    assert max(grown.shape[:2]) == 1600


def test_colour_adjustments_stay_in_range(image_bytes: bytes) -> None:
    rgb = ops.decode(image_bytes).rgb
    for adjusted in (
        ops.adjust_brightness(rgb, 1.03),
        ops.adjust_contrast(rgb, 1.04),
        ops.adjust_temperature(rgb, 0.02),
    ):
        assert float(adjusted.min()) >= 0.0
        assert float(adjusted.max()) <= 1.0
        assert not np.array_equal(adjusted, rgb)


def test_composite_over_background_replaces_transparent_area() -> None:
    rgb = np.zeros((10, 10, 3), dtype=np.float32)
    alpha = np.zeros((10, 10), dtype=np.float32)
    alpha[3:7, 3:7] = 1.0
    background = np.ones((10, 10, 3), dtype=np.float32)
    result = ops.composite_over(rgb, alpha, background)
    assert result[0, 0].tolist() == [1.0, 1.0, 1.0]  # fond
    assert result[5, 5].tolist() == [0.0, 0.0, 0.0]  # sujet


def test_encode_jpeg_strips_metadata(image_bytes: bytes) -> None:
    rgb = ops.decode(image_bytes).rgb
    data = ops.encode_jpeg(rgb, quality=93)
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == "JPEG"
        assert not dict(out.getexif())


def test_phash_is_stable_under_reencoding(image_bytes: bytes) -> None:
    """Le pHash ne bouge pas pour une simple recompression.

    C'est précisément pourquoi republier le même fichier « juste
    réenregistré » ne trompe personne.
    """
    original = ops.decode(image_bytes).rgb
    recompressed = ops.decode(ops.encode_jpeg(original, quality=80)).rgb
    assert hamming_distance(phash(original), phash(recompressed)) <= 2


def test_phash_detects_a_real_transformation(image_bytes: bytes) -> None:
    original = ops.decode(image_bytes).rgb
    mirrored, _ = ops.mirror_horizontal(original, None)
    assert hamming_distance(phash(original), phash(mirrored)) > 2


def test_phash_hamming_distance_bounds() -> None:
    assert hamming_distance("0000000000000000", "0000000000000000") == 0
    assert hamming_distance("0000000000000000", "ffffffffffffffff") == 64


def test_decode_handles_png_and_webp() -> None:
    for fmt in ("PNG", "WEBP"):
        decoded = ops.decode(make_image_bytes(200, 260, fmt=fmt))
        assert decoded.size == (200, 260)
