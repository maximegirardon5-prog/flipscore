"""Orchestration d'un passage de collecte.

Principes :
- chaque couple (recherche, source) est une unité indépendante, dans sa propre transaction :
  une source en panne n'empêche jamais les autres de tourner ;
- une source non configurée (clés absentes) est simplement ignorée ;
- une source en échec répété est mise en pause (disjoncteur), avec reprise automatique ;
- le quota quotidien de chaque source est respecté ;
- tout est tracé dans `search_runs` (journal lisible) et résumé dans `CollectionSummary`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.collection.searches import sync_searches
from app.collection.source_state import (
    add_calls,
    calls_used_today,
    get_state,
    paused_until,
    record_failure,
    record_success,
)
from app.core.business_config import BusinessConfig
from app.core.errors import (
    ConfigError,
    ListingGone,
    SourceBlockedError,
    SourceQuotaExceeded,
    SourceTemporaryError,
)
from app.core.logging import get_logger
from app.core.settings import Settings
from app.core.timeutil import as_utc
from app.db.models import Listing, ListingSearch, RawListing, SavedSearch, SearchRun
from app.normalization.service import ListingNormalizer, mark_ended
from app.sources.base import SearchQuery, SourceConnector
from app.sources.registry import discover_connectors, get_connector

log = get_logger(__name__)

# Une recherche est lancée si son échéance tombe dans cette marge : la tâche planifiée
# horaire peut démarrer avec quelques minutes d'avance ou de retard.
DUE_GRACE = timedelta(minutes=10)
# Nombre maximal d'annonces lues par recherche et par passage (le connecteur limite aussi).
MAX_RESULTS_PER_RUN = 1000

SessionFactory = Callable[[], Session]
ConnectorFactory = Callable[[str], SourceConnector]


@dataclass
class RunOutcome:
    search: str
    connector: str
    status: str  # success | error | blocked | skipped
    found: int = 0
    new: int = 0
    price_changes: int = 0
    disappeared: int = 0
    api_calls: int = 0
    message: str = ""


@dataclass
class CollectionSummary:
    outcomes: list[RunOutcome] = field(default_factory=list)
    expired: int = 0
    purged_payloads: int = 0
    paused_sources: dict[str, datetime] = field(default_factory=dict)

    @property
    def failures(self) -> list[RunOutcome]:
        return [o for o in self.outcomes if o.status in ("error", "blocked")]

    @property
    def total_new(self) -> int:
        return sum(o.new for o in self.outcomes)

    def as_text(self) -> str:
        """Résumé lisible (journal GitHub Actions, message Telegram)."""
        lines = []
        for o in self.outcomes:
            icon = {"success": "✅", "skipped": "⏭️"}.get(o.status, "❌")
            detail = (
                f"{o.found} vues, {o.new} nouvelles, {o.price_changes} prix modifiés, "
                f"{o.disappeared} disparues, {o.api_calls} appels"
                if o.status == "success"
                else o.message
            )
            lines.append(f"{icon} {o.search} / {o.connector} : {detail}")
        if self.expired:
            lines.append(f"⌛ {self.expired} annonces expirées (non vérifiables)")
        if self.purged_payloads:
            lines.append(f"🧹 {self.purged_payloads} données brutes purgées")
        for source, until in self.paused_sources.items():
            lines.append(f"⏸️ source {source} en pause jusqu'à {until:%d/%m %H:%M} UTC")
        return "\n".join(lines) or "Aucune recherche à lancer."


class CollectionService:
    def __init__(
        self,
        session_factory: SessionFactory,
        config: BusinessConfig,
        settings: Settings,
        connector_factory: ConnectorFactory | None = None,
        normalizer: ListingNormalizer | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config
        self.settings = settings
        self.connector_factory = connector_factory or (lambda code: get_connector(code, settings))
        self.normalizer = normalizer or ListingNormalizer()
        self._connectors: dict[str, SourceConnector] = {}

    # --- point d'entrée --------------------------------------------------------------------

    def run(self, now: datetime, job_run_id: int | None = None) -> CollectionSummary:
        summary = CollectionSummary()
        with self._session() as db:
            sync_searches(db, self.config)
            due = [
                (s.id, s.code, list(s.connectors))
                for s in db.scalars(select(SavedSearch).where(SavedSearch.is_active.is_(True)))
                if s.next_run_at is None or as_utc(s.next_run_at) <= now + DUE_GRACE
            ]

        for search_id, code, connector_codes in due:
            for connector_code in connector_codes:
                outcome = self._run_one(search_id, code, connector_code, now, job_run_id, summary)
                summary.outcomes.append(outcome)
            with self._session() as db:
                search = db.get(SavedSearch, search_id)
                search.last_run_at = now
                search.next_run_at = now + timedelta(minutes=search.interval_minutes)
                if any(o.status == "success" for o in summary.outcomes if o.search == code):
                    search.last_success_at = now

        summary.expired = self._isolated(lambda db: expire_unverifiable(db, self.config, now), 0)
        summary.purged_payloads = self._isolated(
            lambda db: purge_raw_payloads(db, self.config, now), 0
        )
        for connector in self._connectors.values():
            close = getattr(connector, "close", None)
            if close:
                close()
        return summary

    # --- une recherche sur une source -----------------------------------------------------

    def _run_one(
        self,
        search_id: int,
        code: str,
        connector_code: str,
        now: datetime,
        job_run_id: int | None,
        summary: CollectionSummary,
    ) -> RunOutcome:
        outcome = RunOutcome(search=code, connector=connector_code, status="skipped")
        try:
            connector = self._get_connector(connector_code)
        except ConfigError as exc:
            outcome.status, outcome.message = "error", str(exc)
            self._record_run(search_id, connector_code, now, job_run_id, outcome)
            return outcome

        if not connector.is_configured():
            outcome.message = "source non configurée (clés absentes) : ignorée"
            log.info(outcome.message, extra={"search": code, "connector": connector_code})
            return outcome

        with self._session() as db:
            state = get_state(db, connector_code)
            until = paused_until(state, now)
            remaining = self._daily_budget(connector_code) - calls_used_today(state, now)
        if until:
            outcome.message = f"source en pause jusqu'à {until:%d/%m %H:%M} UTC"
            return outcome
        if remaining <= 0:
            outcome.message = "quota d'appels du jour atteint : reprise demain"
            return outcome
        if hasattr(connector, "call_budget"):
            connector.call_budget = connector.api_calls + remaining

        calls_before = getattr(connector, "api_calls", 0)
        try:
            with self._session() as db:
                search = db.get(SavedSearch, search_id)
                self._collect(db, search, connector, now, outcome)
                self._check_disappeared(db, search, connector, now, outcome)
            outcome.status = "success"
        except SourceQuotaExceeded as exc:
            outcome.status, outcome.message = "skipped", str(exc)
        except SourceBlockedError as exc:
            outcome.status, outcome.message = "blocked", str(exc)
        except Exception as exc:  # isolation : aucune erreur ne doit arrêter les autres sources
            outcome.status, outcome.message = "error", f"{type(exc).__name__}: {exc}"
            if not isinstance(exc, SourceTemporaryError):
                log.exception(
                    "erreur inattendue", extra={"search": code, "connector": connector_code}
                )
        outcome.api_calls = getattr(connector, "api_calls", 0) - calls_before

        with self._session() as db:
            state = get_state(db, connector_code)
            add_calls(state, outcome.api_calls, now)
            if outcome.status == "success":
                record_success(state, now)
            elif outcome.status in ("error", "blocked"):
                pause = record_failure(
                    state,
                    outcome.message,
                    now,
                    self.config.collection.circuit_breaker,
                    blocked=outcome.status == "blocked",
                )
                if pause:
                    summary.paused_sources[connector_code] = pause
        self._record_run(search_id, connector_code, now, job_run_id, outcome)
        log.info("recherche terminée", extra={**outcome.__dict__})
        return outcome

    def _collect(
        self,
        db: Session,
        search: SavedSearch,
        connector: SourceConnector,
        now: datetime,
        outcome: RunOutcome,
    ) -> None:
        query = SearchQuery(
            keywords=search.query,
            category_code=search.category_code,
            min_price_cents=search.min_price_cents,
            max_price_cents=search.max_price_cents,
            postal_code=search.postal_code,
            radius_km=search.radius_km,
            conditions=search.conditions,
            local_pickup_only=search.local_pickup_only,
            limit=MAX_RESULTS_PER_RUN,
        )
        seen: set[int] = set()
        for raw in connector.search(query):
            raw.fetched_at = now
            result = self.normalizer.normalize(db, raw, category_code=search.category_code)
            if result.listing.id in seen:
                continue  # même annonce renvoyée deux fois (pagination qui bouge)
            seen.add(result.listing.id)
            outcome.found += 1
            outcome.new += result.is_new
            outcome.price_changes += result.price_changed
            link = db.get(ListingSearch, (result.listing.id, search.id))
            if link is None:
                db.add(
                    ListingSearch(
                        listing_id=result.listing.id,
                        saved_search_id=search.id,
                        first_matched_at=now,
                        last_matched_at=now,
                    )
                )
            else:
                link.last_matched_at = now
        db.flush()

    def _check_disappeared(
        self,
        db: Session,
        search: SavedSearch,
        connector: SourceConnector,
        now: datetime,
        outcome: RunOutcome,
    ) -> None:
        """Vérifie auprès de la source les annonces que la recherche ne voit plus."""
        rules = self.config.collection.disappearance
        if not connector.capabilities.fetch or rules.max_checks_per_run == 0:
            return
        threshold = now - timedelta(hours=rules.check_after_hours)
        candidates = db.scalars(
            select(Listing)
            .join(ListingSearch, ListingSearch.listing_id == Listing.id)
            .where(
                ListingSearch.saved_search_id == search.id,
                ListingSearch.last_matched_at < threshold,
                Listing.status == "active",
                Listing.platform == connector.platform,
                or_(Listing.status_checked_at.is_(None), Listing.status_checked_at < threshold),
            )
            .order_by(Listing.status_checked_at.is_not(None), Listing.status_checked_at)
            .limit(rules.max_checks_per_run)
        ).all()
        for listing in candidates:
            try:
                raw = connector.fetch(listing.external_id)
            except ListingGone as gone:
                mark_ended(listing, gone.status, now)
                outcome.disappeared += 1
                continue
            except SourceTemporaryError:
                log.warning("vérification interrompue", extra={"listing_id": listing.id})
                break
            raw.fetched_at = now
            result = self.normalizer.normalize(db, raw)
            result.listing.status_checked_at = now
            if result.listing.status == "sold":
                outcome.disappeared += 1
        db.flush()

    # --- outils ----------------------------------------------------------------------------

    def _get_connector(self, code: str) -> SourceConnector:
        if code not in self._connectors:
            self._connectors[code] = self.connector_factory(code)
        return self._connectors[code]

    def _daily_budget(self, connector_code: str) -> int:
        if connector_code == "ebay_api":
            return self.config.collection.ebay.daily_call_budget
        return 10**9  # pas de quota connu pour les autres sources

    def _record_run(
        self,
        search_id: int,
        connector_code: str,
        now: datetime,
        job_run_id: int | None,
        outcome: RunOutcome,
    ) -> None:
        with self._session() as db:
            db.add(
                SearchRun(
                    job_run_id=job_run_id,
                    saved_search_id=search_id,
                    connector=connector_code,
                    started_at=now,
                    finished_at=now,
                    status=outcome.status,
                    found=outcome.found,
                    new_count=outcome.new,
                    price_changes=outcome.price_changes,
                    disappeared=outcome.disappeared,
                    api_calls=outcome.api_calls,
                    error=outcome.message or None,
                )
            )

    def _isolated(self, func: Callable[[Session], int], default: int) -> int:
        try:
            with self._session() as db:
                return func(db)
        except Exception:
            log.exception("tâche de maintenance en échec")
            return default

    def _session(self):
        return _SessionScope(self.session_factory)


class _SessionScope:
    """Transaction courte : commit en sortie normale, rollback en cas d'erreur."""

    def __init__(self, factory: SessionFactory) -> None:
        self.session = factory()

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()


