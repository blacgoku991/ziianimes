# Ziia — préparation et publication d'annonces multi-comptes

Outil destiné aux revendeurs de vêtements d'occasion qui gèrent plusieurs
comptes marketplace, un par niche.

**État : étape 1 livrée.** Espaces de travail, articles, photos sources et
pipeline de variantes avec prévisualisation avant/après. **Aucune
publication automatique n'est implémentée à ce stade** — c'est délibéré, et
c'est l'ordre de développement retenu.

À lire avant tout : [`docs/REVUE_SPEC.md`](docs/REVUE_SPEC.md) — les points
de la spécification qui me paraissent fragiles, dont trois à trancher avant
les étapes 4 et 5.

---

## Démarrage rapide

```bash
cp .env.example .env          # renseigner JWT_SECRET et ENCRYPTION_KEY
docker compose up --build
```

- API : http://localhost:8000 — documentation interactive sur `/docs`
- Interface : http://localhost:3000

### Sans Docker

```bash
make install          # environnement Python + dépendances
createdb ziia
make migrate          # migrations Alembic
make api              # http://localhost:8000
make worker           # worker d'imagerie (autre terminal)

cd frontend && npm install && npm run dev
```

Clé de chiffrement au repos :

```bash
python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

## Tests

```bash
make test       # 100 tests sur SQLite — ~30 s, aucun service externe
make test-pg    # même suite sur PostgreSQL, migrations Alembic comprises
make lint
```

Les deux cibles passent. La suite Postgres applique réellement
`alembic upgrade head` : le schéma testé est celui qui sera déployé.

## Ce qui est couvert par les tests

| Domaine | Ce qui est vérifié |
|---|---|
| Pipeline photo | **Un seul encodage** (compté), pas de bord noir après rotation, EXIF supprimé, bornes de qualité tenues même en escalade, rendu reproductible depuis une recette stockée |
| Écart perceptuel | Distance de Hamming ≥ 10/64 avec la source, ≥ 8 entre variantes sœurs, stabilité du pHash sous recompression |
| Isolation | Accès croisé refusé sur articles, photos, variantes et fichiers ; jeton média lié à son objet ; en-tête d'espace de travail non cru sur parole |
| Authentification | Rotation des jetons, détection de rejeu, réinitialisation non rejouable, absence d'oracle d'existence de comptes |
| Métier | Import idempotent, référence unique par espace, suppression logique, ordre des photos, régénération, acceptation/refus |

## Structure

```
backend/
  app/
    core/        configuration, sécurité, chiffrement, journalisation
    db/          moteur, types portables, base déclarative
    models/      23 tables — identité, catalogue, marketplace, référentiels
    imaging/     ops, recettes, fonds, segmentation, pHash, pipeline
    storage/     interface objet + implémentations locale et S3/R2
    services/    logique métier, toujours filtrée par espace de travail
    api/v1/      auth, articles, photos, variantes
    workers/     Celery — file `imaging`
  alembic/       migration initiale
  tests/         100 tests
frontend/        Next.js 15, TypeScript, Tailwind
docs/            REVUE_SPEC.md, ARCHITECTURE.md
```

## Ce qui est fait, et ce qui ne l'est pas

**Étape 1 — fait**

- inscription, connexion, mot de passe oublié, jetons révocables
- espace de travail isolé, essai gratuit de 14 jours (colonnes posées)
- articles : référence, coût d'achat, marge cible, statut, suppression logique
- import de photos en pleine résolution, sans recompression, dédupliqué
- génération de 1 à 6 variantes par photo, en file d'attente ou en direct
- prévisualisation avant/après, régénération, acceptation, refus
- écart perceptuel mesuré, stocké et affiché

**Non implémenté volontairement**

- Stripe : les colonnes existent, l'intégration attend
- envoi d'e-mail : en développement, le lien de réinitialisation est
  journalisé, et uniquement en développement
- `rembg` : dépendance optionnelle (`pip install -e ".[segmentation]"`).
  Sans elle, le pipeline conserve le fond d'origine et le signale au lieu de
  faire croire à un détourage raté
- tout ce qui touche aux plateformes : étapes 2 à 6

## Position sur l'automatisation

L'automatisation des publications est contraire aux conditions
d'utilisation de certaines plateformes. Le risque de restriction de compte
est porté par l'utilisateur, et l'avertissement figure à l'inscription
(`workspaces.automation_notice_accepted_at`).

Ce que le produit ne fait pas et ne fera pas : créer des comptes
automatiquement, contourner un CAPTCHA, réceptionner des SMS jetables.
L'utilisateur rattache des comptes qu'il possède déjà. Le mode brouillon
reste disponible en permanence et constitue le comportement par défaut.
