"""Opérations image en espace flottant.

Règle du module : **tout se passe en `float32` RGB dans `[0, 1]`**. Aucune
fonction ici n'encode ni ne décode un format compressé. Le décodage a lieu
une fois à l'entrée du pipeline, l'encodage une fois à la sortie ; entre les
deux, il n'y a jamais de JPEG intermédiaire, donc pas d'artefacts
recompressés qui s'accumulent.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

from app.core.errors import UnprocessableImageError

# Limite de garde : au-delà, on refuse plutôt que de saturer la mémoire du
# worker (une image 20 000 x 20 000 en float32 = 4,8 Go).
MAX_SOURCE_PIXELS = 60_000_000
Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


@dataclass
class DecodedImage:
    """Image décodée en pleine résolution, prête pour le pipeline."""

    rgb: np.ndarray  # (H, W, 3) float32 dans [0, 1]
    alpha: np.ndarray | None  # (H, W) float32 dans [0, 1] ou None

    @property
    def size(self) -> tuple[int, int]:
        return self.rgb.shape[1], self.rgb.shape[0]


def decode(data: bytes) -> DecodedImage:
    """Décode des octets image vers du RGB flottant, orientation corrigée.

    - l'orientation EXIF est appliquée puis oubliée (les métadonnées ne sont
      jamais réémises en sortie) ;
    - un profil ICC non sRGB est converti, pas ignoré : sinon les couleurs
      dérivent à l'affichage sur les plateformes.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            icc = img.info.get("icc_profile")
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            img = img.convert("RGBA" if has_alpha else "RGB")
            if icc:
                img = _to_srgb(img, icc)
            array = np.asarray(img, dtype=np.float32) / 255.0
    except UnprocessableImageError:
        raise
    except Exception as exc:  # format inconnu, fichier tronqué
        raise UnprocessableImageError(f"image illisible : {exc}") from exc

    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise UnprocessableImageError("image dans un mode couleur non géré")
    if array.shape[0] < 2 or array.shape[1] < 2:
        raise UnprocessableImageError("image trop petite")

    if array.shape[2] == 4:
        return DecodedImage(rgb=np.ascontiguousarray(array[:, :, :3]), alpha=array[:, :, 3].copy())
    return DecodedImage(rgb=array, alpha=None)


def _to_srgb(img: Image.Image, icc: bytes) -> Image.Image:
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        target = ImageCms.createProfile("sRGB")
        return ImageCms.profileToProfile(img, source, target, outputMode=img.mode)  # type: ignore[return-value]
    except Exception:
        # Profil exotique ou illisible : on garde les pixels tels quels
        # plutôt que de faire échouer l'import de la photo.
        return img


# ---------------------------------------------------------------------------
# Géométrie
# ---------------------------------------------------------------------------


def mirror_horizontal(
    rgb: np.ndarray, alpha: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray | None]:
    return np.ascontiguousarray(rgb[:, ::-1]), (
        np.ascontiguousarray(alpha[:, ::-1]) if alpha is not None else None
    )


def largest_inscribed_rect(width: int, height: int, angle_deg: float) -> tuple[int, int]:
    """Plus grand rectangle aligné aux axes contenu dans le rectangle tourné.

    C'est ce qui permet une rotation **sans bord noir ni bord répliqué** :
    on ne rattrape pas les coins manquants, on recadre à l'intérieur.
    """
    angle = math.radians(abs(angle_deg) % 180.0)
    if angle > math.pi / 2:
        angle = math.pi - angle
    if width <= 0 or height <= 0:
        return 0, 0

    width_is_longer = width >= height
    side_long, side_short = (width, height) if width_is_longer else (height, width)
    sin_a, cos_a = abs(math.sin(angle)), abs(math.cos(angle))

    if side_short <= 2.0 * sin_a * cos_a * side_long or abs(sin_a - cos_a) < 1e-10:
        # Solution dégénérée : le rectangle est limité par son petit côté.
        half = 0.5 * side_short
        if width_is_longer:
            rect_w, rect_h = (
                half / sin_a if sin_a else float(width),
                half / cos_a if cos_a else float(height),
            )
        else:
            rect_w, rect_h = (
                half / cos_a if cos_a else float(width),
                half / sin_a if sin_a else float(height),
            )
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        rect_w = (width * cos_a - height * sin_a) / cos_2a
        rect_h = (height * cos_a - width * sin_a) / cos_2a

    return max(1, int(math.floor(rect_w))), max(1, int(math.floor(rect_h)))


