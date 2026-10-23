# FlipScore

Application qui note les annonces de petites annonces et de marketplaces (eBay, Leboncoin,
Vinted…) avec un **score d'opportunité de 0 à 100**, explicable, pour l'achat-revente.

> **État : phase 2 (collecte) en cours.** Fondations en place ; moteur de collecte,
> normalisation et connecteur eBay prêts (eBay en sommeil tant que les clés ne sont pas
> saisies). L'estimation, le score et les alertes arrivent dans les phases suivantes.

---

## Démarrer en 5 minutes, sans rien installer (recommandé)

Tout se passe dans ton navigateur, sur PC, Mac ou tablette, grâce à **GitHub Codespaces**
(gratuit environ 60 h/mois).

1. Sur la page GitHub du projet, clique sur le bouton vert **`<> Code`**, onglet
   **Codespaces**, puis **Create codespace on main**.
2. Attends 2 à 3 minutes : un éditeur s'ouvre et **l'installation se fait toute seule**
   (le message `✅ Installation terminée` s'affiche dans le terminal en bas).
3. Dans le terminal en bas de l'écran, tape :
   ```bash
   ./run.sh test
   ```
   Tu dois voir `80 passed` (ou plus) : tout fonctionne.
4. Pour voir l'application :
   ```bash
   ./run.sh dev
   ```
   Un onglet s'ouvre (sinon : onglet **PORTS** puis l'icône 🌐 sur la ligne 8000). La page
   affiche l'état du système avec des ✅.
5. Pour arrêter l'application : clique dans le terminal et appuie sur `Ctrl + C`.

💡 Pense à **arrêter ton Codespace** quand tu as fini (menu ☰ en haut à gauche, puis
*Codespaces : Stop Current Codespace*) pour ne pas consommer tes heures gratuites.

## Démarrer sur ton ordinateur (optionnel)

Il faut **Python 3.12 ou plus récent** et **Git**.

```bash
git clone https://github.com/maximegirardon5-prog/flipscore.git
cd flipscore
./run.sh setup     # installe tout, crée .env et la base locale
./run.sh test      # lance les tests
./run.sh dev       # démarre l'application sur http://localhost:8000
```

Sous Windows, utilise **WSL** ou Git Bash (le script `run.sh` est un script bash).

## Les commandes

| Commande | Effet |
|---|---|
| `./run.sh setup` | Installe l'environnement (une seule fois) |
| `./run.sh test` | Lance tous les tests |
| `./run.sh dev` | Démarre l'application (http://localhost:8000, doc de l'API sur `/docs`) |
| `./run.sh initdb` | Crée ou met à jour les tables de la base |
| `./run.sh job collect` | Lance une collecte des annonces à la main |
| `./run.sh job heartbeat` | Vérifie que la base et la configuration fonctionnent |
| `./run.sh check` | Vérifie la qualité du code |

## Modifier les réglages, sans toucher au code

Tous les réglages métier sont dans le dossier [`config/`](config/) et sont modifiables
**directement sur le site GitHub** (ouvre le fichier, clique sur ✏️, enregistre avec
*Commit changes*).

| Fichier | Contenu |
|---|---|
| `config/scoring.yaml` | Poids des 6 critères du score, seuils de confiance et d'alerte |
| `config/platforms.yaml` | Frais de chaque plateforme |
| `config/defaults.yaml` | Tes réglages par défaut (rayon, coût au km, valeur de ton heure…) |
| `config/searches.yaml` | Tes recherches enregistrées (mots-clés, catégorie, budget, zone, fréquence) |
| `config/collection.yaml` | Réglages de la collecte (quotas, pannes, expiration) |
| `config/categories/*.yaml` | Un fichier par catégorie (attributs, frais, risques, poids) |

À chaque modification, GitHub relance les tests automatiquement (onglet **Actions**) :
✅ = ta modification est valide, ❌ = il y a une erreur, et le message indique laquelle.

**Ajouter une catégorie** = copier `config/categories/smartphone.yaml`, le renommer (par
exemple `console.yaml`) et l'adapter. Rien d'autre à faire. Voir
[docs/configuration.md](docs/configuration.md).

## Organisation du projet

```
flipscore/
├── app/                    code de l'application
│   ├── core/               réglages, secrets, journaux, erreurs, lecture des YAML
│   ├── db/                 modèle de données (tables) et accès à la base
│   ├── sources/            connecteurs de sources : 1 fichier = 1 plateforme (plugins)
│   ├── collection/         orchestration de la collecte (quotas, pannes, planification)
│   ├── normalization/      mise au format unique des annonces
│   ├── products/           identification du produit                    (phase 3)
│   ├── estimation/         estimation du prix de revente                (phase 4)
│   ├── scoring/            calcul du score explicable                   (phase 5)
│   ├── alerts/             alertes Telegram                             (phase 6)
│   ├── ai/                 accès IA interchangeable + plafond de dépense
│   ├── jobs/               tâches planifiées (lancées par GitHub Actions)
│   ├── web/                pages web
│   └── main.py             point d'entrée de l'application web
├── config/                 réglages métier (YAML), modifiables sans code
├── alembic/                migrations (évolutions du schéma de la base)
├── tests/                  tests automatiques
├── docs/                   documentation (architecture, données, risques…)
├── .github/workflows/      tests automatiques + tâches planifiées
├── .devcontainer/          configuration de Codespaces
├── .env.example            modèle du fichier de secrets
└── run.sh                  script de lancement
```

## Secrets

Les clés et mots de passe vont dans le fichier `.env` (créé par `./run.sh setup` à partir
de `.env.example`). **Ce fichier n'est jamais envoyé sur GitHub.** En production, les mêmes
valeurs se règlent dans les paramètres de Vercel et dans *Settings > Secrets and variables >
Actions* sur GitHub.

## Documentation

- [Architecture et choix techniques](docs/architecture.md)
- [Modèle de données](docs/modele-de-donnees.md)
- [Contrat des connecteurs](docs/connecteurs.md)
- [Collecte des annonces](docs/collecte.md)
- [Guide : activer eBay](docs/guide-ebay.md)
- [Configuration](docs/configuration.md)
- [Risques juridiques, techniques et de coûts](docs/risques.md)

## En cas de problème

| Symptôme | Solution |
|---|---|
| `❌ Environnement non installé` | Lance `./run.sh setup` |
| `Permission denied` sur `run.sh` | Lance `chmod +x run.sh` puis réessaie |
| Un test échoue après une modification de `config/` | Lis le message : il indique le fichier et la ligne fautive |
| La page affiche « Base de données ❌ » | Vérifie `DATABASE_URL` dans `.env` |
