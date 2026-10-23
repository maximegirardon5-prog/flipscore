# Modèle de données

Définition exacte : [`app/db/models.py`](../app/db/models.py). Migration initiale :
`alembic/versions/`. Testé sur SQLite et PostgreSQL 16.

## Conventions

- Identifiants entiers auto-incrémentés (lisibles dans le tableur Supabase).
- **Montants en centimes** (entiers) + devise : aucune erreur d'arrondi.
- Dates en UTC avec fuseau horaire.
- Listes fermées (états, statuts) en texte, protégées par des contraintes `CHECK`.
- `created_at` et `updated_at` sur les tables métier.

## Relations

```
 raw_listings ──▶ listings ──┬──▶ listing_price_history
   (brut)        (normalisé) ├──▶ scores ──▶ score_criteria
                     │       │       └──▶ estimates ◀── price_observations
                     ▼       └──▶ alerts ◀── saved_searches            ▲
                 products ──▶ categories                                │
                                                                        │
 inventory_items ──┬──▶ purchases                 ventes réelles ───────┘
   (stock)         ├──▶ sales
                   └──▶ item_costs          vue v_item_profit = profit réel par objet

 Techniques : settings, config_snapshots, job_runs, ai_usage
```

## Tables

| Table | Rôle |
|---|---|
| `raw_listings` | annonce brute telle que reçue (payload purgé après 90 jours) |
| `listings` | annonce normalisée, unique par (plateforme, identifiant) |
| `listing_price_history` | une ligne par changement de prix |
| `categories` | copie en base des profils YAML (intégrité des liens) |
| `products` | référence générique (marque, modèle, attributs JSON, empreinte unique) |
| `price_observations` | prix connus d'un produit (annonce, vente, ta vente réelle), avec un poids de qualité |
| `estimates` | estimation de revente mise en cache (fourchette, délai, confiance) |
| `scores` | score 0-100, marge, ROI, frais détaillés, résumé, points forts et faibles, réglages utilisés |
| `score_criteria` | détail par critère : valeur brute, sous-score, poids, explication, signaux |
| `saved_searches` | recherches surveillées et leurs seuils |
| `alerts` | alertes envoyées (anti-doublon garanti) et ton retour (intéressé, acheté, ignoré…) |
| `inventory_items` | objets en stock et leur statut |
| `purchases` / `sales` / `item_costs` | achat, vente, frais annexes : profit réel |
| `settings` | réglages personnels (priorité sur les YAML) |
| `config_snapshots` | configuration figée utilisée par les scores |
| `job_runs` | journal des tâches planifiées |
| `ai_usage` | chaque appel IA et son coût (plafond mensuel) |

## Attributs propres à chaque catégorie

Les colonnes communes (catégorie, marque, modèle) sont de vraies colonnes. Le reste est en
**JSON** (JSONB sous PostgreSQL, indexé en GIN), **validé par le schéma du profil YAML** de
la catégorie.

```
Téléphone : {"storage_gb": 128, "battery_health": 87, "carrier_locked": false}
Vélo      : {"bike_type": "gravel", "frame_size": "M", "groupset": "Shimano 105"}
Vêtement  : {"size": "L", "gender": "homme", "material": "laine"}
```

Alternatives écartées : une table par catégorie (modifier la base à chaque catégorie) et le
modèle EAV (requêtes complexes et illisibles).

## RGPD

- Vendeur : identifiant **haché** uniquement, jamais nom, téléphone ou e-mail.
- Acheteur : aucune donnée stockée.
- Données brutes purgées après 90 jours.
