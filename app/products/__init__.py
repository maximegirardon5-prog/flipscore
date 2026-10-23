"""Identification du produit (implémentation : phase 3).

Rôle    : répondre à « c'est quoi exactement ? » : catégorie, marque, modèle, attributs.
          Règles et mots-clés des profils YAML d'abord ; IA seulement en cas de doute.
Entrée  : Listing + profils de catégorie
Sortie  : MatchResult (produit trouvé ou créé + confiance)
"""

from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Listing


class MatchResult(BaseModel):
    product_id: int | None
    category_code: str | None
    confidence: float = Field(ge=0, le=1)
    method: str  # "rules" | "ai" | "manual"


class ProductMatcher(Protocol):
    def match(self, db: Session, listing: Listing) -> MatchResult: ...
