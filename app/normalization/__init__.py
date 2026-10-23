"""Normalisation des annonces (implémentation : phase 2).

Rôle    : transformer un `RawListingData` (format du connecteur) en ligne `listings`
          (format unique) : état standardisé, prix en centimes, vendeur pseudonymisé,
          distance depuis ta zone, dédoublonnage, historique des changements de prix.
Entrée  : RawListingData (app/sources/base.py)
Sortie  : Listing (app/db/models.py), créée ou mise à jour.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models import Listing
from app.sources.base import RawListingData


class Normalizer(Protocol):
    def normalize(self, db: Session, raw: RawListingData) -> Listing: ...
