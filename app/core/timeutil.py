"""Dates : tout est manipulé en UTC avec fuseau.

SQLite (tests, local) relit les dates sans fuseau : `as_utc` les ramène en UTC pour pouvoir
les comparer sans erreur.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
