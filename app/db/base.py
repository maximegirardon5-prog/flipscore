"""Base commune des modèles SQLAlchemy et types partagés."""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB sous PostgreSQL (indexable, rapide), JSON simple sous SQLite (tests, local).
JsonType = JSON().with_variant(JSONB(), "postgresql")

# BIGINT sous PostgreSQL ; INTEGER sous SQLite (seul type auto-incrémenté par SQLite).
IdType = BigInteger().with_variant(Integer(), "sqlite")

# Noms de contraintes prévisibles : indispensable pour des migrations Alembic propres.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Ajoute created_at / updated_at à une table."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class IdMixin:
    id: Mapped[int] = mapped_column(IdType, primary_key=True, autoincrement=True)
