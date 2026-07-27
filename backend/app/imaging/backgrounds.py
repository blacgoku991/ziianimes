"""Fonds de recomposition.

Palette volontairement neutre et courte : les fonds saturés font baisser la
perception de qualité d'une annonce vêtement, et un fond identique d'une
variante à l'autre annulerait tout l'intérêt de la manœuvre.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class BackgroundSpec:
    key: str
    label: str
    #: Couleur principale en RGB 0-255.
    color: tuple[int, int, int]
    #: Couleur secondaire pour un dégradé doux ; identique = fond uni.
    color_to: tuple[int, int, int] | None = None
    #: Assombrissement des bords, 0 = aucun.
    vignette: float = 0.0


PALETTE: tuple[BackgroundSpec, ...] = (
    BackgroundSpec("white", "Blanc studio", (250, 250, 249)),
    BackgroundSpec("light_grey", "Gris clair", (235, 236, 238)),
    BackgroundSpec("beige", "Beige", (238, 231, 220)),
    BackgroundSpec("warm_grey", "Gris chaud", (228, 224, 219)),
    BackgroundSpec(
        "soft_gradient", "Dégradé doux", (248, 248, 247), color_to=(226, 228, 231), vignette=0.05
    ),
    BackgroundSpec(
        "cool_gradient", "Dégradé froid", (244, 246, 248), color_to=(223, 229, 234), vignette=0.04
    ),
)

BY_KEY = {spec.key: spec for spec in PALETTE}


def render_background(spec: BackgroundSpec, width: int, height: int) -> np.ndarray:
    """Construit le fond en float32 RGB [0, 1] à la taille demandée."""
    start = np.array(spec.color, dtype=np.float32) / 255.0
    if spec.color_to is None:
        canvas = np.empty((height, width, 3), dtype=np.float32)
        canvas[:, :] = start
    else:
        end = np.array(spec.color_to, dtype=np.float32) / 255.0
        # Dégradé vertical : c'est l'orientation qui imite le mieux une
        # chute de lumière de studio.
        ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
        canvas = start[None, None, :] * (1.0 - ramp) + end[None, None, :] * ramp
        canvas = np.ascontiguousarray(np.broadcast_to(canvas, (height, width, 3)))

    if spec.vignette > 0:
        canvas = _apply_vignette(canvas, spec.vignette)
    return np.clip(canvas, 0.0, 1.0)


def _apply_vignette(canvas: np.ndarray, strength: float) -> np.ndarray:
    height, width = canvas.shape[:2]
    kernel_x = cv2.getGaussianKernel(width, width * 0.6)
    kernel_y = cv2.getGaussianKernel(height, height * 0.6)
    mask = (kernel_y @ kernel_x.T).astype(np.float32)
    mask = mask / mask.max()
    factor = (1.0 - strength) + strength * mask
    return canvas * factor[:, :, None]
