"""Prépare la base : applique les migrations puis synchronise les catégories.

python -m app.jobs.init_db
"""

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.core.business_config import get_business_config
from app.db.sync import sync_categories
from app.jobs.runner import run_job


def upgrade_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def init_db(db: Session) -> int:
    return sync_categories(db, get_business_config())


if __name__ == "__main__":
    upgrade_schema()
    raise SystemExit(run_job("init_db", init_db))
