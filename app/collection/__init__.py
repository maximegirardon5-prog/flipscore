"""Collecte des annonces : orchestration des connecteurs, planification, quotas, pannes.

Rôle    : lancer les recherches enregistrées arrivées à échéance sur leurs sources, faire
          normaliser les annonces, détecter les changements de prix et les disparitions.
Entrée  : recherches enregistrées (config/searches.yaml) + connecteurs
Sortie  : annonces en base + journal `search_runs` + état des sources `source_states`
"""
