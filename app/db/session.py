"""Connexion à la base et sessions.

Sous Vercel (serverless), chaque requête peut démarrer une nouvelle instance : on garde un
petit pool de connexions et on vérifie qu'une connexion est vivante avant de l'utiliser.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        engine = create_engine(database_url, connect_args={"check_same_thread": False})

        # SQLite n'applique les clés étrangères que si on le lui demande.
        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    return create_engine(database_url, pool_pre_ping=True, pool_size=2, max_overflow=2)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session transactionnelle : commit si tout va bien, rollback en cas d'erreur.

    with session_scope() as db:
        db.add(objet)
    """
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
