"""Connecteur Vinted — automatisation du formulaire `/items/new`.

Vinted n'a pas d'API publique : le connecteur pilote un navigateur. Cinq
décisions structurent ce fichier.

**Mode brouillon par défaut.** Le formulaire est rempli intégralement et
*volontairement pas soumis*. Voir `docs/REVUE_SPEC.md` §1.1 : Vinted n'a pas
de brouillon serveur, donc « l'utilisateur donne le dernier clic » ne peut
pas être pris au pied de la lettre. Ce que fait ce connecteur, c'est
préparer, capturer l'écran, et rendre la main. La soumission automatique
existe mais reste conditionnée à trois choses réunies : l'espace de travail
a accepté l'avertissement CGU, la publication est explicitement en mode
`autopublish`, et les sélecteurs ont été calibrés.

**Reprise idempotente.** Chaque étape franchie est enregistrée. Un rejeu
saute ce qui est déjà fait — en particulier l'envoi des photos, l'étape
longue et celle qui, rejouée, créerait des doublons.

**Aucune attente fixe.** On attend l'apparition d'un élément, jamais une
durée arbitraire : une photo lourde met plus longtemps qu'un `sleep(3)`.

**Marque validée par clic.** Remplir le champ marque sans cliquer dans le
menu laisse la valeur non validée et l'annonce part sans marque. Le
connecteur clique, puis vérifie.

**CAPTCHA = arrêt.** Sa détection interrompt le job et rend la main à
l'utilisateur. Le contourner est explicitement hors périmètre.
"""

from __future__ import annotations

import random
import time
from typing import Any

from app.connectors.base import (
    ConnectorError,
    PublishRequest,
    PublishResult,
    PublishStep,
    StepOutcome,
)
from app.connectors.vinted.selectors import CALIBRATED, SELECTOR_SET_VERSION, SELECTORS, Target
from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import Platform

logger = get_logger(__name__)

#: Correspondance état interne → libellé affiché par la plateforme.
CONDITION_LABELS = {
    "new_with_tags": "Neuf avec étiquette",
    "new_without_tags": "Neuf sans étiquette",
    "very_good": "Très bon état",
    "good": "Bon état",
    "fair": "Satisfaisant",
}


