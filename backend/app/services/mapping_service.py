"""Rapprochement « sortie IA » → nœud exact de la plateforme.

Le morceau le plus différenciant, et celui où la tentation d'en faire trop
est la plus forte. L'ordre de résolution retenu va du plus fiable au moins
fiable, et s'arrête dès qu'une réponse sûre est trouvée :

1. **correspondance apprise pour cet espace de travail** — l'utilisateur a
   déjà tranché ce cas, sa décision fait autorité ;
2. **correspondance globale** entretenue par l'éditeur ;
3. **rapprochement lexical** sur le libellé et le chemin, avec un score
   explicite ;
4. **rien** — et on demande à l'utilisateur, dont le choix est mémorisé et
   remonte en (1) pour la fois suivante.

Pas d'embeddings à ce stade, volontairement : un revendeur couvre
l'essentiel de son volume avec quelques centaines de catégories, et une
table qui apprend des décisions de l'utilisateur les couvre plus vite et
plus sûrement qu'un rapprochement sémantique. Le point d'extension est
prévu (`SemanticMatcher`) pour la longue traîne, une fois les cas fréquents
absorbés.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import MappingSource, Platform
from app.models.referential import (
    BrandMapping,
    CategoryMapping,
    PlatformBrand,
    PlatformCategory,
    PlatformSize,
)

logger = get_logger(__name__)

#: En dessous, on ne propose rien plutôt qu'un mauvais rapprochement : une
#: annonce mal catégorisée est invisible, ce qui est pire qu'un choix demandé.
MIN_AUTO_SCORE = 0.55

#: Mots vides du domaine, ignorés dans le rapprochement.
_STOPWORDS = {
    "de",
    "du",
    "des",
    "le",
    "la",
    "les",
    "un",
    "une",
    "et",
    "en",
    "a",
    "au",
    "aux",
    "pour",
    "avec",
    "sans",
    "taille",
    "vetement",
    "vetements",
}

#: Synonymes courants : ce que dit l'IA (ou l'utilisateur) à gauche, ce que
#: la plateforme emploie à droite.
_SYNONYMS = {
    "sweat": {"sweat", "sweatshirt"},
    "sweatshirt": {"sweat", "sweatshirt"},
    "hoodie": {"sweat", "capuche", "sweatshirt"},
    "capuche": {"capuche", "sweat"},
    "pull": {"pull", "pullover", "tricot"},
    "tee": {"t", "shirt"},
    "tshirt": {"t", "shirt"},
    "jean": {"jean", "denim"},
    "blouson": {"blouson", "veste"},
    "doudoune": {"manteau", "veste"},
    "parka": {"manteau", "veste"},
    "basket": {"basket", "sneaker", "chaussure"},
    "sneaker": {"basket", "chaussure"},
    "chaussure": {"chaussure", "basket"},
    "chemisier": {"chemise", "blouse"},
    "blouse": {"blouse", "chemise"},
    "cardigan": {"gilet", "cardigan"},
    "jogging": {"survetement", "sport"},
    "survetement": {"survetement", "sport"},
    "short": {"short"},
    "sac": {"sac"},
    "casquette": {"casquette", "bonnet"},
    "bonnet": {"casquette", "bonnet"},
    "botte": {"botte"},
    "escarpin": {"escarpin"},
    "combinaison": {"combinaison"},
    "salopette": {"combinaison"},
    "chino": {"chino", "pantalon"},
    "legging": {"pantalon"},
    "polo": {"polo"},
    "debardeur": {"debardeur"},
    "maillot": {"maillot", "bain"},
    "blazer": {"blazer", "veste"},
    "manteau": {"manteau"},
    "veste": {"veste"},
}


def normalize(value: str | None) -> str:
    """Minuscules, sans accent ni ponctuation. Clé de rapprochement."""
    if not value:
        return ""
    stripped = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def singular(word: str) -> str:
    """Singularise grossièrement.

    Les référentiels sont au pluriel (« Robes », « Sweats »), les libellés
    produits par l'IA au singulier (« robe », « sweat »). Sans cette
    réduction, aucun des deux ne rencontre l'autre.
    """
    if len(word) > 3 and word.endswith(("s", "x")):
        return word[:-1]
    return word


def tokens(value: str | None) -> set[str]:
    return {singular(word) for word in normalize(value).split() if word and word not in _STOPWORDS}


def expand(words: set[str]) -> set[str]:
    """Ajoute les synonymes connus d'un ensemble de mots."""
    expanded = set(words)
    for word in words:
        expanded |= _SYNONYMS.get(word, set())
    joined = " ".join(sorted(words))
    expanded |= _SYNONYMS.get(joined, set())
    return expanded


