"""Exécution encadrée d'une tâche : journalisation, trace en base (job_runs), code retour.

def ma_tache(db) -> int:      # renvoie le nombre d'éléments traités
    ...
if __name__ == "__main__":
    raise SystemExit(run_job("ma_tache", ma_tache))
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings
from app.db.models import JobRun
from app.db.session import session_scope

log = get_logger(__name__)


def run_job(name: str, func: Callable[[Session], int]) -> int:
    """Lance `func` et renvoie 0 si succès, 1 si erreur (GitHub Actions affiche alors ❌)."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.is_production)

    with session_scope() as db:
        run = JobRun(job_name=name, started_at=datetime.now(UTC), status="running")
        db.add(run)
    log.info("tâche démarrée", extra={"job": name, "job_run_id": run.id})

    try:
        with session_scope() as db:
            processed = func(db)
    except Exception as exc:  # on journalise TOUT échec, puis on le signale
        log.exception("tâche en échec", extra={"job": name})
        with session_scope() as db:
            row = db.merge(run)
            row.status, row.error, row.finished_at = "error", repr(exc)[:2000], datetime.now(UTC)
        return 1

    with session_scope() as db:
        row = db.merge(run)
        row.status, row.items_processed, row.finished_at = "success", processed, datetime.now(UTC)
    log.info("tâche terminée", extra={"job": name, "items": processed})
    return 0
