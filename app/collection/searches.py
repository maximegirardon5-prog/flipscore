"""Synchronise config/searches.yaml vers la table `saved_searches`."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_config import BusinessConfig
from app.core.logging import get_logger
from app.db.models import SavedSearch

log = get_logger(__name__)


def _cents(eur: float | None) -> int | None:
    return None if eur is None else round(eur * 100)


def sync_searches(db: Session, config: BusinessConfig) -> int:
    """Crée ou met à jour les recherches. Une recherche retirée du fichier est désactivée
    (pas supprimée : l'historique y fait référence). Renvoie le nombre de recherches actives."""
    existing = {s.code: s for s in db.scalars(select(SavedSearch))}
    default_interval = config.collection.default_interval_minutes

    for spec in config.searches:
        row = existing.pop(spec.code, None)
        if row is None:
            row = SavedSearch(code=spec.code)
            db.add(row)
        row.name = spec.name
        row.query = spec.keywords
        row.connectors = list(spec.connectors)
        row.category_code = spec.category
        row.min_price_cents = _cents(spec.min_price_eur)
        row.max_price_cents = _cents(spec.max_price_eur)
        row.conditions = list(spec.conditions)
        row.local_pickup_only = spec.local_pickup_only
        row.postal_code = spec.postal_code
        row.radius_km = spec.radius_km
        row.interval_minutes = spec.interval_minutes or default_interval
        row.is_active = spec.active

    for row in existing.values():  # recherches retirées du fichier
        if row.is_active:
            log.info("recherche désactivée (retirée de searches.yaml)", extra={"code": row.code})
        row.is_active = False

    db.flush()
    return sum(1 for s in config.searches if s.active)
