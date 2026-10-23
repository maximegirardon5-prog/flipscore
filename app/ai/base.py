"""Interface IA + garde-fou budgétaire.

Tout appel IA DOIT passer par `BudgetGuard.check()` avant, et `record()` après : aucun
appel ne part si le plafond mensuel (AI_MONTHLY_BUDGET_CENTS) serait dépassé.
"""

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import FlipScoreError
from app.db.models import AiUsage


class AIBudgetExceeded(FlipScoreError):
    """Plafond mensuel atteint : l'app continue sans IA (mode dégradé)."""


class AIProvider(Protocol):
    name: str

    def extract_listing(self, text: str | None, image: bytes | None) -> dict[str, Any]:
        """Extrait titre, prix, état, attributs d'un texte ou d'une capture d'écran."""
        ...


class NoAIProvider:
    """Fournisseur « aucune IA » : utilisé quand AI_PROVIDER=none."""

    name = "none"

    def extract_listing(self, text: str | None, image: bytes | None) -> dict[str, Any]:
        return {}


def month_spend_cents(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(
        select(func.coalesce(func.sum(AiUsage.cost_cents), 0)).where(AiUsage.created_at >= start)
    )
    return int(total or 0)


class BudgetGuard:
    def __init__(self, monthly_budget_cents: int) -> None:
        self.monthly_budget_cents = monthly_budget_cents

    def check(self, db: Session, estimated_cost_cents: int) -> None:
        """Lève AIBudgetExceeded si l'appel ferait dépasser le plafond.

        Un appel estimé à 0 centime (palier gratuit) est toujours autorisé : ce sont alors
        les quotas du fournisseur qui limitent.
        """
        if estimated_cost_cents <= 0:
            return
        if month_spend_cents(db) + estimated_cost_cents > self.monthly_budget_cents:
            raise AIBudgetExceeded("Plafond IA mensuel atteint")

    def record(self, db: Session, **usage: Any) -> AiUsage:
        row = AiUsage(created_at=datetime.now(UTC), **usage)
        db.add(row)
        return row
