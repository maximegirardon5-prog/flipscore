"""Prépare la base : applique les migrations puis synchronise catégories et recherches.

python -m app.jobs.init_db
"""

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.collection.searches import sync_searches
from app.core.business_config import get_business_config
from app.db.sync import sync_categories
from app.jobs.runner import run_job


def upgrade_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def init_db(db: Session) -> int:
    config = get_business_config()
    changed = sync_categories(db, config)  # catégories d'abord (les recherches y font référence)
    sync_searches(db, config)
    return changed


if __name__ == "__main__":
    upgrade_schema()
    raise SystemExit(run_job("init_db", init_db))
