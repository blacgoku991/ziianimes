# Avant de publier sur un vrai compte

Ce document liste ce qui **n'a pas pu être vérifié** dans l'environnement de
développement, et ce qu'il reste à faire avant qu'une annonce parte
réellement. Il est délibérément explicite : l'écart entre « ça tourne » et
« ça publie sans faire restreindre le compte du client » se joue là.

---

## 1. Calibrer les sélecteurs Vinted — bloquant

**État : non calibré.** Cet environnement n'a ni compte Vinted ni accès au
site. Le fichier `app/connectors/vinted/selectors.py` décrit la *forme*
attendue du formulaire `/items/new` et permet de faire tourner et de tester
toute la machinerie, mais ses sélecteurs n'ont pas rencontré le vrai DOM.

Tant que `CALIBRATED = False` :

- `VintedConnector.supports_autopublish` vaut `False` ;
- toute publication Vinted est forcée en **mode brouillon**, quelle que soit
  la demande.

C'est volontaire : un jeu de sélecteurs non vérifié ne doit pas pouvoir
soumettre une annonce.

Marche à suivre :

```bash
# 1. Rattacher le compte dans l'interface, y coller les cookies de session
# 2. Lancer la calibration — le navigateur s'ouvre en mode visible
make calibrate-vinted id=<account_id>
```

L'outil rapporte, cible par cible, le sélecteur qui fonctionne ou l'absence
de candidat valide. Corrigez `selectors.py`, incrémentez
`SELECTOR_SET_VERSION`, puis passez `CALIBRATED` à `True`.

La version du jeu de sélecteurs est journalisée avec chaque publication :
c'est ce qui permet de corréler une vague d'échecs à un changement de
formulaire côté plateforme.

## 2. Remplacer les identifiants du référentiel

`app/referential/seed/vinted.json` est un jeu de **départ saisi à la main**
(76 catégories, 84 marques, 84 tailles). Il approche l'arborescence réelle
sans en être une copie, et **ses identifiants externes sont locaux**.

Conséquence concrète : le rapprochement de catégories fonctionne dès
l'installation et sert à la calibration, mais les `external_id` ne
correspondent à rien côté plateforme. Le connecteur Vinted contourne le
problème en pilotant la cascade par le **chemin lisible** plutôt que par
l'identifiant — ce qui marche, mais reste un contournement.

Avant la production, écrire une `ReferentialSource` qui récupère les vrais
identifiants (`app/referential/importer.py`, le point d'extension est
prévu). L'import est différentiel : les correspondances déjà apprises par
les utilisateurs survivent au remplacement.

## 3. Brancher les API officielles

Les connecteurs eBay, Depop et Leboncoin
(`app/connectors/api_based.py`) implémentent l'authentification, la gestion
d'erreurs, la limitation de débit et la conversion vers le contrat commun.
Les URL d'API sont posées mais **non testées contre les services réels** :
chacun demande un compte développeur validé et des identifiants
d'application.

Prévoir aussi, pour chacun : le parcours OAuth de bout en bout (aujourd'hui
le jeton est collé à la main) et le rafraîchissement automatique du jeton.

## 4. Vérifier les barèmes de frais

`app/services/fees.py` contient des valeurs par défaut plausibles, pas une
vérité contractuelle. Elles changent régulièrement et diffèrent entre
comptes particuliers et professionnels.

Le tableau de bord et les prix conseillés en dépendent directement : une
marge fausse oriente les décisions d'achat du revendeur dans le mauvais
sens. Confirmer compte par compte, puis surcharger via
`workspaces.settings["fees"]`.

## 5. Sécurité — ce qui reste à durcir

| Point | État | À faire |
|---|---|---|
| Chiffrement des sessions | AES-256-GCM, AAD liée à la ligne | Passer à un KMS avec clés de données par espace de travail. Le format (`v1.<nonce>.<chiffré>`) est versionné pour permettre la migration |
| Profils navigateur | Répertoire isolé par compte, supprimé avec le compte | Monter en `tmpfs` — c'est fait dans `docker-compose.yml`, à confirmer sur la cible réelle |
| Clé applicative | Variable d'environnement | Une fuite d'environnement expose toutes les sessions de tous les clients |
| E-mail transactionnel | Non branché | Le lien de réinitialisation est journalisé **en développement uniquement** |
| Limitation de débit de notre API | Absente | L'import de photos est coûteux, il doit être borné par espace de travail |

## 6. RGPD — non traité

Signalé dans la revue de spécification et toujours ouvert. Photos de
vêtements portés, messages d'acheteurs, adresses d'expédition : ce sont des
données personnelles. Il manque une durée de conservation, une procédure de
suppression et un export. Sur un SaaS français vendu à des professionnels,
c'est à traiter avant les premiers clients payants.

## 7. Stripe

Les colonnes existent (`stripe_customer_id`, `subscription_status`,
`trial_ends_at`) et l'essai de 14 jours est initialisé à l'inscription.
L'intégration elle-même n'est pas faite : ni parcours de paiement, ni
webhooks, ni application des quotas par palier.

Le coût variable réel est déjà tracé (`ai_generations.cost_micros`, remonté
dans le tableau de bord), ce qui donne la base pour calibrer les paliers.

## 8. Le point qui n'est pas technique

La **fenêtre de survente** (`SYNC_INTERVAL_SECONDS`, 10 minutes par défaut)
est le délai pendant lequel une pièce vendue reste visible ailleurs. Deux
acheteurs peuvent l'acheter. Le produit le détecte, le signale
(`oversold: true`, journal en erreur) et l'affiche dans le tableau de bord —
mais il ne peut pas l'empêcher.

Il faut décider, en produit et non en technique : réduire l'intervalle,
n'autoriser qu'une plateforme à la fois pour les pièces uniques, ou assumer
et documenter le risque auprès des utilisateurs. Voir
`docs/REVUE_SPEC.md` §1.2.