@dataclass
class MatchCandidate:
    external_id: str
    label: str
    path: str
    score: float
    source: MappingSource

    def as_dict(self) -> dict:
        return {
            "external_id": self.external_id,
            "label": self.label,
            "path": self.path,
            "score": round(self.score, 3),
            "source": self.source.value,
        }


@dataclass
class MatchResult:
    """Résultat d'un rapprochement.

    `needs_user_choice` est la valeur importante : elle dit à l'interface
    qu'il faut poser la question plutôt que de publier une supposition.
    """

    best: MatchCandidate | None
    candidates: list[MatchCandidate]
    needs_user_choice: bool

    def as_dict(self) -> dict:
        return {
            "best": self.best.as_dict() if self.best else None,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "needs_user_choice": self.needs_user_choice,
        }


class SemanticMatcher(Protocol):
    """Point d'extension pour la longue traîne (embeddings).

    Non implémenté à ce stade — voir la note en tête de module.
    """

    def rank(self, query: str, candidates: list[PlatformCategory]) -> list[tuple[str, float]]: ...


# ---------------------------------------------------------------------------
# Catégories
# ---------------------------------------------------------------------------


def match_category(
    db: Session,
    *,
    workspace_id: uuid.UUID | None,
    platform: Platform,
    label: str,
    extra_context: str | None = None,
    limit: int = 5,
) -> MatchResult:
    """Rapproche un libellé d'une catégorie feuille de la plateforme."""
    key = normalize(label)
    if not key:
        return MatchResult(best=None, candidates=[], needs_user_choice=True)

    learned = _lookup_category_mapping(db, workspace_id=workspace_id, platform=platform, key=key)
    if learned is not None:
        category = db.execute(
            sa.select(PlatformCategory).where(
                PlatformCategory.platform == platform,
                PlatformCategory.external_id == learned.category_external_id,
            )
        ).scalar_one_or_none()
        if category is not None and category.is_active:
            learned.hit_count += 1
            candidate = MatchCandidate(
                external_id=category.external_id,
                label=category.name,
                path=category.path,
                score=1.0,
                source=learned.source,
            )
            return MatchResult(best=candidate, candidates=[candidate], needs_user_choice=False)

    leaves = (
        db.execute(
            sa.select(PlatformCategory).where(
                PlatformCategory.platform == platform,
                PlatformCategory.is_leaf.is_(True),
                PlatformCategory.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    direct_tokens = tokens(label) | tokens(extra_context)
    query_tokens = expand(direct_tokens)
    scored = [
        MatchCandidate(
            external_id=leaf.external_id,
            label=leaf.name,
            path=leaf.path,
            score=_score_category(query_tokens, direct_tokens, leaf),
            source=MappingSource.embedding,
        )
        for leaf in leaves
    ]
    scored = [candidate for candidate in scored if candidate.score > 0]
    scored.sort(key=lambda candidate: (-candidate.score, candidate.path))
    top = scored[:limit]
    best = top[0] if top else None
    needs_choice = best is None or best.score < MIN_AUTO_SCORE
    # Deux candidats au coude à coude sur « Sweatshirts » et « Sweats à
    # capuche » : la machine ne peut pas trancher, l'utilisateur si.
    if not needs_choice and len(top) > 1 and abs(top[0].score - top[1].score) < 0.05:
        needs_choice = True
    return MatchResult(best=best, candidates=top, needs_user_choice=needs_choice)


def _score_category(
    query_tokens: set[str], direct_tokens: set[str], leaf: PlatformCategory
) -> float:
    """Score dans [0, 1].

    Deux signaux, dans cet ordre :

    * le **rappel sur le nom de la feuille** — « sweat » doit désigner
      « Sweatshirts » même si la requête contient aussi la marque et la
      couleur, donc on mesure la couverture du nom, pas celle de la requête ;
    * le **genre** — « baskets homme » et « baskets enfant » ne mènent pas au
      même nœud, et se tromper de rayon rend l'annonce invisible. Un genre
      explicite dans la requête écarte donc fortement les autres rayons.
    """
    if not query_tokens:
        return 0.0
    name_tokens = expand(tokens(leaf.name))
    overlap = query_tokens & name_tokens
    if not overlap:
        return 0.0

    recall = len(overlap) / max(1, len(name_tokens))
    # Départage : un mot présent tel quel dans la requête vaut mieux qu'un
    # mot atteint par synonyme. Sans ça, « chino » et « pantalon » se valent,
    # et « sweat à capuche » ne se distingue pas de « sweatshirt ».
    direct = len(direct_tokens & name_tokens) / max(1, len(name_tokens))
    score = 0.85 * recall + 0.15 * direct

    segment = normalize(leaf.path.split(">")[0].strip())
    requested = _requested_segment(query_tokens)
    if requested:
        score *= 1.0 if segment == requested else 0.3
    elif segment == "enfants":
        # Sans mention d'âge, un vêtement adulte est bien plus probable.
        score *= 0.8
    return min(1.0, score)


#: Mots qui désignent un rayon, et le segment de référentiel correspondant.
_SEGMENT_WORDS = {
    "homme": "hommes",
    "masculin": "hommes",
    "femme": "femmes",
    "feminin": "femmes",
    "enfant": "enfants",
    "fille": "enfants",
    "garcon": "enfants",
    "bebe": "enfants",
    "junior": "enfants",
}


def _requested_segment(query_tokens: set[str]) -> str | None:
    for word in query_tokens:
        segment = _SEGMENT_WORDS.get(word)
        if segment:
            return segment
    return None


def _lookup_category_mapping(
    db: Session, *, workspace_id: uuid.UUID | None, platform: Platform, key: str
) -> CategoryMapping | None:
    """Surcharge locataire d'abord, correspondance globale ensuite."""
    if workspace_id is not None:
        row = db.execute(
            sa.select(CategoryMapping).where(
                CategoryMapping.workspace_id == workspace_id,
                CategoryMapping.platform == platform,
                CategoryMapping.source_key == key,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return db.execute(
        sa.select(CategoryMapping).where(
            CategoryMapping.workspace_id.is_(None),
            CategoryMapping.platform == platform,
            CategoryMapping.source_key == key,
        )
    ).scalar_one_or_none()


def remember_category_choice(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    platform: Platform,
    label: str,
    category_external_id: str,
) -> CategoryMapping:
    """Mémorise le choix de l'utilisateur — il ne sera plus jamais demandé."""
    key = normalize(label)
    existing = db.execute(
        sa.select(CategoryMapping).where(
            CategoryMapping.workspace_id == workspace_id,
            CategoryMapping.platform == platform,
            CategoryMapping.source_key == key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.category_external_id = category_external_id
        existing.source = MappingSource.manual
        existing.confidence = 1.0
        db.flush()
        return existing

    mapping = CategoryMapping(
        workspace_id=workspace_id,
        platform=platform,
        source_key=key,
        category_external_id=category_external_id,
        confidence=1.0,
        source=MappingSource.manual,
    )
    db.add(mapping)
    db.flush()
    return mapping


# ---------------------------------------------------------------------------
# Marques
# ---------------------------------------------------------------------------


def match_brand(
    db: Session,
    *,
    workspace_id: uuid.UUID | None,
    platform: Platform,
    label: str,
    limit: int = 5,
) -> MatchResult:
    """Rapproche une marque.

    Rappel structurant : on ne peut pas inventer de marque, elle doit
    exister dans la liste de la plateforme. D'où le repli explicite sur
    « Autre marque » quand il existe.
    """
    key = normalize(label)
    if not key:
        return MatchResult(best=None, candidates=[], needs_user_choice=True)

    learned = _lookup_brand_mapping(db, workspace_id=workspace_id, platform=platform, key=key)
    if learned is not None:
        brand = db.execute(
            sa.select(PlatformBrand).where(
                PlatformBrand.platform == platform,
                PlatformBrand.external_id == learned.brand_external_id,
            )
        ).scalar_one_or_none()
        if brand is not None:
            candidate = MatchCandidate(
                external_id=brand.external_id,
                label=brand.name,
                path=brand.name,
                score=1.0,
                source=learned.source,
            )
            return MatchResult(best=candidate, candidates=[candidate], needs_user_choice=False)

    exact = db.execute(
        sa.select(PlatformBrand).where(
            PlatformBrand.platform == platform,
            PlatformBrand.normalized_name == key,
            PlatformBrand.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if exact is not None:
        candidate = MatchCandidate(
            external_id=exact.external_id,
            label=exact.name,
            path=exact.name,
            score=1.0,
            source=MappingSource.imported,
        )
        return MatchResult(best=candidate, candidates=[candidate], needs_user_choice=False)

    brands = (
        db.execute(
            sa.select(PlatformBrand).where(
                PlatformBrand.platform == platform, PlatformBrand.is_active.is_(True)
            )
        )
        .scalars()
        .all()
    )
    scored = []
    for brand in brands:
        score = _string_similarity(key, brand.normalized_name)
        if score > 0.5:
            scored.append(
                MatchCandidate(
                    external_id=brand.external_id,
                    label=brand.name,
                    path=brand.name,
                    score=score,
                    source=MappingSource.embedding,
                )
            )
    scored.sort(key=lambda candidate: (-candidate.score, candidate.label))
    top = scored[:limit]
    best = top[0] if top else None
    return MatchResult(
        best=best,
        candidates=top,
        needs_user_choice=best is None or best.score < 0.85,
    )


def _lookup_brand_mapping(
    db: Session, *, workspace_id: uuid.UUID | None, platform: Platform, key: str
) -> BrandMapping | None:
    if workspace_id is not None:
        row = db.execute(
            sa.select(BrandMapping).where(
                BrandMapping.workspace_id == workspace_id,
                BrandMapping.platform == platform,
                BrandMapping.source_key == key,
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return db.execute(
        sa.select(BrandMapping).where(
            BrandMapping.workspace_id.is_(None),
            BrandMapping.platform == platform,
            BrandMapping.source_key == key,
        )
    ).scalar_one_or_none()


def remember_brand_choice(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    platform: Platform,
    label: str,
    brand_external_id: str,
) -> BrandMapping:
    key = normalize(label)
    existing = db.execute(
        sa.select(BrandMapping).where(
            BrandMapping.workspace_id == workspace_id,
            BrandMapping.platform == platform,
            BrandMapping.source_key == key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.brand_external_id = brand_external_id
        existing.source = MappingSource.manual
        existing.confidence = 1.0
        db.flush()
        return existing
    mapping = BrandMapping(
        workspace_id=workspace_id,
        platform=platform,
        source_key=key,
        brand_external_id=brand_external_id,
        confidence=1.0,
        source=MappingSource.manual,
    )
    db.add(mapping)
    db.flush()
    return mapping


def fallback_brand(db: Session, platform: Platform) -> PlatformBrand | None:
    """Marque de repli (« Autre marque ») quand rien ne correspond."""
    return (
        db.execute(
            sa.select(PlatformBrand).where(
                PlatformBrand.platform == platform,
                PlatformBrand.normalized_name.in_(["autre marque", "autre", "other"]),
            )
        )
        .scalars()
        .first()
    )


# ---------------------------------------------------------------------------
# Tailles
# ---------------------------------------------------------------------------


def match_size(
    db: Session, *, platform: Platform, category_external_id: str | None, label: str
) -> MatchResult:
    """Rapproche une taille **dans la grille de la catégorie**.

    Les grilles dépendent de la catégorie : « 38 » ne veut pas dire la même
    chose sur une robe et sur une paire de baskets. Chercher une taille sans
    connaître la catégorie est une erreur, et cette signature l'empêche.
    """
    key = normalize(label)
    if not key:
        return MatchResult(best=None, candidates=[], needs_user_choice=True)

    group = None
    if category_external_id:
        category = db.execute(
            sa.select(PlatformCategory).where(
                PlatformCategory.platform == platform,
                PlatformCategory.external_id == category_external_id,
            )
        ).scalar_one_or_none()
        group = category.size_group_external_id if category else None

    query = sa.select(PlatformSize).where(PlatformSize.platform == platform)
    if group:
        query = query.where(PlatformSize.size_group_external_id == group)
    sizes = db.execute(query).scalars().all()

    scored = []
    for size in sizes:
        # « S / 36 » doit accepter « s » comme « 36 ».
        parts = {part.strip() for part in size.normalized_name.split(" ") if part.strip()}
        if key in parts or key == size.normalized_name:
            score = 1.0
        else:
            score = _string_similarity(key, size.normalized_name)
        if score > 0.6:
            scored.append(
                MatchCandidate(
                    external_id=size.external_id,
                    label=size.name,
                    path=size.size_group_external_id or "",
                    score=score,
                    source=MappingSource.imported,
                )
            )
    scored.sort(key=lambda candidate: (-candidate.score, candidate.label))
    top = scored[:5]
    best = top[0] if top else None
    return MatchResult(
        best=best, candidates=top, needs_user_choice=best is None or best.score < 0.9
    )


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def _string_similarity(left: str, right: str) -> float:
    """Similarité par bigrammes (Sørensen-Dice), robuste aux fautes de frappe."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_grams = {left[i : i + 2] for i in range(len(left) - 1)} or {left}
    right_grams = {right[i : i + 2] for i in range(len(right) - 1)} or {right}
    overlap = len(left_grams & right_grams)
    return 2.0 * overlap / (len(left_grams) + len(right_grams))


def search_categories(
    db: Session, *, platform: Platform, query: str | None, limit: int = 50
) -> list[PlatformCategory]:
    statement = sa.select(PlatformCategory).where(
        PlatformCategory.platform == platform,
        PlatformCategory.is_active.is_(True),
        PlatformCategory.is_leaf.is_(True),
    )
    if query:
        pattern = f"%{normalize(query)}%"
        statement = statement.where(sa.func.lower(PlatformCategory.path).like(pattern))
    return list(db.execute(statement.order_by(PlatformCategory.path).limit(limit)).scalars().all())


def search_brands(
    db: Session, *, platform: Platform, query: str | None, limit: int = 50
) -> list[PlatformBrand]:
    statement = sa.select(PlatformBrand).where(
        PlatformBrand.platform == platform, PlatformBrand.is_active.is_(True)
    )
    if query:
        statement = statement.where(PlatformBrand.normalized_name.like(f"%{normalize(query)}%"))
    return list(db.execute(statement.order_by(PlatformBrand.name).limit(limit)).scalars().all())


def sizes_for_category(
    db: Session, *, platform: Platform, category_external_id: str
) -> list[PlatformSize]:
    category = db.execute(
        sa.select(PlatformCategory).where(
            PlatformCategory.platform == platform,
            PlatformCategory.external_id == category_external_id,
        )
    ).scalar_one_or_none()
    if category is None or not category.size_group_external_id:
        return []
    return list(
        db.execute(
            sa.select(PlatformSize)
            .where(
                PlatformSize.platform == platform,
                PlatformSize.size_group_external_id == category.size_group_external_id,
            )
            .order_by(PlatformSize.id)
        )
        .scalars()
        .all()
    )
