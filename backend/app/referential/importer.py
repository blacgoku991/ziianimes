"""Chargement et rafraîchissement des référentiels plateformes.

Les référentiels bougent : catégories renommées, marques ajoutées, grilles
de tailles remaniées. L'import est donc **idempotent et différentiel** —
on met à jour ce qui a changé, on désactive ce qui a disparu, on ne
supprime rien. Une catégorie retirée du référentiel doit rester lisible :
des publications passées y font référence.

Le jeu livré (`seed/vinted.json`) permet de faire tourner le rapprochement
dès l'installation. Il n'est pas une copie du référentiel réel et ses
identifiants sont locaux : avant toute publication, il faut brancher une
`ReferentialSource` qui récupère les vrais identifiants de la plateforme.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import Platform
from app.models.referential import PlatformBrand, PlatformCategory, PlatformSize
from app.services.mapping_service import normalize

logger = get_logger(__name__)

SEED_DIR = Path(__file__).parent / "seed"


class ReferentialSource(Protocol):
    """Source de référentiel pour une plateforme.

    L'implémentation par fichier est fournie ; une implémentation réseau
    (API officielle pour eBay/Depop, récupération outillée pour Vinted) se
    branche ici sans toucher au reste.
    """

    platform: Platform

    def fetch(self) -> dict: ...


class SeedFileSource:
    """Source de fichier — jeu de départ livré avec l'application."""

    def __init__(self, platform: Platform, path: Path | None = None) -> None:
        self.platform = platform
        self.path = path or SEED_DIR / f"{platform.value}.json"

    def fetch(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))


class ImportReport:
    def __init__(self) -> None:
        self.categories_created = 0
        self.categories_updated = 0
        self.categories_deactivated = 0
        self.brands_created = 0
        self.brands_updated = 0
        self.sizes_created = 0
        self.sizes_updated = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def import_referential(db: Session, source: ReferentialSource) -> ImportReport:
    payload = source.fetch()
    platform = source.platform
    now = datetime.now(UTC)
    report = ImportReport()

    if payload.get("platform") and payload["platform"] != platform.value:
        raise ValueError(
            f"le référentiel annonce « {payload['platform']} », importé pour « {platform.value} »"
        )

    _import_categories(db, platform, payload.get("categories", []), now, report)
    _import_brands(db, platform, payload.get("brands", []), now, report)
    _import_sizes(db, platform, payload.get("sizes", []), now, report)
    db.flush()

    logger.info("referential_imported", platform=platform.value, **report.as_dict())
    return report


def _import_categories(
    db: Session, platform: Platform, rows: list[dict], now: datetime, report: ImportReport
) -> None:
    existing = {
        row.external_id: row
        for row in db.execute(
            sa.select(PlatformCategory).where(PlatformCategory.platform == platform)
        )
        .scalars()
        .all()
    }
    seen: set[str] = set()

    for row in rows:
        external_id = str(row["external_id"])
        seen.add(external_id)
        current = existing.get(external_id)
        values = {
            "parent_external_id": row.get("parent_external_id"),
            "name": row["name"],
            "path": row["path"],
            "level": int(row.get("level", 0)),
            "is_leaf": bool(row.get("is_leaf", False)),
            "size_group_external_id": row.get("size_group_external_id"),
            "raw": row,
            "fetched_at": now,
            "is_active": True,
        }
        if current is None:
            db.add(PlatformCategory(platform=platform, external_id=external_id, **values))
            report.categories_created += 1
        else:
            changed = any(getattr(current, key) != value for key, value in values.items())
            for key, value in values.items():
                setattr(current, key, value)
            if changed:
                report.categories_updated += 1

    # Désactivation, pas suppression : des publications pointent dessus.
    for external_id, row in existing.items():
        if external_id not in seen and row.is_active:
            row.is_active = False
            report.categories_deactivated += 1


def _import_brands(
    db: Session, platform: Platform, rows: list[dict], now: datetime, report: ImportReport
) -> None:
    existing = {
        row.external_id: row
        for row in db.execute(sa.select(PlatformBrand).where(PlatformBrand.platform == platform))
        .scalars()
        .all()
    }
    for row in rows:
        external_id = str(row["external_id"])
        name = row["name"]
        normalized = row.get("normalized_name") or normalize(name)
        current = existing.get(external_id)
        if current is None:
            db.add(
                PlatformBrand(
                    platform=platform,
                    external_id=external_id,
                    name=name,
                    normalized_name=normalized,
                    fetched_at=now,
                    is_active=True,
                )
            )
            report.brands_created += 1
        else:
            if (current.name, current.normalized_name) != (name, normalized):
                report.brands_updated += 1
            current.name, current.normalized_name = name, normalized
            current.fetched_at, current.is_active = now, True


def _import_sizes(
    db: Session, platform: Platform, rows: list[dict], now: datetime, report: ImportReport
) -> None:
    existing = {
        row.external_id: row
        for row in db.execute(sa.select(PlatformSize).where(PlatformSize.platform == platform))
        .scalars()
        .all()
    }
    for row in rows:
        external_id = str(row["external_id"])
        name = row["name"]
        normalized = row.get("normalized_name") or normalize(name)
        group = row.get("size_group_external_id")
        current = existing.get(external_id)
        if current is None:
            db.add(
                PlatformSize(
                    platform=platform,
                    external_id=external_id,
                    size_group_external_id=group,
                    name=name,
                    normalized_name=normalized,
                    fetched_at=now,
                )
            )
            report.sizes_created += 1
        else:
            if (current.name, current.size_group_external_id) != (name, group):
                report.sizes_updated += 1
            current.name, current.normalized_name = name, normalized
            current.size_group_external_id, current.fetched_at = group, now


def import_all_seeds(db: Session) -> dict[str, dict[str, int]]:
    """Charge tous les référentiels livrés. Sûr à rejouer."""
    reports: dict[str, dict[str, int]] = {}
    for path in sorted(SEED_DIR.glob("*.json")):
        try:
            platform = Platform(path.stem)
        except ValueError:
            logger.warning("seed_ignored", file=path.name)
            continue
        reports[platform.value] = import_referential(db, SeedFileSource(platform, path)).as_dict()
    return reports
