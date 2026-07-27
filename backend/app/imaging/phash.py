"""Hash perceptuel (pHash DCT) — la mesure objective du pipeline.

C'est l'outil que les plateformes utilisent pour repérer deux annonces
portant la même photo. On s'en sert ici dans l'autre sens : vérifier qu'une
variante s'écarte suffisamment de sa source, et refuser de livrer une
variante qui ne s'en écarte pas.
"""

from __future__ import annotations

import cv2
import numpy as np

_HASH_SIZE = 8
_DCT_SIZE = 32


def phash(rgb: np.ndarray) -> str:
    """Empreinte 64 bits, rendue en hexadécimal (16 caractères)."""
    if rgb.ndim == 3:
        gray = cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2GRAY)
    else:
        gray = rgb.astype(np.float32)
    resized = cv2.resize(gray, (_DCT_SIZE, _DCT_SIZE), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(resized)
    block = coefficients[:_HASH_SIZE, :_HASH_SIZE].flatten()
    # On exclut le coefficient continu : il ne porte que la luminance
    # moyenne, qui varierait pour un simple réglage d'exposition.
    median = float(np.median(block[1:]))
    bits = block > median
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming_distance(left: str, right: str) -> int:
    """Nombre de bits différents entre deux empreintes (0 à 64)."""
    return bin(int(left, 16) ^ int(right, 16)).count("1")
