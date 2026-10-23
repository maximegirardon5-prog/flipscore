"""Environnement Alembic : relie les migrations à nos modèles et à DATABASE_URL."""

from logging.config import fileConfig

from alembic import context

from app.core.settings import get_settings
from app.db import models  # noqa: F401  (importe toutes les tables)
from app.db.base import Base
from app.db.session import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Une URL passée explicitement (tests) a priorité sur DATABASE_URL.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def include_object(obj, name, type_, reflected, compare_to):
    """Ignore les index propres à PostgreSQL (GIN) quand la base n'est pas PostgreSQL."""
    if type_ == "index" and name and name.endswith("_gin"):
        return context.get_context().dialect.name == "postgresql"
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        # render_as_batch : permet de modifier des colonnes même sous SQLite.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
