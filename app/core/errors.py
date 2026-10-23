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


class SourceQuotaExceeded(SourceTemporaryError):
    """Plafond d'appels du jour atteint : on reprendra demain, sans rien forcer."""


class ListingGone(SourceError):
    """L'annonce demandée n'existe plus sur la plateforme (vendue ou retirée)."""

    def __init__(self, ref: str, status: str = "removed") -> None:
        super().__init__(f"Annonce terminée : {ref} ({status})")
        self.ref = ref
        self.status = status
