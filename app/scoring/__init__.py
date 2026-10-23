"""Moteur de scoring (implémentation : phase 5).

Rôle    : score 0-100 EXPLICABLE à partir de 6 critères pondérés (config/scoring.yaml,
          surchargés par le profil de catégorie).
Entrée  : Listing + EstimateResult + configuration métier
Sortie  : ScoreResult (enregistré dans `scores` + `score_criteria`)
"""

from typing import Protocol

from pydantic import BaseModel, Field

from app.core.business_config import BusinessConfig
from app.db.models import Listing
from app.estimation import EstimateResult


class CriterionResult(BaseModel):
    criterion: str
    raw_value: float | None
    raw_unit: str | None
    sub_score: int = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    explanation: str
    flags: list[str] = Field(default_factory=list)

    @property
    def contribution(self) -> float:
        return self.sub_score * self.weight


class ScoreResult(BaseModel):
    total: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    net_margin_cents: int | None
    roi_pct: float | None
    cost_breakdown: dict[str, int]
    criteria: list[CriterionResult]
    summary: str
    strengths: list[str]
    weaknesses: list[str]


class Scorer(Protocol):
    def score(
        self, listing: Listing, estimate: EstimateResult | None, config: BusinessConfig
    ) -> ScoreResult: ...