def rotate(
    rgb: np.ndarray, alpha: np.ndarray | None, angle_deg: float
) -> tuple[np.ndarray, np.ndarray | None]:
    """Rotation légère suivie d'un recadrage intérieur.

    L'interpolation est bicubique (`INTER_CUBIC`) : sur 1 à 3 degrés, le
    ré-échantillonnage est le seul coût qualité, et il reste sous le seuil
    de perception à ces résolutions.
    """
    if abs(angle_deg) < 1e-3:
        return rgb, alpha

    height, width = rgb.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle_deg, 1.0)
    rotated = cv2.warpAffine(
        rgb, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    rotated_alpha = None
    if alpha is not None:
        rotated_alpha = cv2.warpAffine(
            alpha,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )

    crop_w, crop_h = largest_inscribed_rect(width, height, angle_deg)
    x0 = (width - crop_w) // 2
    y0 = (height - crop_h) // 2
    rgb_out = np.ascontiguousarray(rotated[y0 : y0 + crop_h, x0 : x0 + crop_w])
    alpha_out = (
        np.ascontiguousarray(rotated_alpha[y0 : y0 + crop_h, x0 : x0 + crop_w])
        if rotated_alpha is not None
        else None
    )
    return np.clip(rgb_out, 0.0, 1.0), alpha_out


def crop_fractions(
    rgb: np.ndarray,
    alpha: np.ndarray | None,
    *,
    left: float,
    right: float,
    top: float,
    bottom: float,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Recadrage asymétrique exprimé en fractions de chaque bord."""
    height, width = rgb.shape[:2]
    # On refuse de retirer plus de la moitié d'une dimension : un recadrage
    # agressif coupe le vêtement, ce qui est bien pire qu'une photo trop
    # proche de l'originale. Les fractions sont réduites proportionnellement
    # pour conserver l'asymétrie voulue.
    left, right = _clamp_pair(left, right)
    top, bottom = _clamp_pair(top, bottom)

    x0 = int(round(width * left))
    x1 = width - int(round(width * right))
    y0 = int(round(height * top))
    y1 = height - int(round(height * bottom))
    x1 = max(x1, x0 + 2)
    y1 = max(y1, y0 + 2)
    out = np.ascontiguousarray(rgb[y0:y1, x0:x1])
    out_alpha = np.ascontiguousarray(alpha[y0:y1, x0:x1]) if alpha is not None else None
    return out, out_alpha


#: Fraction maximale retirée sur une dimension (les deux bords cumulés).
MAX_CROP_PER_AXIS = 0.5


def _clamp_pair(first: float, second: float) -> tuple[float, float]:
    first, second = max(0.0, first), max(0.0, second)
    total = first + second
    if total <= MAX_CROP_PER_AXIS:
        return first, second
    scale = MAX_CROP_PER_AXIS / total
    return first * scale, second * scale


def resize_long_edge(
    rgb: np.ndarray,
    alpha: np.ndarray | None,
    target_long_edge: int,
    *,
    allow_upscale: bool,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Amène le côté long à `target_long_edge`.

    Réduction en `INTER_AREA` (moyennage, pas d'aliasing), agrandissement en
    Lanczos. L'agrandissement n'a lieu que s'il est explicitement autorisé :
    gonfler une source de 600 px vers 1600 px produit une image molle qu'il
    vaut souvent mieux ne pas publier.
    """
    height, width = rgb.shape[:2]
    long_edge = max(width, height)
    if long_edge == target_long_edge:
        return rgb, alpha
    if long_edge < target_long_edge and not allow_upscale:
        return rgb, alpha

    scale = target_long_edge / float(long_edge)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LANCZOS4
    out = cv2.resize(rgb, new_size, interpolation=interp)
    out_alpha = cv2.resize(alpha, new_size, interpolation=interp) if alpha is not None else None
    return np.clip(out, 0.0, 1.0), (np.clip(out_alpha, 0.0, 1.0) if out_alpha is not None else None)


# ---------------------------------------------------------------------------
# Colorimétrie
# ---------------------------------------------------------------------------


def adjust_brightness(rgb: np.ndarray, factor: float) -> np.ndarray:
    """Facteur multiplicatif (1.03 = +3 %)."""
    return np.clip(rgb * float(factor), 0.0, 1.0)


def adjust_contrast(rgb: np.ndarray, factor: float) -> np.ndarray:
    """Contraste autour du gris moyen de l'image, pas autour de 0,5.

    Pivoter sur la moyenne réelle évite d'assombrir globalement une photo
    sur fond clair, cas dominant en prise de vue vêtement.
    """
    pivot = float(rgb.mean())
    return np.clip((rgb - pivot) * float(factor) + pivot, 0.0, 1.0)


def adjust_temperature(rgb: np.ndarray, delta: float) -> np.ndarray:
    """Balance chaud/froid. `delta` positif réchauffe (R+, B-)."""
    gains = np.array([1.0 + delta, 1.0 + delta * 0.15, 1.0 - delta], dtype=np.float32)
    return np.clip(rgb * gains, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def refine_alpha(alpha: np.ndarray, *, erode_px: int = 1, feather_px: float = 1.2) -> np.ndarray:
    """Nettoie un masque de segmentation avant composition.

    L'érosion d'un ou deux pixels supprime le liseré de l'ancien fond qui
    reste collé au sujet ; le flou léger évite l'escalier sur les contours.
    """
    work = np.clip(alpha, 0.0, 1.0).astype(np.float32)
    if erode_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_px * 2 + 1, erode_px * 2 + 1))
        work = cv2.erode(work, kernel)
    if feather_px > 0:
        work = cv2.GaussianBlur(work, (0, 0), sigmaX=float(feather_px))
    return np.clip(work, 0.0, 1.0)


def composite_over(rgb: np.ndarray, alpha: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Compose `rgb` (avec son alpha) au-dessus d'un fond de même taille."""
    if background.shape[:2] != rgb.shape[:2]:
        background = cv2.resize(
            background, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR
        )
    a = alpha[:, :, None]
    return np.clip(rgb * a + background * (1.0 - a), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Encodage — unique point de sortie compressé du pipeline
# ---------------------------------------------------------------------------


def encode_jpeg(rgb: np.ndarray, *, quality: int) -> bytes:
    """Encode en JPEG, une seule fois, sans métadonnées.

    `subsampling=0` (4:4:4) : le sous-échantillonnage chroma par défaut
    abîme visiblement les textiles saturés et les motifs fins.
    """
    array = np.clip(rgb, 0.0, 1.0)
    as_uint8 = np.rint(array * 255.0).astype(np.uint8)
    image = Image.fromarray(as_uint8, mode="RGB")
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=int(quality),
        subsampling=0,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue()
