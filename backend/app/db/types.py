"""Types de colonnes portables.

PostgreSQL est la cible de production ; SQLite sert à la suite de tests
rapide. On déclare donc des types natifs Postgres avec une variante
portable, plutôt que deux jeux de modèles qui divergeraient.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

#: `uuid` natif sur Postgres, `CHAR(32)` ailleurs.
UUIDType = sa.Uuid(as_uuid=True)

#: `jsonb` sur Postgres (indexable), `json` texte ailleurs.
JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


class UtcDateTime(sa.TypeDecorator):
    """Horodatage toujours conscient du fuseau, quel que soit le moteur.

    Postgres restitue un `timestamptz` avec son fuseau ; SQLite (et certains
    pilotes) renvoient un `datetime` naïf, ce qui fait exploser la moindre
    comparaison avec `datetime.now(timezone.utc)` — typiquement la
    vérification d'expiration d'un jeton. On normalise donc en UTC des deux
    côtés de la frontière plutôt que de parsemer le code de conversions.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


TimestampType = UtcDateTime()
