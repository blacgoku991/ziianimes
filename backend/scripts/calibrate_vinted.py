"""Calibration des sélecteurs Vinted.

Ouvre le formulaire `/items/new` dans un navigateur **visible**, avec la
session d'un compte rattaché, et rapporte pour chaque cible le sélecteur qui
fonctionne — ou l'absence de tout candidat valide.

    make calibrate-vinted id=<account_id>

C'est l'étape à faire avant d'activer un compte en production : les
sélecteurs livrés décrivent la forme attendue du formulaire, ils n'ont pas
été vérifiés contre le site réel. Tant que `CALIBRATED` vaut `False`, le
connecteur refuse toute soumission automatique.
"""

from __future__ import annotations

import contextlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.vinted.selectors import (  # noqa: E402
    SELECTOR_SET_VERSION,
    SELECTORS,
)
from app.db.session import session_scope  # noqa: E402
from app.models.marketplace import MarketplaceAccount  # noqa: E402
from app.services import account_service  # noqa: E402


def main(account_id: str) -> int:
    from playwright.sync_api import sync_playwright

    with session_scope() as db:
        account = db.get(MarketplaceAccount, uuid.UUID(account_id))
        if account is None:
            print(f"Compte {account_id} introuvable.")
            return 1
        credentials = account_service.load_credentials(
            account=account, workspace_id=account.workspace_id
        )
        profile = str(account_service.browser_profile_dir(account))
        label = account.label

    if credentials is None:
        print(f"Le compte « {label} » n'a pas d'identifiants enregistrés.")
        return 1

    print(f"Compte            : {label}")
    print(f"Jeu de sélecteurs : {SELECTOR_SET_VERSION}")
    print(f"Profil navigateur : {profile}\n")

    found: list[str] = []
    missing: list[str] = []

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile, headless=False, locale="fr-FR"
        )
        try:
            if credentials.get("cookies"):
                context.add_cookies(credentials["cookies"])
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(SELECTORS.new_item_url, wait_until="domcontentloaded")
            # Le formulaire se construit côté client : on lui laisse le temps
            # de se monter avant d'inspecter le DOM.
            page.wait_for_timeout(5000)

            for target in SELECTORS.all_targets():
                hit = None
                for candidate in target.candidates:
                    with contextlib.suppress(Exception):
                        if page.locator(candidate).count() > 0:
                            hit = candidate
                            break

                if hit:
                    found.append(target.name)
                    marker = "OK"
                elif target.required:
                    missing.append(target.name)
                    marker = "MANQUE"
                else:
                    marker = "absent"

                print(f"[{marker:6s}] {target.name:22s} {hit or '— aucun candidat'}")
                if target.note and not hit:
                    print(f"           {target.note}")

            print("\nFenêtre laissée ouverte pour inspecter le DOM (Ctrl+C pour finir).")
            with contextlib.suppress(KeyboardInterrupt):
                page.wait_for_timeout(600_000)
        finally:
            context.close()

    print(f"\n{len(found)} cible(s) trouvée(s), {len(missing)} obligatoire(s) manquante(s).")
    if missing:
        print("Corrigez app/connectors/vinted/selectors.py, incrémentez")
        print("SELECTOR_SET_VERSION, puis passez CALIBRATED à True.")
        return 2
    print("Vous pouvez passer CALIBRATED à True dans selectors.py.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1]))
