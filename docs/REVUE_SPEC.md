# Revue de la spécification — ce qui me paraît fragile

Document demandé avant de coder. Il ne remet pas en cause le produit : la
plupart des choix sont bons, notamment le modèle « un article, N
publications », le mode brouillon par défaut et la publication en file
d'attente. Ce qui suit liste ce qui me semble fragile, mal dimensionné ou
absent, classé par gravité.

---

## 1. Points bloquants — à trancher avant l'étape concernée

### 1.1 « Mode brouillon » sur Vinted : deux produits différents sous un seul mot

> « Mode brouillon : tout est rempli, l'utilisateur donne le dernier clic de
> validation. Doit être l'option par défaut. »

C'est le bon principe, mais sur Vinted il n'a pas d'implémentation évidente.
Le formulaire `/items/new` n'a pas de brouillon serveur qu'on remplirait
côté worker et que l'utilisateur retrouverait ensuite dans son navigateur.
Un formulaire rempli par Playwright vit dans le contexte navigateur du
worker, et nulle part ailleurs. Il n'y a donc que trois façons de tenir la
promesse :

- **(a) navigateur piloté à distance** — le worker ouvre la session, remplit,
  et on diffuse l'écran à l'utilisateur pour son clic final. Techniquement
  lourd (streaming, latence, sessions longues), mais c'est le seul « dernier
  clic » littéral ;
- **(b) préparation locale + soumission automatique** — l'utilisateur valide
  dans *notre* interface, et le worker fait tout, y compris le clic. C'est
  simple, mais ce n'est plus un brouillon : c'est de la publication
  automatique avec confirmation préalable ;
- **(c) assistance manuelle** — on prépare textes, prix, catégories et
  variantes, et l'utilisateur copie-colle. Sans risque, mais on ne supprime
  que la moitié du travail.

**À décider avant l'étape 4**, parce que ce choix détermine l'architecture du
worker, le modèle de risque et l'argument commercial. Mon avis : (b) par
défaut avec un écran de récapitulatif sérieux, et (c) toujours accessible en
repli. (a) est une impasse d'ingénierie pour une équipe de cette taille.

### 1.2 Survente : deux acheteurs, un seul vêtement

> « Quand une publication passe à "vendu" → dépublication automatique de
> toutes les autres publications du même article »

La détection de la vente passe par un sondage périodique de chaque compte.
Entre deux sondages, rien n'empêche deux acheteurs d'acheter le même
vêtement physique sur deux plateformes. La spécification ne dit rien de ce
cas, qui n'est pas théorique : c'est le mode d'échec normal du produit dès
que le stock est unitaire — et il l'est, en friperie.

Conséquences concrètes pour le vendeur : annulation, remboursement, et sur
Vinted une dégradation de la note vendeur. Le produit doit donc :

- exposer un état explicite (`reserved`) et une procédure de réconciliation ;
- laisser configurer une stratégie « une plateforme à la fois » pour les
  pièces uniques, plutôt que de traiter la publication tous azimuts comme
  l'objectif ;
- afficher honnêtement la fenêtre d'exposition (« vos annonces sont
  synchronisées toutes les N minutes »).

Le schéma prévoit `ArticleStatus.reserved` et le journal `publication_events`
pour ça ; la logique reste à écrire à l'étape 5.

### 1.3 Le prix conseillé s'appuie sur une donnée qui n'existe pas

> « Recherche d'articles comparables **vendus** (marque + catégorie + état) »

Vinted n'expose pas publiquement les prix de vente. Ce qui est visible, ce
sont des prix **demandés** sur des annonces actives. Estimer un prix de vente
à partir de prix demandés donne un biais systématique vers le haut — et un
outil qui conseille des prix trop élevés fait mécaniquement baisser le taux
de rotation de ses utilisateurs, c'est-à-dire exactement l'inverse du
service rendu.

Deux options honnêtes :

- annoncer une « fourchette des prix demandés » et le dire ainsi dans
  l'interface ;
- construire l'estimation sur **l'historique de ventes de l'utilisateur**,
  que le produit accumule de toute façon. C'est plus lent à démarrer, mais
  c'est la seule donnée de vente réelle à laquelle on ait accès, et elle
  devient un actif propre au produit.

---

## 2. Le pipeline photo — bon design, mauvaise justification

