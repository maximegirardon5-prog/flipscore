# Architecture

## Principe : un « monolithe modulaire »

Une seule application, découpée en modules qui ne communiquent que par des formats de
données définis (classes Pydantic et tables). Chaque module est remplaçable sans toucher aux
autres. Pas de microservices : trop complexes pour aucun bénéfice à cette échelle.

```
 SOURCES (plugins)                                        ┌────────────────────┐
 ┌──────────────────┐                                     │ PROFILS CATÉGORIE  │
 │ eBay API         │──┐                                  │ (config/*.yaml)    │
 │ Lien partagé     │  │  RawListingData                  └─────────┬──────────┘
 │ Capture d'écran  │  ├──────────────▶ NORMALISATION ─┐            │
 │ Texte collé      │  │                               ▼            │
 │ E-mails d'alerte │──┘                            Listing         │
 └──────────────────┘                                  │            │
                                                       ▼            │
                                       IDENTIFICATION PRODUIT ◀─────┤
                                                       │            │
              price_observations ───────▶ ESTIMATION REVENTE        │
                                                       │            │
                                                       ▼            │
                                              SCORING 0-100 ◀───────┘
                                                       │
                                        ┌──────────────┴─────────────┐
                                        ▼                            ▼
                                     ALERTES                     INTERFACE
                                  (Telegram)               (web + bot Telegram)
```

| Composant | Dossier | Entrée | Sortie | Phase |
|---|---|---|---|---|
| Connecteurs | `app/sources/` | recherche, URL, saisie manuelle | `RawListingData` | 1 (contrat), 2 |
| Normalisation | `app/normalization/` | `RawListingData` | `Listing` + historique des prix | 2 |
| Identification produit | `app/products/` | `Listing` + profils | `MatchResult` | 3 |
| Estimation | `app/estimation/` | produit + état + observations | `EstimateResult` | 4 |
| Scoring | `app/scoring/` | `Listing` + estimation + configuration | `ScoreResult` | 5 |
| Alertes | `app/alerts/` | score + recherches enregistrées | message Telegram | 6 |
| IA | `app/ai/` | texte, image | données extraites (plafond budgétaire) | selon besoin |
| Tâches | `app/jobs/` | — | exécution tracée dans `job_runs` | 1 (socle) |

Les interfaces (`Protocol`) de chaque composant sont déjà définies dans le `__init__.py` de
leur dossier : chaque phase n'aura qu'à les implémenter.

## Stack et justification

| Brique | Choix | Pourquoi |
|---|---|---|
| Langage | Python 3.12 | Lisible, excellent pour la donnée et l'IA |
| Web | FastAPI | Simple, validation intégrée, doc d'API automatique (`/docs`) |
| Base | SQLite (local, tests), PostgreSQL / Supabase (production) | Zéro installation en local ; même code grâce à SQLAlchemy |
| Migrations | Alembic | Fait évoluer le schéma sans perdre de données |
| Configuration | YAML + Pydantic | Modifiable sans code, validé strictement |
| Interface | Jinja2 + HTMX + Pico.css | Pas de framework JavaScript ni d'étape de compilation |
| Tâches | Commandes Python lancées par GitHub Actions | Gratuit, sans serveur allumé en permanence |
| Tests | pytest + ruff, dans GitHub Actions | Coche verte ou croix rouge à chaque modification |

## Hébergement à 0 €

| Rôle | Service |
|---|---|
| Code, tests, environnement de développement | GitHub (dépôt privé) + Codespaces |
| Site web + bot Telegram | Vercel (offre Hobby) |
| Base de données | Supabase (PostgreSQL) |
| Tâches planifiées | GitHub Actions (cron) |

**Chemin de migration** si les limites gratuites sont dépassées : un serveur loué (VPS,
environ 5 €/mois) ou Oracle Cloud Always Free. Les tâches sont déjà des commandes autonomes
et la base est du PostgreSQL standard : rien à réécrire.
