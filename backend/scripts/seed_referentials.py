"""Charge les référentiels plateformes livrés.

Exécuté à chaque démarrage de l'API : l'import est différentiel et
idempotent, le rejouer ne crée pas de doublon et met simplement à jour ce
qui a changé.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import session_scope  # noqa: E402
from app.referential.importer import import_all_seeds  # noqa: E402

if __name__ == "__main__":
    with session_scope() as db:
        report = import_all_seeds(db)
    for platform, counts in report.items():
        print(f"{platform}: {counts}")
