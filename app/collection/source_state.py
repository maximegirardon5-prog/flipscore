"""Santé et quota de chaque source : mise en pause automatique d'une source en panne
(« disjoncteur ») et décompte des appels du jour."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.business_config import CircuitBreaker
from app.core.timeutil import as_utc
from app.db.models import SourceState


def get_state(db: Session, connector: str) -> SourceState:
    state = db.get(SourceState, connector)
    if state is None:
        state = SourceState(connector=connector, consecutive_failures=0, calls_today=0)
        db.add(state)
        db.flush()
    return state


def paused_until(state: SourceState, now: datetime) -> datetime | None:
    until = as_utc(state.paused_until)
    return until if until and until > now else None


def calls_used_today(state: SourceState, now: datetime) -> int:
    return state.calls_today if state.calls_day == now.date().isoformat() else 0


def add_calls(state: SourceState, calls: int, now: datetime) -> None:
    today = now.date().isoformat()
    if state.calls_day != today:
        state.calls_day, state.calls_today = today, 0
    state.calls_today += calls


def record_success(state: SourceState, now: datetime) -> None:
    state.consecutive_failures = 0
    state.paused_until = None
    state.last_error = None
    state.last_success_at = now


def record_failure(
    state: SourceState, error: str, now: datetime, breaker: CircuitBreaker, *, blocked: bool = False
) -> datetime | None:
    """Compte un échec. Renvoie la date de fin de pause si la source vient d'être mise en pause.

    Pause = base × 2^(échecs au-delà du seuil), plafonnée. Un accès refusé (blocked) met
    directement la pause maximale : on n'insiste jamais auprès d'une plateforme qui refuse.
    """
    state.consecutive_failures += 1
    state.last_error = error[:2000]
    max_pause = timedelta(hours=breaker.max_pause_hours)
    if blocked:
        state.paused_until = now + max_pause
        return state.paused_until
    over = state.consecutive_failures - breaker.failures_before_pause
    if over >= 0:
        pause = min(timedelta(minutes=breaker.base_pause_minutes) * (2**over), max_pause)
        state.paused_until = now + pause
        return state.paused_until
    return None
