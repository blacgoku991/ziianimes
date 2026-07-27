"""Traitement d'image : décodage, variantes, empreintes perceptuelles."""

from app.imaging.phash import hamming_distance, phash
from app.imaging.pipeline import (
    RenderResult,
    SourceAnalysis,
    analyse_source,
    render_variant,
    render_variant_with_guarantee,
)
from app.imaging.recipes import VariantRecipe, build_recipe

__all__ = [
    "RenderResult",
    "SourceAnalysis",
    "VariantRecipe",
    "analyse_source",
    "build_recipe",
    "hamming_distance",
    "phash",
    "render_variant",
    "render_variant_with_guarantee",
]