Le pipeline demandé est techniquement solide et je l'ai implémenté tel quel
(passe d'encodage unique, travail en pleine résolution, bornes de qualité).
Trois réserves, dont une correspond à un défaut réel dans la spécification.

### 2.1 Le miroir horizontal casse les logos — défaut corrigé

> « Variations géométriques légères : miroir horizontal […] »

Le miroir est la transformation la plus rentable sur une empreinte
perceptuelle, et c'est aussi celle qui **inverse les logos et les textes**.
Un swoosh Nike retourné, une étiquette illisible, un imprimé en miroir : ça
se voit immédiatement et ça décrédibilise l'annonce. Sur les niches
streetwear et sport — deux des quatre citées en exemple — c'est un défaut
direct.

Implémenté : le miroir reste actif par défaut (sans danger sur un vêtement
uni) mais devient débrayable par `VARIANT_ALLOW_MIRROR`, et le désactiver ne
décale aucun autre paramètre de la recette (test dédié). La suite logique, à
l'étape 2, est de le couper automatiquement quand l'analyse vision détecte
du texte ou un logo.

### 2.2 La variation de photo n'est pas ce qui relie les comptes entre eux

La spécification présente le pipeline comme la parade au rapprochement de
comptes. C'est très optimiste. Les plateformes disposent de signaux
nettement plus forts qu'un hash d'image : adresse IP, empreinte de
navigateur, cookies, coordonnées bancaires, adresse d'expédition, numéro de
téléphone. Un revendeur avec cinq comptes Vinted, un seul RIB et une seule
adresse de domicile est rapprochable quoi qu'il arrive côté photos.

Ce n'est pas une raison d'abandonner le pipeline — c'en est une de le
**positionner autrement**. Sa valeur réelle et défendable est :

- des visuels propres (fond neutre, cadrage cohérent) sans passer par
  Photoshop ;
- une déclinaison par plateforme sans perte de qualité ;
- pas de fichier strictement identique republié tel quel, ce qui est une
  hygiène de base, pas une technique d'évasion.

Le vendre comme un dispositif de contournement, c'est promettre ce que le
produit ne peut pas tenir, et c'est aussi ce qui l'exposerait juridiquement.

### 2.3 « Sans dégradation perceptible » : relatif à quoi ?

La source est presque toujours déjà un JPEG de téléphone. « Sans perte
perceptible » se mesure donc par rapport à ce fichier-là, pas à un capteur
brut. Et surtout : **la plateforme réencode à la réception**. Toute stratégie
qui reposerait sur des micro-différences de compression est annulée à
l'envoi.

C'est un argument en faveur du design retenu : les tests vérifient que le
pHash est stable sous recompression (distance ≤ 2), ce qui prouve que seules
les transformations **géométriques** survivent au réencodage de la
plateforme. C'est aussi pourquoi la garantie d'écart porte sur une distance
de Hamming mesurée, stockée et affichée, plutôt que sur une promesse.

### 2.4 `rembg` sur du vêtement : ne pas l'appliquer les yeux fermés

U²-Net s'en sort bien sur un vêtement posé à plat ou sur cintre, et mal sur
la dentelle, les franges, les bretelles fines, les tissus transparents et les
motifs très contrastés. Le remplacement systématique de fond produira, sur
une fraction non négligeable des photos, une annonce **moins bonne** que
l'originale.

Implémenté en conséquence : la segmentation est optionnelle, l'échec est
silencieux mais **signalé** (`background_replaced = false` affiché dans
l'interface), et rien n'est publié sans que l'utilisateur ait vu la variante.

---

## 3. Sous-estimations d'effort

### 3.1 Les référentiels de catégories sont le vrai gros morceau

La spécification le pressent (« le plus difficile et le plus différenciant »)
mais sous-estime encore. Aucune API publique : constituer l'arbre Vinted
suppose de le récupérer par des moyens qui posent eux-mêmes la question des
CGU, et la structure change. Les grilles de tailles dépendent de la
catégorie, la marque doit exister dans **leur** liste — on ne peut pas en
inventer une, il faut gérer le repli « marque non listée ».

Sur l'approche : les embeddings sont sur-dimensionnés pour commencer. Un
revendeur couvre 95 % de son volume avec quelques centaines de catégories.
Une table de correspondance entretenue à la main, plus la mémorisation des
choix de l'utilisateur, ira plus loin et plus vite qu'un rapprochement
sémantique — qui se justifie sur la longue traîne, une fois les cas fréquents
couverts. Le schéma prévoit exactement ça : `CategoryMapping` avec
`workspace_id` nul pour le global, non nul pour la surcharge locataire, et
`hit_count` pour identifier ce qui mérite d'entrer dans la table globale.

### 3.2 Le chiffrement au repos ne couvre pas la fenêtre d'exposition réelle

Chiffrer les sessions en base est nécessaire et fait (AES-256-GCM, données
authentifiées liées au propriétaire du secret). Mais une session doit être
**déchiffrée** pour être injectée dans un profil navigateur : l'exposition
réelle, c'est le disque et la mémoire du conteneur worker pendant le job, pas
la table Postgres.

À prévoir à l'étape 4 : profils navigateur éphémères en `tmpfs`, effacés en
fin de job, conteneurs jamais capturés en image. Et sur les clés : une clé
applicative en variable d'environnement signifie qu'une fuite
d'environnement expose **toutes** les sessions de **tous** les clients. Le
chemin correct est un KMS avec des clés de données par espace de travail ; le
format sérialisé (`v1.<nonce>.<chiffré>`) est versionné pour permettre cette
migration sans casse.

---

## 4. Absents de la spécification

Par ordre décroissant d'importance :

1. **RGPD.** Photos de vêtements portés (donc de personnes), messages
   d'acheteurs, adresses d'expédition : ce sont des données personnelles. Ni
   durée de conservation, ni suppression, ni export ne sont mentionnés. Sur
   un SaaS français vendu à des professionnels, c'est un manque sérieux.
2. **Import de l'existant.** Un revendeur qui s'inscrit a déjà 200 annonces
   en ligne. Le jour 1, il a besoin d'importer, pas de créer. C'est
   probablement le premier facteur d'adoption, et il n'apparaît nulle part.
3. **Frais et marge nette.** Le tableau de bord promet « CA, marge ». Sans
   modèle des commissions, des frais de port subventionnés et des options
   payantes, les marges affichées seront fausses — et une marge fausse est
   pire qu'une marge absente.
4. **Coût marginal et quotas.** Rendu d'images et appels vision sont le vrai
   coût variable. Les paliers d'abonnement doivent s'y adosser. Le schéma
   trace déjà le coût IA (`ai_generations.cost_micros`) ; il manque les
   quotas d'usage et une limitation de débit sur notre propre API.
5. **Retours et annulations.** L'énumération de statuts n'a pas de
   `returned`. Un retour remet l'article en stock — c'est un cas courant.
6. **E-mail transactionnel.** La réinitialisation de mot de passe est au
   périmètre sans prestataire d'envoi choisi. À l'étape 1, le lien est
   journalisé en développement, et uniquement là.

---

## 5. Ordre de développement

L'ordre proposé est cohérent. Une remarque quand même : l'étape 2 (IA) est la
partie la plus facilement remplaçable du produit — la génération de texte est
devenue une commodité — alors que l'étape 4 (un connecteur fiable) est ce que
personne ne fait bien. Si l'objectif est de valider le produit auprès de
vrais revendeurs, je passerais 1 → 4 → 3 → 2 → 5 : un connecteur qui marche
prouve la promesse, une belle description non.

Si l'objectif est d'avoir tôt quelque chose de démontrable sans risque de
compte, l'ordre initial est le bon. C'est un arbitrage produit, pas
technique.

Dernier point, sur l'affirmation d'ouverture : « 80 % de leur temps ». Elle
mérite d'être mesurée avant d'être mise en avant. Si le vrai goulot
d'étranglement est le sourcing et la prise de vue, l'outil s'attaque à moins
que ce qui est annoncé — ce qui reste très bien, mais change le discours.

---

## 6. Ce qui est bien vu dans la spécification

Pour équilibrer, et parce que ces choix ont structuré l'implémentation :

- le modèle **un article, N publications** est le bon, et il est
  difficilement rattrapable après coup s'il est raté ;
- **ne pas promettre l'instantané** sur une opération qui prend des minutes ;
- **le mode brouillon par défaut**, et l'avertissement CGU à l'accueil : la
  position honnête, et celle qui protège l'éditeur ;
- **rester sur les comptes que l'utilisateur possède déjà**, sans création
  automatisée ni contournement de CAPTCHA : c'est la ligne qui sépare un
  outil professionnel d'un outil de fraude ;
- **la reprise idempotente à l'étape 5** plutôt qu'à l'étape 9, quand tout
  serait à réécrire.
