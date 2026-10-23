"""Alertes (implémentation : phase 6).

Rôle    : prévenir quand une annonce correspond à une recherche enregistrée et dépasse
          ses seuils. Anti-doublon garanti par la base (alerts : saved_search_id + listing_id).
Entrée  : Score + SavedSearch
Sortie  : message envoyé (Telegram) + ligne `alerts`
"""

from typing import Protocol


class Notifier(Protocol):
    """Un canal d'envoi (Telegram aujourd'hui, e-mail ou push demain)."""

    channel: str

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> str:
        """Envoie le message et renvoie l'identifiant du message côté canal."""
        ...
