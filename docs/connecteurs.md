# Contrat des connecteurs de sources

Code de référence : [`app/sources/base.py`](../app/sources/base.py). Exemple complet :
[`app/sources/demo.py`](../app/sources/demo.py).

## Ajouter une plateforme

1. Créer `app/sources/ma_plateforme.py` avec une classe qui hérite de `SourceConnector`.
2. Déclarer la plateforme dans `config/platforms.yaml` (frais, modes d'accès).
3. C'est tout : le registre la découvre automatiquement et la suite de tests
   `tests/test_connectors.py` vérifie qu'elle respecte le contrat.

## Ce qu'un connecteur déclare

| Attribut | Exemple | Rôle |
|---|---|---|
| `code` | `"ebay_api"` | identifiant unique |
| `platform` | `"ebay"` | doit exister dans `platforms.yaml` (ou `"any"`) |
| `capabilities` | `search=True, fetch=True` | ce qu'il sait faire |
| `min_interval_seconds` | `1.0` | délai minimal entre deux appels |
| `enabled_in_production` | `True` | `False` pour un connecteur de test |

## Ce qu'un connecteur sait faire (selon ses capacités)

| Méthode | Entrée | Sortie |
|---|---|---|
| `search(query)` | `SearchQuery` (mots-clés, prix, zone, limite) | itérateur de `RawListingData` |
| `fetch(ref)` | URL ou identifiant | `RawListingData` |
| `parse_manual(data)` | `ManualInput` (texte, URL, image, plateforme) | liste de `RawListingData` |
| `healthcheck()` | — | `True` si la source répond |
| `is_configured()` | — | `True` si les secrets nécessaires sont présents |

## Format de sortie : `RawListingData`

- `platform`, `connector`, `external_id`, `url`, `fetched_at`
- `payload` : données brutes complètes (conservées 90 jours, pour pouvoir retraiter)
- `draft` (`ListingDraft`) : champs standards que le connecteur sait lire (titre et prix
  obligatoires ; état, photos, localisation, vendeur, attributs… optionnels)

Le connecteur ne calcule rien et n'écrit pas en base. La normalisation fait le travail
générique (état standardisé, vendeur pseudonymisé, distance, dédoublonnage, historique).

## Règles obligatoires

1. **Respecter les CGU.** Pas de scraping de Leboncoin ni de Vinted (voir `risques.md`).
2. Respecter `min_interval_seconds`.
3. `SourceTemporaryError` pour une erreur passagère (on réessaiera) ;
   `SourceBlockedError` si l'accès est refusé (on s'arrête, sans insister).
4. Ne jamais remonter de données personnelles inutiles (nom, téléphone, e-mail).

## Connecteurs prévus

| Code | Plateforme | Mode | Phase |
|---|---|---|---|
| `demo` | — | données fictives (tests) | 1 ✅ |
| `ebay_api` | eBay | API officielle Browse | 2 |
| `email_alert` | Leboncoin, Vinted | lecture des e-mails d'alerte de la boîte Gmail dédiée | 2 |
| `manual_text` | toutes | texte collé dans Telegram ou sur le site | 2 |
| `screenshot` | toutes | capture d'écran analysée par l'IA | IA |
