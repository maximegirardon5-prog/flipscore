# Collecte des annonces

## Vue d'ensemble

```
config/searches.yaml ──sync──▶ saved_searches
                                   │ (recherches arrivées à échéance)
                                   ▼
                      CollectionService (app/collection/service.py)
                       │   pour chaque (recherche, source), indépendamment :
                       │   1. source configurée ? en pause ? quota du jour restant ?
                       │   2. connector.search(...)  →  RawListingData
                       │   3. normalisation  →  listings (+ historique des prix)
                       │   4. lien listing_searches (quelle recherche a vu quelle annonce)
                       │   5. vérification des annonces disparues (si la source le permet)
                       ▼
            search_runs (journal)   source_states (santé + quota)
```

Lancement : `./run.sh job collect` (en local) ou le workflow planifié GitHub Actions (étape c).

## Garanties

| Exigence | Comment |
|---|---|
| Pas de doublons | annonce unique par (plateforme, identifiant) ; version brute identique non réarchivée |
| Changements de prix | une ligne `listing_price_history` à chaque changement |
| Annonces disparues | eBay : vérification ciblée (`fetch`) des annonces non revues depuis 24 h → `sold` ou `removed`. Sources non vérifiables (Leboncoin, Vinted) : `expired` après 14 jours sans être revues |
| Une source en panne n'arrête pas les autres | chaque couple (recherche, source) a sa propre transaction et sa propre gestion d'erreur |
| Pas d'acharnement | erreurs passagères : 3 nouvelles tentatives espacées ; 3 échecs de suite : pause de 1 h, doublée à chaque nouvel échec (max 24 h) ; accès refusé (403) : pause de 24 h immédiate |
| Quotas | eBay : 4 000 appels/jour maximum (réglable), décomptés dans `source_states` |
| Source non configurée | ignorée sans erreur (ex. eBay tant que les clés ne sont pas saisies) |
| RGPD | pseudo vendeur haché avec un sel secret, retiré des données brutes ; données brutes purgées après 90 jours |

## Fréquence

La tâche planifiée tourne toutes les heures. Chaque recherche a sa fréquence
(`interval_minutes`, 60 minimum) : elle n'est lancée que si son échéance est atteinte (marge de
10 minutes pour absorber les retards de GitHub Actions).

## Lire le journal

Dans le tableur Supabase (*Table Editor*) :
- `search_runs` : une ligne par recherche et par source (vues, nouvelles, prix modifiés,
  disparues, appels, erreur) ;
- `source_states` : état de chaque source (échecs de suite, pause, appels du jour) ;
- `listings` : les annonces.

## Connecteur eBay

- API officielle Browse, marketplace `EBAY_FR`, annonces situées en France.
- Mode « main propre » (`local_pickup_only: true`) : uniquement les annonces à retirer autour
  du code postal, dans le rayon indiqué.
- Filtres : prix (min/max), états, catégories eBay (`ebay_category_ids` dans le profil de
  catégorie, optionnel), formats de vente (`collection.yaml`).
- Secrets : `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_ENV` (voir le guide
  [guide-ebay.md](guide-ebay.md)).
