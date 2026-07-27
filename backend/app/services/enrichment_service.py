"""Étape 2 — enrichissement d'un article par l'IA.

Le service ne remplace jamais une saisie de l'utilisateur : il complète les
champs restés vides et propose des textes. Un revendeur qui a corrigé la
marque à la main ne doit pas la voir écrasée au prochain passage — c'est le
genre de détail qui fait abandonner un outil.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.ai import ToneProfile, VisionAnalysis, get_ai_provider
from app.core.config import settings
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.models.catalog import Article, ArticlePhoto
from app.models.enums import ArticleCondition
from app.models.referential import AiGeneration
from app.services import photo_service
from app.storage import ObjectNotFound

logger = get_logger(__name__)

#: Champs que l'analyse peut renseigner, uniquement s'ils sont vides.
_FILLABLE = ("brand", "color", "material", "size_label", "category_label")


def analyse_article(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article: Article,
    hint: str | None = None,
    overwrite: bool = False,
) -> VisionAnalysis:
    """Analyse les photos d'un article et complète ses caractéristiques."""
    photos = photo_service.list_photos(db, workspace_id=workspace_id, article_id=article.id)
    if not photos:
        raise ValidationError("aucune photo à analyser sur cet article")

    images = _load_images(photos[: settings.ai_max_photos_per_analysis])
    if not images:
        raise ValidationError("les fichiers des photos sont introuvables")

    provider = get_ai_provider()
    analysis = provider.analyse_photos(images, hint=hint)

    _apply_to_article(article, analysis, overwrite=overwrite)
    _record_usage(
        db,
        workspace_id=workspace_id,
        article_id=article.id,
        kind="vision_analysis",
        usage=analysis.usage,
        result=analysis.to_dict(),
    )
    db.flush()
    logger.info(
        "article_analysed",
        article_id=str(article.id),
        garment=analysis.garment_type,
        brand_confidence=analysis.brand_confidence,
    )
    return analysis


def _load_images(photos: list[ArticlePhoto]) -> list[bytes]:
    images: list[bytes] = []
    for photo in photos:
        try:
            images.append(photo_service.read_photo_bytes(photo))
        except ObjectNotFound:
            logger.warning("photo_file_missing", photo_id=str(photo.id))
    return images


def _apply_to_article(article: Article, analysis: VisionAnalysis, *, overwrite: bool) -> None:
    values = {
        "brand": analysis.brand,
        "color": analysis.color,
        "material": analysis.material,
        "size_label": analysis.size_label,
        "category_label": analysis.garment_type,
    }
    for field in _FILLABLE:
        proposed = values.get(field)
        if not proposed:
            continue
        # Une marque devinée sans certitude n'écrase rien : mieux vaut un
        # champ vide qu'une marque fausse, qui fait retirer l'annonce.
        if field == "brand" and analysis.brand_confidence < 0.6:
            continue
        if overwrite or not getattr(article, field):
            setattr(article, field, proposed)

    if analysis.condition and (overwrite or article.condition is None):
        try:
            article.condition = ArticleCondition(analysis.condition)
        except ValueError:
            logger.warning("unknown_condition", value=analysis.condition)

    attributes = dict(article.attributes or {})
    attributes["ai"] = analysis.to_dict()
    attributes["ai_analysed_at"] = datetime.now(UTC).isoformat()
    # Conséquence directe sur le pipeline photo : un logo visible interdit le
    # miroir horizontal, qui l'inverserait.
    attributes["allow_mirror"] = not analysis.has_visible_logo_or_text
    article.attributes = attributes


def generate_listing_copy(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article: Article,
    variant_count: int = 3,
    niche: str | None = None,
) -> list[dict]:
    """Produit N jeux de textes distincts pour un même article."""
    if variant_count < 1 or variant_count > 8:
        raise ValidationError("entre 1 et 8 variantes de texte")

    stored = (article.attributes or {}).get("ai")
    analysis = (
        VisionAnalysis(**{k: v for k, v in stored.items() if k in VisionAnalysis.__annotations__})
        if stored
        else VisionAnalysis(
            garment_type=article.category_label,
            brand=article.brand,
            color=article.color,
            material=article.material,
            size_label=article.size_label,
            condition=article.condition.value if article.condition else None,
        )
    )

    tone = ToneProfile.for_niche(niche)
    batch = get_ai_provider().write_listing(
        analysis,
        tone=tone,
        variant_count=variant_count,
        brand=article.brand,
        size_label=article.size_label,
    )

    copies = [variant.to_dict() for variant in batch.variants]
    attributes = dict(article.attributes or {})
    attributes["copy_variants"] = copies
    attributes["copy_tone"] = tone.key
    article.attributes = attributes

    # Le titre et la description de l'article prennent la première variante
    # si l'utilisateur n'a rien saisi ; les suivantes sont réservées aux
    # autres comptes.
    if copies and not article.title:
        article.title = copies[0]["title"][:255]
    if copies and not article.description:
        article.description = copies[0]["description"]

    _record_usage(
        db,
        workspace_id=workspace_id,
        article_id=article.id,
        kind="listing_copy",
        usage=batch.usage,
        result={"variant_count": len(copies), "tone": tone.key},
    )
    db.flush()
    return copies


def take_copy_variant(article: Article, index: int) -> dict | None:
    """Renvoie le jeu de textes destiné à la n-ième publication.

    Si l'IA a produit moins de variantes que de comptes cibles, on ne
    recycle pas la première : on renvoie `None` et l'appelant retombe sur
    les champs de l'article, ce qui reste préférable à deux annonces
    strictement identiques sur deux comptes.
    """
    variants = (article.attributes or {}).get("copy_variants") or []
    if 0 <= index < len(variants):
        return variants[index]
    return None


def _record_usage(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    article_id: uuid.UUID | None,
    kind: str,
    usage: object,
    result: dict,
) -> None:
    """Trace le coût : c'est le vrai coût variable du produit."""
    db.add(
        AiGeneration(
            workspace_id=workspace_id,
            article_id=article_id,
            kind=kind,
            model=getattr(usage, "model", "inconnu"),
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cost_micros=usage.cost_micros(  # type: ignore[union-attr]
                input_per_mtok=settings.ai_input_price_per_mtok,
                output_per_mtok=settings.ai_output_price_per_mtok,
            ),
            latency_ms=getattr(usage, "latency_ms", 0),
            result=result,
        )
    )


def workspace_ai_cost_micros(db: Session, workspace_id: uuid.UUID, *, since: datetime) -> int:
    total = db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(AiGeneration.cost_micros), 0)).where(
            AiGeneration.workspace_id == workspace_id, AiGeneration.created_at >= since
        )
    ).scalar_one()
    return int(total)
