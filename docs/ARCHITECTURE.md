# Architecture

## Vue d'ensemble

```
Next.js  ──HTTP──▶  FastAPI  ──▶  PostgreSQL
                       │
                       ├──▶  S3 / R2 / disque   (photos sources, variantes)
                       │
                       └──▶  Redis ──▶  worker imagerie   (Celery, conteneur séparé)
                                   └──▶  worker publication (Playwright, conteneur dédié)
                                   └──▶  ordonnanceur (synchro ventes, relances, santé)
```

Les workers ne partagent avec l'API que la base et le stockage objet. Un
rendu lourd — ou plus tard un navigateur qui tombe — ne dégrade jamais les
temps de réponse de l'API.

## Isolation multi-locataire

Un espace de travail (`workspaces`) est la frontière d'isolation. Toute
table métier porte un `workspace_id` non nul et indexé, qui entre dans les
contraintes d'unicité composées (`uq_articles_workspace_id_sku` : deux
revendeurs peuvent utiliser la même référence article).

Trois règles tenues par le code :

1. aucune lecture d'entité sans filtre sur `workspace_id` — `app/services/scoping.py`
   fournit les accesseurs, les services les utilisent systématiquement ;
2. une entité absente **de cet espace** renvoie `404`, jamais `403` : un 403
   confirmerait son existence ailleurs ;
3. l'appartenance est revérifiée en base à chaque requête
   (`app/api/deps.py`), jamais déduite du contenu du jeton — qui pourrait
   être antérieur à un retrait d'accès.

Douze tests couvrent spécifiquement ces frontières (`tests/test_tenancy.py`).

## Authentification

- mots de passe hachés en **argon2** ;
- accès par JWT court (30 min), rafraîchissement long (30 j) **révocable** :
  seule l'empreinte du jeton est stockée ;
- rotation stricte au rafraîchissement. Rejouer un jeton déjà consommé est
  traité comme un vol : toutes les sessions de l'utilisateur sont révoquées,
  et cette révocation est validée explicitement en base parce que la requête
  se termine ensuite par une erreur ;
- jetons média séparés (`scope: media`), liés à un objet précis, valables
  15 minutes, et explicitement refusés comme moyen d'authentification
  générale. C'est ce qui permet à une balise `<img>` d'afficher une photo
  privée sans cookie ni CSRF.

## Pipeline photo

L'invariant central :

```
décodage → (segmentation) → géométrie → composition → colorimétrie
        → mise à l'échelle → UN SEUL ENCODAGE
```

Tout se passe en `float32` RGB dans `[0, 1]` entre le décodage et
l'encodage. Aucun JPEG intermédiaire, donc aucune accumulation d'artefacts.
Un test compte les appels à `PIL.Image.Image.save` et échoue s'il y en a
plus d'un — y compris sur le chemin avec détourage et recomposition.

Autres garde-fous :

| Point | Traitement |
|---|---|
| Rotation | Recadrage au plus grand rectangle inscrit → aucun bord noir ni répliqué |
| Recadrage | Plafonné à 50 % par axe, sinon le vêtement est coupé |
| Amplitudes | Bornées dans `recipes.py`, pas chez l'appelant : même en escalade, 3° et 10 % maximum |
| Sortie | JPEG 93, chroma 4:4:4, EXIF supprimé, sRGB |
| Agrandissement | Seulement si autorisé — gonfler une source de 600 px donne une image molle |
| Reproductibilité | La recette est sérialisée en base : un rendu se rejoue à l'octet près |

**Garantie d'écart.** Après rendu, la distance de Hamming entre l'empreinte
perceptuelle de la variante et celle de la source est mesurée. Si elle est
sous le seuil, le pipeline rejoue avec une recette plus marquée (dans les
bornes). Après épuisement des tentatives, la meilleure variante est renvoyée
avec sa distance réelle — stockée et affichée à l'écran, jamais masquée.

Une vérification symétrique existe entre variantes sœurs
(`variant_service.py`) : deux déclinaisons d'une même photo destinées à deux
comptes ne doivent pas se ressembler entre elles non plus.

## Stockage

