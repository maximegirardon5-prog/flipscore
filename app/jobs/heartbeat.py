"""Tâche « battement de cœur » : vérifie que la configuration et la base fonctionnent.

Lancée chaque jour par GitHub Actions, elle a aussi un effet utile : elle empêche la mise en
pause automatique de la base Supabase gratuite (pause après 7 jours sans activité).

    python -m app.jobs.heartbeat
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.business_config import get_business_config
from app.jobs.runner import run_job


def heartbeat(db: Session) -> int:
    config = get_business_config()  # lève ConfigError si un YAML est invalide
    db.execute(text("SELECT 1"))
    return len(config.categories)


if __name__ == "__main__":
    raise SystemExit(run_job("heartbeat", heartbeat))
