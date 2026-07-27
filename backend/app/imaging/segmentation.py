"""Détourage du sujet.

`rembg` (U²-Net) est une dépendance lourde qui télécharge un modèle au
premier appel : elle est chargée paresseusement et reste optionnelle. Sans
elle, le pipeline continue sans remplacement de fond — les variations
géométriques et colorimétriques suffisent à écarter les empreintes — et la
variante est marquée `background_replaced = false` pour que l'interface le
dise clairement plutôt que de laisser croire à un détourage raté.

La segmentation tourne sur une copie réduite : le masque est ensuite
ré-agrandi. Seule la précision du contour est concernée, jamais les pixels
du sujet, qui restent ceux de la source pleine résolution.
"""

from __future__ import annotations

import io
import threading
from typing import Protocol

import cv2
import numpy as np
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Côté long utilisé pour l'inférence du masque.
SEGMENTATION_LONG_EDGE = 1024


class Segmenter(Protocol):
    available: bool

    def alpha(self, rgb: np.ndarray) -> np.ndarray | None:
        """Retourne un masque (H, W) float32 dans [0, 1], ou None."""


class NullSegmenter:
    """Aucun détourage — le pipeline garde le fond d'origine."""

    available = False

    def alpha(self, rgb: np.ndarray) -> np.ndarray | None:  # noqa: ARG002
        return None


class RembgSegmenter:
    """Adaptateur `rembg`, chargé une seule fois par processus."""

    def __init__(self) -> None:
        self._session: object | None = None
        self._lock = threading.Lock()
        self._failed = False

    @property
    def available(self) -> bool:
        return not self._failed

    def _ensure_session(self) -> object | None:
        if self._session is not None or self._failed:
            return self._session
        with self._lock:
            if self._session is None and not self._failed:
                try:
                    from rembg import new_session  # type: ignore[import-not-found]

                    self._session = new_session("u2net")
                except Exception as exc:
                    logger.warning("segmentation_unavailable", error=str(exc))
                    self._failed = True
        return self._session

    def alpha(self, rgb: np.ndarray) -> np.ndarray | None:
        session = self._ensure_session()
        if session is None:
            return None
        try:
            from rembg import remove  # type: ignore[import-not-found]

            height, width = rgb.shape[:2]
            small = _downscale(rgb, SEGMENTATION_LONG_EDGE)
            buffer = io.BytesIO()
            Image.fromarray((small * 255.0).astype(np.uint8), mode="RGB").save(buffer, format="PNG")
            cut = remove(buffer.getvalue(), session=session)
            with Image.open(io.BytesIO(cut)) as out:
                mask_small = np.asarray(out.convert("RGBA"), dtype=np.float32)[:, :, 3] / 255.0
        except Exception as exc:
            logger.warning("segmentation_failed", error=str(exc))
            return None

        if mask_small.max() < 0.05:
            # Masque vide : mieux vaut ne pas détourer que livrer un aplat.
            return None
        return cv2.resize(mask_small, (width, height), interpolation=cv2.INTER_LINEAR)


def _downscale(rgb: np.ndarray, long_edge: int) -> np.ndarray:
    height, width = rgb.shape[:2]
    scale = long_edge / float(max(height, width))
    if scale >= 1.0:
        return rgb
    return cv2.resize(
        rgb, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA
    )


_singleton: Segmenter | None = None
_singleton_lock = threading.Lock()


def get_segmenter() -> Segmenter:
    """Segmenteur du processus, selon `SEGMENTATION_BACKEND`."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                if settings.segmentation_backend == "none":
                    _singleton = NullSegmenter()
                else:
                    _singleton = RembgSegmenter()
    return _singleton


def reset_segmenter() -> None:
    """Réinitialise le singleton (tests, changement de configuration)."""
    global _singleton
    _singleton = None
