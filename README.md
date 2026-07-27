# Ziia — préparation et publication d'annonces multi-comptes

Outil pour revendeurs de vêtements d'occasion qui gèrent plusieurs comptes
marketplace, un par niche.

**Les six étapes sont livrées.** 152 tests, verts sur SQLite comme sur
PostgreSQL avec les migrations réellement appliquées.

Deux documents à lire avant de mettre en production :

- [`docs/REVUE_SPEC.md`](docs/REVUE_SPEC.md) — ce qui me paraît fragile dans
  la spécification, dont trois points à trancher ;
- [`docs/MISE_EN_PRODUCTION.md`](docs/MISE_EN_PRODUCTION.md) — ce qui reste à
  faire avant de publier sur un vrai compte, en particulier **la calibration
  des sélecteurs Vinted**, qui n'a pas pu être faite ici.

---

## Installation

**Prérequis : Docker Desktop installé et démarré.** Sous Windows,
vérifiez que la baleine est présente dans la barre des tâches avant de
lancer quoi que ce soit ; sans cela `docker compose` échoue avec un message
sur un « pipe introuvable ».

### Windows (PowerShell)

```powershell
git clone https://github.com/blacgoku991/ziianimes.git
cd ziianimes
git checkout claude/reseller-saas-multicompte-bzilc7

powershell -ExecutionPolicy Bypass -File .\scripts\setup-env.ps1
docker compose up --build
```

Le script crée `.env` et y génère les deux secrets — pas besoin de Python
installé. Rejouer le script ne réécrit pas un secret déjà renseigné :
changer `ENCRYPTION_KEY` rendrait illisibles les sessions marketplace déjà
enregistrées.

### Linux / macOS

```bash
git clone https://github.com/blacgoku991/ziianimes.git
cd ziianimes
git checkout claude/reseller-saas-multicompte-bzilc7

bash scripts/setup-env.sh
docker compose up --build
```

### Premier démarrage : comptez du temps

L'image du worker de publication embarque un navigateur : plus d'un
gigaoctet à télécharger. Pour avoir l'interface tout de suite, démarrez
d'abord le nécessaire, et ajoutez les workers ensuite :

```bash
docker compose up --build db redis api frontend
# puis, dans un autre terminal :
docker compose up --build worker-imaging worker-publish beat
```

Sans `worker-imaging`, la génération de variantes reste en attente : cochez
« synchrone » dans l'interface pour la déclencher directement pendant vos
essais.

- Interface : <http://localhost:3000>
- API et documentation interactive : <http://localhost:8000/docs>

Le premier démarrage applique les migrations et charge les référentiels
plateformes. Créez votre compte sur `/register`, puis suivez le parcours :
**Articles → photos → variantes → analyse → prix → Comptes → publier**.

Sans clé `ANTHROPIC_API_KEY`, l'analyse et la rédaction basculent sur un
fournisseur déterministe hors ligne : tout le produit reste utilisable, les
textes sont simplement plus pauvres.

### Sans Docker

```bash
make install                       # environnement Python + dépendances
createdb ziia && make migrate && make seed
make api                           # http://localhost:8000
make worker                        # worker d'imagerie      (autre terminal)
make worker-publish                # worker de publication  (autre terminal)
make beat                          # ordonnanceur           (autre terminal)

cd frontend && npm install && npm run dev
```

## Commandes

| Commande | Effet |
|---|---|
| `make test` | 152 tests sur SQLite — ~60 s, aucun service externe |
| `make test-pg` | même suite sur PostgreSQL, migrations comprises |
| `make lint` | analyse statique (ruff) |
| `make migrate` / `make revision m="…"` | migrations Alembic |
| `make seed` | recharge les référentiels (idempotent) |
| `make calibrate-vinted id=<account_id>` | **vérifie les sélecteurs Vinted** — obligatoire avant toute publication réelle |
| `make up` / `make down` / `make logs` | pile Docker complète |

## Ce qui est livré, étape par étape

**1 — Fondations.** Inscription, connexion, mot de passe oublié, jetons
révocables. Espace de travail isolé. Articles avec coût d'achat et marge
cible. Import de photos en pleine résolution, jamais recompressées.
Génération de variantes avec prévisualisation avant/après, régénération,
acceptation, refus.

