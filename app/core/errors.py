"""Exceptions métier communes. Chaque composant lève ces erreurs plutôt que des erreurs
génériques, pour que l'appelant sache quoi faire (réessayer, ignorer, alerter)."""


class FlipScoreError(Exception):
    """Erreur de base de l'application."""


class ConfigError(FlipScoreError):
    """Fichier de configuration absent ou invalide."""


class SourceError(FlipScoreError):
    """Erreur côté source de données (plateforme, API, e-mail)."""


class SourceTemporaryError(SourceError):
    """Erreur passagère (réseau, quota) : on peut réessayer plus tard."""


class SourceBlockedError(SourceError):
    """La plateforme refuse l'accès : NE PAS réessayer en boucle (risque de bannissement)."""
