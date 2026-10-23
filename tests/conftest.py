"""Préparation commune des tests : base temporaire, migrée avec Alembic.

Par défaut : SQLite (rien à installer). Si TEST_DATABASE_URL est défini (CI), les tests
tournent sur PostgreSQL, comme en production : la base est vidée avant chaque test.
"""

import os
import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.business_config import get_business_config
from app.core.settings import get_settings
from app.db.session import get_engine

ROOT = Path(__file__).resolve().parent.parent


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_business_config.cache_clear()
    get_engine.cache_clear()


@pytest.fixture(autouse=True)
def test_env(tmp_path, monkeypatch):
    """Chaque test a sa propre base vide : aucun test ne dépend d'un autre."""
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("APP_ENV", "test")
    pg_url = os.environ.get("TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", pg_url or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("CONFIG_DIR", str(ROOT / "config"))
    _clear_caches()
    if pg_url:
        with get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield
    get_engine().dispose()
    _clear_caches()


@pytest.fixture
def db():
    from app.db.session import get_sessionmaker

    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def config_copy(tmp_path) -> Path:
    """Copie modifiable du dossier config/ pour tester les erreurs de configuration."""
    dest = tmp_path / "config"
    shutil.copytree(ROOT / "config", dest)
    return dest
