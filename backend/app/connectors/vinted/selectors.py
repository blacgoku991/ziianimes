"""Sélecteurs du formulaire Vinted — **fichier de calibration**.

⚠️ À LIRE AVANT LA PREMIÈRE PUBLICATION RÉELLE ⚠️

Les valeurs ci-dessous n'ont **pas** été validées contre le site réel : cet
environnement de développement n'a ni compte Vinted ni accès au site. Elles
décrivent la forme attendue du formulaire et permettent de faire tourner et
de tester toute la machinerie ; elles doivent être vérifiées et corrigées
une fois devant le vrai `/items/new`, avant d'activer un compte en
production.

Marche à suivre pour calibrer, en une passe :

    make calibrate-vinted     # ouvre le formulaire dans un navigateur visible
                              # et affiche, pour chaque étape, le sélecteur
                              # trouvé ou manquant

Deux règles tenues ici, et qui expliquent la structure :

1. **jamais de classe CSS générée.** `.sc-a1b2c3` change à chaque
   déploiement de la plateforme. On vise, dans l'ordre : `data-testid`,
   attribut `name`, rôle ARIA, texte visible ;
2. **plusieurs candidats par cible.** Les sélecteurs sont des listes
   essayées dans l'ordre, ce qui permet de survivre à une refonte partielle
   sans redéployer — et au test de santé quotidien de dire précisément
   lequel a cessé de fonctionner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Incrémenter à chaque calibration : la version est journalisée avec chaque
#: publication, ce qui permet de corréler une vague d'échecs à un changement
#: de formulaire.
SELECTOR_SET_VERSION = "2026-07-uncalibrated"

#: Tant que ce drapeau est faux, le connecteur refuse la soumission
#: automatique et se limite au mode brouillon. C'est le garde-fou qui évite
#: qu'un jeu de sélecteurs non vérifié parte en production.
CALIBRATED = False


@dataclass(frozen=True)
class Target:
    """Une cible du formulaire et ses sélecteurs candidats."""

    name: str
    candidates: tuple[str, ...]
    required: bool = True
    #: Description lisible, affichée par l'outil de calibration.
    note: str = ""


@dataclass(frozen=True)
class VintedSelectors:
    new_item_url: str = "https://www.vinted.fr/items/new"
    logged_in_probe: Target = field(
        default_factory=lambda: Target(
            "logged_in_probe",
            (
                "[data-testid='header-user-menu']",
                "[data-testid='user-menu-button']",
                "header a[href*='/member/']",
            ),
            note="Présence = session valide. Absence = reconnexion nécessaire.",
        )
    )
    photo_input: Target = field(
        default_factory=lambda: Target(
            "photo_input",
            (
                "input[type='file'][data-testid='photo-uploader']",
                "input[type='file'][name='photos']",
                "input[type='file']",
            ),
            note="Cible de set_input_files. Ne jamais simuler un glisser-déposer.",
        )
    )
    photo_thumbnail: Target = field(
        default_factory=lambda: Target(
            "photo_thumbnail",
            (
                "[data-testid='photo-thumbnail']",
                "[data-testid^='item-photo']",
                "figure img[src*='vinted']",
            ),
            note=(
                "Vignette confirmée côté serveur. On attend son apparition — "
                "jamais un délai fixe : une photo lourde met plus longtemps."
            ),
        )
    )
    title_input: Target = field(
        default_factory=lambda: Target(
            "title_input",
            ("[data-testid='title-input'] input", "input[name='title']", "#title"),
        )
    )
    description_input: Target = field(
        default_factory=lambda: Target(
            "description_input",
            (
                "[data-testid='description-input'] textarea",
                "textarea[name='description']",
                "#description",
            ),
        )
    )
    category_opener: Target = field(
        default_factory=lambda: Target(
            "category_opener",
            ("[data-testid='catalog-select-input']", "[data-testid='category-select']"),
            note="Ouvre la cascade de catégories.",
        )
    )
    category_option: Target = field(
        default_factory=lambda: Target(
            "category_option",
            ("[data-testid='catalog-option']", "[role='option']", "li[role='menuitem']"),
            note="Un niveau de la cascade. Filtré par texte visible au clic.",
        )
    )
    brand_input: Target = field(
        default_factory=lambda: Target(
            "brand_input",
            ("[data-testid='brand-select-input'] input", "input[name='brand']"),
        )
    )
    brand_option: Target = field(
        default_factory=lambda: Target(
            "brand_option",
            ("[data-testid='brand-option']", "[role='option']"),
            note=(
                "IMPÉRATIF : cliquer l'option du menu. Remplir le champ sans "
                "cliquer laisse la marque non validée et l'annonce part sans."
            ),
        )
    )
    size_opener: Target = field(
        default_factory=lambda: Target(
            "size_opener", ("[data-testid='size-select-input']", "[data-testid='size-select']")
        )
    )
    size_option: Target = field(
        default_factory=lambda: Target(
            "size_option", ("[data-testid='size-option']", "[role='option']")
        )
    )
    condition_opener: Target = field(
        default_factory=lambda: Target(
            "condition_opener",
            ("[data-testid='status-select-input']", "[data-testid='condition-select']"),
        )
    )
    condition_option: Target = field(
        default_factory=lambda: Target(
            "condition_option", ("[data-testid='status-option']", "[role='option']")
        )
    )
    colour_opener: Target = field(
        default_factory=lambda: Target(
            "colour_opener", ("[data-testid='color-select-input']",), required=False
        )
    )
    colour_option: Target = field(
        default_factory=lambda: Target(
            "colour_option", ("[data-testid='color-option']", "[role='option']"), required=False
        )
    )
    material_opener: Target = field(
        default_factory=lambda: Target(
            "material_opener", ("[data-testid='material-select-input']",), required=False
        )
    )
    material_option: Target = field(
        default_factory=lambda: Target(
            "material_option",
            ("[data-testid='material-option']", "[role='option']"),
            required=False,
        )
    )
    price_input: Target = field(
        default_factory=lambda: Target(
            "price_input", ("[data-testid='price-input'] input", "input[name='price']")
        )
    )
    submit_button: Target = field(
        default_factory=lambda: Target(
            "submit_button",
            ("[data-testid='upload-form-save-button']", "button[type='submit']"),
            note="Cliqué uniquement hors mode brouillon.",
        )
    )
    error_banner: Target = field(
        default_factory=lambda: Target(
            "error_banner",
            ("[data-testid='form-error']", "[role='alert']"),
            required=False,
            note="Message de refus côté plateforme, remonté tel quel à l'utilisateur.",
        )
    )
    captcha_marker: Target = field(
        default_factory=lambda: Target(
            "captcha_marker",
            ("iframe[src*='captcha']", "iframe[title*='captcha']", "[data-testid='captcha']"),
            required=False,
            note=(
                "Détection seulement. Un CAPTCHA arrête le job et rend la main "
                "à l'utilisateur : le contourner est hors périmètre du produit."
            ),
        )
    )

    def all_targets(self) -> list[Target]:
        return [value for value in self.__dict__.values() if isinstance(value, Target)]


SELECTORS = VintedSelectors()