Interface unique (`app/storage/base.py`), deux implémentations : disque local
(écriture atomique, protection contre l'échappement de chemin) et S3/R2
(objets privés, URL présignées). Les clés sont préfixées par l'espace de
travail, ce qui permet une politique de bucket par locataire.

L'API sert les fichiers elle-même en local, et redirige vers une URL
présignée en S3 : dans les deux cas, l'autorisation est vérifiée avant que le
moindre octet ne circule.

## Tâches asynchrones

Un job = une variante. `render_variant_row` est idempotent : sans `force`,
une variante déjà rendue n'est pas refaite, donc un rejeu après incident ne
produit ni doublon de fichier ni double consommation CPU. Les tâches ne sont
émises qu'**après** le commit de la transaction, sinon le worker peut lire
une ligne qui n'existe pas encore.

## Base de données

23 tables posées dans une seule révision Alembic. Le périmètre dépasse
l'étape 1 volontairement : la forme du modèle et les invariants
(idempotence, unicité article/compte, journal d'événements) sont
structurants, mieux vaut les figer avant d'écrire le premier connecteur.

Choix notables :

- **UUID** en clés primaires : les identifiants circulent dans les URL, un
  entier séquentiel exposerait le volume d'activité ;
- **énumérations en `VARCHAR + CHECK`** plutôt qu'en type ENUM natif :
  ajouter une valeur ne demande alors qu'un remplacement de contrainte, pas
  un `ALTER TYPE` non transactionnel ;
- **horodatages normalisés en UTC** par un `TypeDecorator`, des deux côtés
  de la frontière — sinon SQLite renvoie des dates naïves et toute
  comparaison d'expiration de jeton casse ;
- **convention de nommage des contraintes** : Alembic peut supprimer une
  contrainte par son nom, ce qui est impossible avec les noms auto-générés
  par Postgres ;
- **suppression logique des articles** : une annonce distante survit à la
  suppression locale, il faut garder de quoi la dépublier.

## Journalisation

`structlog` en JSON, avec un processeur de censure qui remplace les clés
sensibles (mots de passe, cookies, jetons, sessions) avant sérialisation.
Chaque ligne porte un `request_id` propagé en en-tête de réponse.

---

## Étapes 2 à 6 — décisions structurantes

### Couche IA remplaçable

`app/ai/` expose un contrat (`AiProvider`) et deux implémentations : Claude,
et un bouchon déterministe hors ligne. Sans clé d'API, le produit reste
entièrement utilisable et le dit dans les journaux, plutôt que d'échouer sur
une erreur d'authentification incompréhensible côté utilisateur. Toute la
suite de tests tourne sans réseau.

Deux règles de coût, dictées par le volume visé (50 à 200 articles par mois
et par revendeur) : **une requête par article**, pas une par photo ; **une
requête pour toutes les variantes de texte**, ce qui évite de repayer
l'analyse et permet au modèle de rendre les variantes réellement
différentes puisqu'il les voit toutes.

### Rapprochement de catégories : apprendre plutôt que deviner

Ordre de résolution, du plus fiable au moins fiable : choix mémorisé pour
cet espace de travail → correspondance globale → rapprochement lexical
scoré → **demander à l'utilisateur**. Le dernier cas n'est pas un échec :
une annonce mal rangée est invisible, ce qui est pire qu'une question.

Pas d'embeddings, volontairement. Le rapprochement lexical gère la
singularisation (les référentiels sont au pluriel, l'IA parle au singulier),
les synonymes du domaine, et surtout le **genre** — « baskets homme » et
« baskets enfant » ne mènent pas au même rayon, et se tromper de rayon rend
l'annonce introuvable. Sur les cas courants, 11 sur 14 sont résolus
automatiquement ; les 3 restants sont de vraies ambiguïtés, et le choix de
l'utilisateur est mémorisé pour ne plus jamais être demandé.

### Argent : tout passe par le net

`app/services/fees.py` modélise commissions, frais d'encaissement et port à
la charge du vendeur. Le tableau de bord, le prix conseillé, le prix
plancher et les baisses programmées consomment tous `compute_margin`. Un
prix moins un coût d'achat n'est pas une marge, et une marge fausse oriente
les décisions d'achat dans le mauvais sens.

### Publication : les garde-fous d'abord

| Garde-fou | Mise en œuvre |
|---|---|
| Une publication à la fois par compte | `UPDATE ... WHERE last_action_at <= seuil` — un seul `UPDATE`, donc atomique. Un `SELECT` puis `UPDATE` laisserait deux workers passer |
| Délais entre actions | Aléatoire entre 45 et 180 s, plus une pause entre chaque champ du formulaire |
| Plafond quotidien | 40 actions par compte, réinitialisé à minuit |
| Doublon inter-comptes | Refusé, pas seulement signalé — c'est un des signaux les plus nets de rapprochement de comptes |
| Brouillon par défaut | La publication automatique exige l'acceptation explicite de l'avertissement CGU, sinon elle est rétrogradée |
| CAPTCHA | Détecté, le job s'arrête et rend la main. Aucune tentative de contournement |

### Reprise idempotente

Chaque étape franchie est écrite dans `publications.checkpoint`. Un échec
transporte la progression accomplie (`ConnectorError.checkpoint`) : la
reprise saute l'envoi des photos, l'étape longue et celle qui, rejouée,
créerait des doublons côté plateforme.

### Vente : ce qui est annulé

À la vente, **toutes** les autres publications de l'article sont retirées —
y compris celles simplement en attente en file. Une publication en attente
est aussi dangereuse qu'une publication en ligne : sans annulation, elle
part *après* la vente. Le runner refuse par ailleurs d'exécuter une
publication passée à `unpublished` entre-temps.

La **survente** — deux acheteurs pour une pièce unique entre deux
synchronisations — est détectée et signalée (`oversold: true`, journal en
erreur) plutôt que masquée. Elle ne peut pas être évitée techniquement ;
c'est un arbitrage produit, documenté dans `docs/REVUE_SPEC.md` §1.2.

### Connecteurs : ne pas propager la fragilité de Vinted

Vinted est fragile parce qu'il n'a pas d'API, pas parce que c'est une
fatalité. eBay, Depop et Leboncoin héritent d'`ApiConnector` : pas de
sélecteur, pas de DOM, une gestion d'erreurs typée (réessayable, définitif,
reconnexion nécessaire) et la limitation de débit traitée comme un cas
normal.

Le contrôle de santé quotidien ouvre réellement le formulaire Vinted et
vérifie chaque cible obligatoire. C'est ce qui permet d'être prévenu le jour
où la plateforme change son DOM, au lieu de le découvrir trois semaines plus
tard en constatant que rien ne part.