# --- maintenance ---------------------------------------------------------------------------


def verifiable_platforms() -> set[str]:
    """Plateformes dont on peut vérifier le statut d'une annonce (connecteur avec fetch)."""
    return {
        cls.platform
        for cls in discover_connectors().values()
        if cls.capabilities.fetch and cls.platform != "any" and cls.enabled_in_production
    }


def expire_unverifiable(db: Session, config: BusinessConfig, now: datetime) -> int:
    """Annonces de plateformes non vérifiables (Leboncoin, Vinted) non revues depuis N jours :
    passées en « expired »."""
    cutoff = now - timedelta(days=config.collection.disappearance.expire_unverifiable_after_days)
    result = db.execute(
        update(Listing)
        .where(
            Listing.status == "active",
            Listing.platform.not_in(verifiable_platforms()),
            Listing.last_seen_at < cutoff,
        )
        .values(status="expired", ended_at=now)
    )
    return result.rowcount or 0


def purge_raw_payloads(db: Session, config: BusinessConfig, now: datetime) -> int:
    """Efface les données brutes plus anciennes que la durée de conservation."""
    cutoff = now - timedelta(days=config.collection.raw_payload_retention_days)
    result = db.execute(
        update(RawListing)
        .where(RawListing.fetched_at < cutoff, RawListing.payload.is_not(None))
        .values(payload=None)
    )
    return result.rowcount or 0