class VintedConnector:
    platform = Platform.vinted
    #: Faux tant que les sélecteurs n'ont pas été calibrés : c'est le
    #: garde-fou qui empêche un jeu non vérifié de soumettre une annonce.
    supports_autopublish = CALIBRATED

    def __init__(self, profile_dir: str, *, headless: bool | None = None) -> None:
        self.profile_dir = profile_dir
        self.headless = settings.playwright_headless if headless is None else headless
        self.timeout = settings.playwright_timeout_ms

    # -- Publication ------------------------------------------------------

    def publish(self, request: PublishRequest, credentials: dict) -> PublishResult:
        checkpoint = dict(request.checkpoint or {})
        try:
            return self._publish(request, credentials, checkpoint)
        except ConnectorError as exc:
            # La progression accomplie repart avec l'erreur : la reprise
            # sautera les étapes déjà franchies.
            exc.checkpoint = checkpoint
            raise

    def _publish(
        self, request: PublishRequest, credentials: dict, checkpoint: dict
    ) -> PublishResult:
        steps: list[StepOutcome] = []
        draft_only = request.draft_only or not self.supports_autopublish

        with self._browser(credentials) as page:
            self._guard_captcha(page)
            self._require_session(page)

            def run(step: PublishStep, action) -> None:  # type: ignore[no-untyped-def]
                if checkpoint.get(step.value):
                    steps.append(StepOutcome(step, ok=True, detail="déjà fait, ignoré"))
                    return
                detail = action()
                checkpoint[step.value] = True
                steps.append(StepOutcome(step, ok=True, detail=detail))
                # Cadence humaine entre deux actions du formulaire.
                self._pause()

            run(PublishStep.open_form, lambda: self._open_form(page))
            run(PublishStep.upload_photos, lambda: self._upload_photos(page, request.image_paths))
            run(
                PublishStep.fill_title,
                lambda: self._fill(page, SELECTORS.title_input, request.title),
            )
            run(
                PublishStep.fill_description,
                lambda: self._fill(page, SELECTORS.description_input, request.description),
            )
            run(
                PublishStep.select_category,
                lambda: self._select_category(page, request.category_external_id),
            )
            run(
                PublishStep.select_brand,
                lambda: self._select_brand(page, request.brand_external_id),
            )
            run(PublishStep.select_size, lambda: self._select_size(page, request.size_external_id))
            run(
                PublishStep.select_condition,
                lambda: self._select_from_menu(
                    page,
                    SELECTORS.condition_opener,
                    SELECTORS.condition_option,
                    CONDITION_LABELS.get(request.condition or "", ""),
                ),
            )
            run(
                PublishStep.select_colour,
                lambda: self._select_from_menu(
                    page, SELECTORS.colour_opener, SELECTORS.colour_option, request.colour or ""
                ),
            )
            run(
                PublishStep.select_material,
                lambda: self._select_from_menu(
                    page,
                    SELECTORS.material_opener,
                    SELECTORS.material_option,
                    request.material or "",
                ),
            )
            run(
                PublishStep.set_price,
                lambda: self._fill(
                    page,
                    SELECTORS.price_input,
                    f"{request.price_cents / 100:.2f}".replace(".", ","),
                ),
            )

            self._guard_captcha(page)
            error = self._read_error(page)
            if error:
                raise ConnectorError(f"formulaire refusé : {error}", retryable=False)

            if draft_only:
                # On s'arrête ici, volontairement. La capture donne à
                # l'utilisateur de quoi vérifier avant de valider lui-même.
                shot = self._screenshot(page)
                steps.append(
                    StepOutcome(PublishStep.review, ok=True, detail="brouillon prêt", data=shot)
                )
                return PublishResult(
                    ok=True,
                    draft_ready=True,
                    steps=steps,
                    checkpoint=checkpoint,
                    remote_url=page.url,
                )

            run(PublishStep.submit, lambda: self._submit(page))
            listing_id, url = self._read_created_listing(page)
            return PublishResult(
                ok=True,
                draft_ready=False,
                remote_listing_id=listing_id,
                remote_url=url,
                steps=steps,
                checkpoint=checkpoint,
            )

    # -- Étapes -----------------------------------------------------------

    def _open_form(self, page: Any) -> str:
        page.goto(SELECTORS.new_item_url, wait_until="domcontentloaded", timeout=self.timeout)
        self._locate(page, SELECTORS.photo_input).wait_for(state="attached", timeout=self.timeout)
        return SELECTORS.new_item_url

    def _upload_photos(self, page: Any, image_paths: list[str]) -> str:
        if not image_paths:
            raise ConnectorError("aucune image à envoyer", retryable=False)
        # set_input_files : on passe les fichiers directement à l'input,
        # sans simuler de glisser-déposer, qui est fragile et détectable.
        self._locate(page, SELECTORS.photo_input).set_input_files(image_paths)

        # On attend que le serveur ait confirmé chaque vignette. Pas de délai
        # fixe : une photo de 8 Mo ne monte pas à la même vitesse qu'une de 800 Ko.
        thumbnails = self._locate(page, SELECTORS.photo_thumbnail)
        deadline = time.monotonic() + self.timeout / 1000 * 2
        while time.monotonic() < deadline:
            if thumbnails.count() >= len(image_paths):
                return f"{len(image_paths)} photo(s) confirmée(s)"
            page.wait_for_timeout(500)
        raise ConnectorError(
            f"vignettes incomplètes : {thumbnails.count()}/{len(image_paths)}", retryable=True
        )

    def _fill(self, page: Any, target: Target, value: str) -> str:
        if not value:
            return "vide, ignoré"
        locator = self._locate(page, target)
        locator.click()
        locator.fill(value)
        return f"{len(value)} caractère(s)"

    def _select_category(self, page: Any, category_path: str | None) -> str:
        """Descend la cascade de catégories, niveau par niveau.

        `category_path` est le chemin lisible de la plateforme
        (« Hommes > Vêtements > Sweats et pull-overs > Sweatshirts ») : c'est
        lui qui pilote les clics, parce que l'identifiant interne n'est pas
        exposé dans le DOM.
        """
        if not category_path:
            raise ConnectorError("catégorie non résolue", retryable=False)
        self._locate(page, SELECTORS.category_opener).click()
        for level in [part.strip() for part in category_path.split(">") if part.strip()]:
            option = page.locator(
                f"{SELECTORS.category_option.candidates[0]}:has-text('{level}')"
            ).first
            option.wait_for(state="visible", timeout=self.timeout)
            option.click()
            self._pause(0.2, 0.6)
        return category_path

    def _select_brand(self, page: Any, brand_name: str | None) -> str:
        if not brand_name:
            return "aucune marque"
        field = self._locate(page, SELECTORS.brand_input)
        field.click()
        field.fill(brand_name)
        option = page.locator(
            f"{SELECTORS.brand_option.candidates[0]}:has-text('{brand_name}')"
        ).first
        try:
            option.wait_for(state="visible", timeout=self.timeout)
            option.click()
        except Exception as exc:
            # Sans clic, la marque n'est pas validée : l'annonce partirait
            # sans, ce qui la rend quasi introuvable.
            raise ConnectorError(
                f"marque « {brand_name} » absente de la liste de la plateforme",
                retryable=False,
            ) from exc
        return brand_name

    def _select_size(self, page: Any, size_name: str | None) -> str:
        return self._select_from_menu(
            page, SELECTORS.size_opener, SELECTORS.size_option, size_name or ""
        )

    def _select_from_menu(self, page: Any, opener: Target, option: Target, label: str) -> str:
        if not label:
            return "vide, ignoré"
        try:
            self._locate(page, opener).click()
            choice = page.locator(f"{option.candidates[0]}:has-text('{label}')").first
            choice.wait_for(state="visible", timeout=self.timeout)
            choice.click()
            return label
        except Exception as exc:
            if opener.required:
                raise ConnectorError(f"« {label} » introuvable dans {opener.name}") from exc
            return f"optionnel, non renseigné ({label})"

    def _submit(self, page: Any) -> str:
        self._locate(page, SELECTORS.submit_button).click()
        page.wait_for_load_state("networkidle", timeout=self.timeout)
        error = self._read_error(page)
        if error:
            raise ConnectorError(f"soumission refusée : {error}", retryable=False)
        return "soumis"

    def _read_created_listing(self, page: Any) -> tuple[str | None, str]:
        url = page.url
        listing_id = None
        if "/items/" in url:
            tail = url.rsplit("/items/", 1)[-1]
            listing_id = tail.split("-")[0].split("?")[0] or None
        return listing_id, url

    def _read_error(self, page: Any) -> str | None:
        try:
            banner = self._locate(page, SELECTORS.error_banner)
            if banner.count() and banner.first.is_visible():
                return (banner.first.inner_text() or "").strip()[:300]
        except Exception:
            return None
        return None

    def _guard_captcha(self, page: Any) -> None:
        try:
            marker = self._locate(page, SELECTORS.captcha_marker)
            present = marker.count() > 0
        except Exception:
            present = False
        if present:
            # On ne tente rien : ni résolution, ni contournement. Le job
            # s'arrête et l'utilisateur reprend la main sur son compte.
            raise ConnectorError(
                "un contrôle anti-robot est apparu — reprenez la main sur ce compte "
                "depuis votre navigateur",
                retryable=False,
                needs_reauth=True,
            )

    def _require_session(self, page: Any) -> None:
        probe = self._locate(page, SELECTORS.logged_in_probe)
        try:
            probe.first.wait_for(state="attached", timeout=5000)
        except Exception as exc:
            raise ConnectorError(
                "session expirée : reconnectez ce compte", retryable=False, needs_reauth=True
            ) from exc

    def _screenshot(self, page: Any) -> dict:
        try:
            import base64

            raw = page.screenshot(full_page=True)
            return {"screenshot_b64": base64.b64encode(raw).decode("ascii")}
        except Exception:
            return {}

    # -- Autres opérations ------------------------------------------------

    def unpublish(self, remote_listing_id: str, credentials: dict) -> bool:
        with self._browser(credentials) as page:
            page.goto(
                f"https://www.vinted.fr/items/{remote_listing_id}",
                wait_until="domcontentloaded",
                timeout=self.timeout,
            )
            hide = page.locator(
                "[data-testid='item-hide-button'], button:has-text('Masquer')"
            ).first
            hide.wait_for(state="visible", timeout=self.timeout)
            hide.click()
            page.wait_for_load_state("networkidle", timeout=self.timeout)
            return True

    def update_price(self, remote_listing_id: str, price_cents: int, credentials: dict) -> bool:
        with self._browser(credentials) as page:
            page.goto(
                f"https://www.vinted.fr/items/{remote_listing_id}/edit",
                wait_until="domcontentloaded",
                timeout=self.timeout,
            )
            self._fill(page, SELECTORS.price_input, f"{price_cents / 100:.2f}".replace(".", ","))
            self._locate(page, SELECTORS.submit_button).click()
            page.wait_for_load_state("networkidle", timeout=self.timeout)
            return True

    def fetch_status(self, remote_listing_id: str, credentials: dict) -> dict:
        with self._browser(credentials) as page:
            page.goto(
                f"https://www.vinted.fr/items/{remote_listing_id}",
                wait_until="domcontentloaded",
                timeout=self.timeout,
            )
            body = page.content().lower()
            return {
                "sold": "vendu" in body or "sold" in body,
                "views_count": 0,
                "checked_url": page.url,
            }

    def health_check(self, credentials: dict) -> tuple[bool, str]:
        """Contrôle quotidien : la session tient-elle, le formulaire est-il intact ?

        Le contrôle va jusqu'à ouvrir le formulaire et vérifier la présence
        de chaque cible obligatoire — c'est ce qui permet d'alerter le jour
        où la plateforme change son DOM, et non trois semaines plus tard en
        découvrant que rien ne part.
        """
        missing: list[str] = []
        try:
            with self._browser(credentials) as page:
                self._require_session(page)
                self._open_form(page)
                for target in SELECTORS.all_targets():
                    if not target.required:
                        continue
                    try:
                        if self._locate(page, target).count() == 0:
                            missing.append(target.name)
                    except Exception:
                        missing.append(target.name)
        except ConnectorError as exc:
            return False, exc.message
        except Exception as exc:
            return False, f"contrôle impossible : {exc}"

        if missing:
            return False, (f"cibles introuvables ({SELECTOR_SET_VERSION}) : {', '.join(missing)}")
        return True, f"formulaire conforme ({SELECTOR_SET_VERSION})"

    def fetch_messages(self, credentials: dict, since: str | None = None) -> list[dict]:  # noqa: ARG002
        with self._browser(credentials) as page:
            page.goto(
                "https://www.vinted.fr/inbox", wait_until="domcontentloaded", timeout=self.timeout
            )
            threads = []
            rows = page.locator("[data-testid='conversation-item'], a[href*='/inbox/']")
            for index in range(min(rows.count(), 50)):
                row = rows.nth(index)
                href = row.get_attribute("href") or ""
                threads.append(
                    {
                        "remote_thread_id": href.rstrip("/").rsplit("/", 1)[-1],
                        "counterparty_name": (row.inner_text() or "").split("\n")[0][:120],
                        "preview": (row.inner_text() or "")[:400],
                    }
                )
            return threads

    # -- Navigateur -------------------------------------------------------

    def _browser(self, credentials: dict):  # type: ignore[no-untyped-def]
        return _BrowserSession(
            profile_dir=self.profile_dir,
            credentials=credentials,
            headless=self.headless,
            timeout=self.timeout,
        )

    def _locate(self, page: Any, target: Target):  # type: ignore[no-untyped-def]
        """Premier sélecteur candidat qui trouve quelque chose.

        Le repli est ce qui permet de survivre à une refonte partielle du
        formulaire sans redéploiement.
        """
        last = None
        for candidate in target.candidates:
            locator = page.locator(candidate)
            last = locator
            try:
                if locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        if target.required and last is not None:
            return last.first
        if last is None:
            raise ConnectorError(f"aucun sélecteur pour {target.name}", retryable=False)
        return last.first

    def _pause(self, low: float | None = None, high: float | None = None) -> None:
        """Délai aléatoire entre deux actions.

        Un formulaire rempli en 400 ms n'est pas un comportement humain.
        """
        low = low if low is not None else 0.4
        high = high if high is not None else 1.4
        time.sleep(random.uniform(low, high))


class _BrowserSession:
    """Contexte navigateur persistant, strictement propre à un compte."""

    def __init__(
        self, *, profile_dir: str, credentials: dict, headless: bool, timeout: int
    ) -> None:
        self.profile_dir = profile_dir
        self.credentials = credentials or {}
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._context = None

    def __enter__(self):  # type: ignore[no-untyped-def]
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        # Contexte persistant par compte : cookies, stockage local et cache
        # ne sont jamais partagés entre deux comptes.
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context.set_default_timeout(self.timeout)

        cookies = self.credentials.get("cookies")
        if cookies:
            try:
                self._context.add_cookies(cookies)
            except Exception as exc:
                logger.warning("cookie_injection_failed", error=str(exc))

        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return page

    def __exit__(self, *exc_info: object) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