**2 — Intelligence.** Analyse vision des photos, génération de N textes
distincts (un par compte cible), ton paramétrable par niche. Référentiels
catégories / marques / tailles avec import différentiel. Rapprochement qui
apprend des décisions de l'utilisateur. Prix conseillé avec fourchette,
marge nette et plancher.

**3 — Stock.** Tableau avec statut par plateforme, filtres, recherche,
capital immobilisé, détection des invendus et baisse suggérée.

**4 — Connecteurs.** Rattachement de comptes existants, secrets chiffrés au
repos, écran de santé. Connecteur Vinted (Playwright) en mode brouillon,
connecteurs eBay / Depop / Leboncoin sur API officielle. Contrôle de santé
quotidien qui teste le formulaire.

**5 — Passage à l'échelle.** File de publication, une à la fois par compte,
délais aléatoires, plafond quotidien, reprise idempotente, dépublication
croisée à la vente, relances et baisses de prix par paliers.

**6 — Confort.** Boîte de réception unifiée avec détection des offres et
réponses rapides. Tableau de bord : CA, marge **nette de frais**, délai
moyen de vente, performance par niche, marques les plus rentables.

## Les garanties vérifiées par les tests

| Domaine | Ce qui est vérifié |
|---|---|
| Pipeline photo | **Un seul encodage** (compté), pas de bord noir après rotation, EXIF supprimé, bornes de qualité tenues même en escalade, rendu reproductible depuis une recette stockée |
| Écart perceptuel | ≥ 10/64 avec la source, ≥ 8 entre variantes sœurs, stabilité du pHash sous recompression |
| Isolation | Accès croisé refusé sur articles, photos, variantes, fichiers, comptes, correspondances et tableau de bord |
| Secrets | Chiffré non rejouable d'une ligne à l'autre, jamais renvoyé par l'API, effacé quand la session expire |
| Publication | Brouillon par défaut, doublon inter-comptes refusé, cadence et plafond quotidien, reprise sans réenvoi des photos, session expirée → reconnexion |
| Vente | Dépublication croisée y compris des publications **en attente**, survente détectée, retour remis en stock |
| Argent | Marge nette après commissions, prix cible cohérent, baisse de prix jamais sous le plancher |

## Où le produit s'arrête volontairement

- **Il ne crée aucun compte marketplace**, ne contourne aucun CAPTCHA, ne
  réceptionne aucun SMS. L'utilisateur rattache des comptes qu'il possède.
- **Le mode brouillon est le comportement par défaut** et le reste tant que
  l'avertissement CGU n'a pas été accepté explicitement.
- **La soumission automatique sur Vinted est désactivée** tant que les
  sélecteurs n'ont pas été calibrés (`CALIBRATED = False`).
- **Un CAPTCHA arrête le job** et rend la main à l'utilisateur.

L'automatisation des publications est contraire aux conditions
d'utilisation de certaines plateformes. Le risque de restriction de compte
est porté par l'utilisateur, et l'avertissement figure à l'inscription.

## Structure

```
backend/
  app/
    core/         configuration, sécurité, chiffrement, journalisation
    db/           moteur, types portables, base déclarative
    models/       23 tables — identité, catalogue, marketplace, référentiels
    imaging/      ops, recettes, fonds, segmentation, pHash, pipeline
    ai/           fournisseur Claude + bouchon hors ligne
    referential/  import des catégories, marques et tailles
    connectors/   contrat commun, Vinted (Playwright), eBay/Depop/Leboncoin
    storage/      interface objet + local et S3/R2
    services/     métier, toujours filtré par espace de travail
    api/v1/       61 routes
    workers/      Celery — files `imaging` et `publish`, ordonnanceur
  alembic/        2 migrations
  scripts/        calibration Vinted, chargement des référentiels
  tests/          152 tests
frontend/         Next.js 15 — articles, stock, comptes, messages, bilan
docs/             REVUE_SPEC.md, ARCHITECTURE.md, MISE_EN_PRODUCTION.md
```
