from datetime import UTC, datetime

import pytest

from app.ai.base import AIBudgetExceeded, BudgetGuard, NoAIProvider, month_spend_cents
from app.db.models import AiUsage


def test_free_calls_are_always_allowed(db):
    BudgetGuard(monthly_budget_cents=0).check(db, estimated_cost_cents=0)


def test_paid_call_blocked_when_budget_exceeded(db):
    guard = BudgetGuard(monthly_budget_cents=100)
    guard.record(db, provider="test", model="m", purpose="extract", cost_cents=90)
    db.flush()
    assert month_spend_cents(db) == 90
    with pytest.raises(AIBudgetExceeded):
        guard.check(db, estimated_cost_cents=20)


def test_previous_month_spend_is_ignored(db):
    db.add(
        AiUsage(
            created_at=datetime(2000, 1, 15, tzinfo=UTC),
            provider="t",
            model="m",
            purpose="x",
            cost_cents=999,
        )
    )
    db.flush()
    assert month_spend_cents(db) == 0


def test_no_ai_provider_returns_nothing():
    assert NoAIProvider().extract_listing("texte", None) == {}
