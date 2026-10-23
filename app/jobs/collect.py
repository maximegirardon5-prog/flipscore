"""Tâche de collecte : lance les recherches arrivées à échéance.

    python -m app.jobs.collect          (ou ./run.sh job collect)

Code retour 1 si au moins une source a échoué (GitHub Actions affiche alors ❌), mais les
sources qui fonctionnent ont bien écrit leurs annonces.
"""

from sqlalchemy.orm import Session

from app.collection.service import CollectionService, CollectionSummary
from app.core.business_config import get_business_config
from app.core.settings import get_settings
from app.core.timeutil import utcnow
from app.db.session import get_sessionmaker
from app.jobs.runner import run_job


class CollectionFailed(Exception):
    def __init__(self, summary: CollectionSummary) -> None:
        super().__init__(summary.as_text())
        self.summary = summary


def collect(db: Session) -> int:
    service = CollectionService(get_sessionmaker(), get_business_config(), get_settings())
    summary = service.run(utcnow())
    print(summary.as_text())
    if summary.failures:
        raise CollectionFailed(summary)
    return summary.total_new


if __name__ == "__main__":
    raise SystemExit(run_job("collect", collect))
