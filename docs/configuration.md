# Configuration

Trois niveaux, chacun pour une raison précise.

| Quoi | Où | Modifié par |
|---|---|---|
| Secrets (clés API, mots de passe, jeton Telegram) | Variables d'environnement : `.env` en local, Vercel et GitHub Secrets en production | toi, une fois |
| Réglages métier par défaut (poids, frais, catégories) | `config/*.yaml`, versionnés dans Git | toi, sur le site GitHub |
| Recherches enregistrées et réglages de collecte | `config/searches.yaml`, `config/collection.yaml` | toi, sur le site GitHub |
| Réglages personnels du quotidien (ville, rayon, seuils) | Table `settings` | toi, depuis l'interface (phase interface) |

**Priorité** : table `settings` > YAML de la catégorie > YAML par défaut.

## Validation

Chaque fichier YAML est validé strictement (`app/core/business_config.py`) :
- une clé inconnue (faute de frappe) est **refusée**, pas ignorée ;
- les valeurs sont contrôlées (poids ≥ 0, pourcentages entre 0 et 100…) ;
- les liens entre fichiers sont vérifiés (catégorie parente, plateformes de revente).

Les tests vérifient la configuration à chaque modification : une erreur bloque la mise en
ligne au lieu de casser l'application.

## Traçabilité

Chaque score enregistre l'empreinte de la configuration utilisée (`config_snapshots`). Si
tu changes les poids, les anciens scores restent explicables.

## Profil de catégorie : champs disponibles

| Champ | Rôle |
|---|---|
| `code`, `name`, `parent` | identité (le nom du fichier doit être `<code>.yaml`) |
| `keywords` | aide à reconnaître la catégorie dans une annonce |
| `attributes` | attributs propres : `type` (int, float, text, bool, choice), `required`, `price_relevant`, `min`, `max`, `choices`, `label` |
| `resale_platforms` | où revendre (doivent exister dans `platforms.yaml`) |
| `typical_shipping_cents`, `packaging_cents` | frais d'envoi et d'emballage typiques |
| `repair_reserve_pct` | réserve pour remise en état |
| `typical_days_to_sell` | délai de vente moyen (liquidité) |
| `storage_volume` | encombrement : small, medium, large |
| `counterfeit_risk`, `risk_keywords` | signaux de risque |
| `weights` | surcharge partielle des poids du score |

`price_relevant: true` signifie que l'attribut fait varier le prix : deux annonces ne sont
comparées que si ces attributs sont identiques (un iPhone 128 Go n'est pas comparé à un
512 Go).

## Recherches enregistrées (`config/searches.yaml`)

Chaque recherche indique ses mots-clés, sa catégorie, ses sources (`connectors`), son budget
(`min_price_eur`, `max_price_eur`), les états acceptés, sa fréquence (`interval_minutes`,
60 minimum) et éventuellement une zone (`local_pickup_only`, `postal_code`, `radius_km`).
Le fichier est commenté champ par champ. Une recherche retirée du fichier est désactivée
(son historique est conservé). Ne change pas le `code` d'une recherche existante.

## Collecte (`config/collection.yaml`)

Fréquence par défaut, durée de conservation des données brutes, quota eBay, pagination,
règles de détection des annonces disparues et du disjoncteur (mise en pause d'une source en
panne). Voir [collecte.md](collecte.md).
