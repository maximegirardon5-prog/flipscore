"""Moteur d'estimation du prix de revente (implémentation : phase 4).

Rôle    : prix de revente probable, fourchette et délai, à partir des comparables.
Entrée  : produit + état + observations de prix
Sortie  : EstimateResult (enregistré dans la table `estimates`)
"""

from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


class EstimateResult(BaseModel):
    price_low_cents: int = Field(ge=0)
    price_median_cents: int = Field(ge=0)
    price_high_cents: int = Field(ge=0)
    sell_days_estimate: int | None = None
    comparables_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    method: str


class Estimator(Protocol):
    def estimate(self, db: Session, product_id: int, condition: str) -> EstimateResult: ...
