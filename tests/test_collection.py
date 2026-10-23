"""Moteur de collecte, testé avec des sources simulées."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.collection.searches import sync_searches
from app.collection.service import CollectionService, expire_unverifiable, purge_raw_payloads
from app.core.business_config import SearchSpec, load_business_config
from app.core.errors import SourceBlockedError
from app.core.settings import Settings
from app.db.models import Listing, ListingSearch, RawListing, SavedSearch, SearchRun, SourceState
from app.db.session import get_sessionmaker, session_scope
from app.db.sync import sync_categories
from app.normalization.service import ListingNormalizer
from tests.helpers import NOW, BrokenConnector, FakeConnector, make_raw


@pytest.fixture
def config():
    cfg = load_business_config("config")
    cfg.searches = [
        SearchSpec(
            code="iphone",
            name="iPhone",
            keywords="iphone 13",
            category="smartphone",
            connectors=["fake"],
            max_price_eur=350,
            interval_minutes=60,
        ),
    ]
    with session_scope() as db:
        sync_categories(db, cfg)
    return cfg


@pytest.fixture
def fake():
    return FakeConnector(Settings(), items=[make_raw("1", 30000), make_raw("2", 25000)])


def service(config, connectors: dict):
    return CollectionService(
        get_sessionmaker(), config, Settings(), connector_factory=lambda code: connectors[code]
    )


def count(model) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_first_run_stores_listings_and_links(config, fake):
    summary = service(config, {"fake": fake}).run(NOW)
    assert [o.status for o in summary.outcomes] == ["success"]
    assert summary.total_new == 2
    assert count(Listing) == 2 and count(ListingSearch) == 2
    query = fake.queries[0]
    assert query.keywords == "iphone 13" and query.max_price_cents == 35000
    with session_scope() as db:
        run = db.scalars(select(SearchRun)).one()
        assert (run.status, run.found, run.new_count) == ("success", 2, 2)
        assert {lst.category_code for lst in db.scalars(select(Listing))} == {"smartphone"}


def test_no_duplicates_and_price_changes_detected(config, fake):
    svc = service(config, {"fake": fake})
    svc.run(NOW)
    fake.items = [make_raw("1", 28000), make_raw("2", 25000), make_raw("3", 20000)]
    summary = svc.run(NOW + timedelta(hours=1))
    outcome = summary.outcomes[0]
    assert (outcome.found, outcome.new, outcome.price_changes) == (3, 1, 1)
    assert count(Listing) == 3


def test_search_not_due_is_skipped(config, fake):
    svc = service(config, {"fake": fake})
    svc.run(NOW)
    assert svc.run(NOW + timedelta(minutes=20)).outcomes == []
    # Marge de 10 min : une tâche horaire un peu en avance relance bien la recherche.
    assert len(svc.run(NOW + timedelta(minutes=55)).outcomes) == 1


def test_failing_source_does_not_stop_others(config, fake):
    config.searches.append(
        SearchSpec(code="velo", name="Vélo", keywords="vélo", connectors=["broken", "fake"])
    )
    broken = BrokenConnector(Settings())
    summary = service(config, {"fake": fake, "broken": broken}).run(NOW)
    statuses = {(o.search, o.connector): o.status for o in summary.outcomes}
    assert statuses == {
        ("iphone", "fake"): "success",
        ("velo", "broken"): "error",
        ("velo", "fake"): "success",
    }
    assert count(Listing) == 2
    assert len(summary.failures) == 1
    assert "❌ velo / broken" in summary.as_text()


def test_unknown_connector_is_reported_not_fatal(config, fake):
    config.searches[0].connectors = ["nexistepas", "fake"]

    def factory(code):
        if code == "fake":
            return fake
        from app.sources.registry import get_connector

        return get_connector(code)

    svc = CollectionService(get_sessionmaker(), config, Settings(), connector_factory=factory)
    outcomes = svc.run(NOW).outcomes
    assert [o.status for o in outcomes] == ["error", "success"]


def test_unconfigured_source_is_silently_skipped(config, fake):
    fake.configured = False
    summary = service(config, {"fake": fake}).run(NOW)
    assert summary.outcomes[0].status == "skipped"
    assert summary.failures == []
    assert fake.queries == []


def test_circuit_breaker_pauses_then_resumes(config):
    broken = BrokenConnector(Settings())
    broken.code = "fake"
    config.collection.circuit_breaker.base_pause_minutes = 120
    svc = service(config, {"fake": broken})
    when = NOW
    for _ in range(3):  # seuil : 3 échecs de suite
        summary = svc.run(when)
        when += timedelta(hours=1)
    assert "fake" in summary.paused_sources
    # Pendant la pause, la source n'est plus interrogée.
    calls = broken.api_calls
    assert svc.run(when).outcomes[0].status == "skipped"
    assert broken.api_calls == calls
    # Après la pause (120 min), elle est de nouveau essayée.
    assert svc.run(when + timedelta(hours=2)).outcomes[0].status == "error"


def test_blocked_source_gets_max_pause(config, fake):
    fake.fail_with = SourceBlockedError("403")
    summary = service(config, {"fake": fake}).run(NOW)
    assert summary.outcomes[0].status == "blocked"
    assert summary.paused_sources["fake"] == NOW + timedelta(hours=24)


def test_daily_quota_is_respected(config, fake):
    config.collection.ebay.daily_call_budget = 1
    fake.code = "ebay_api"
    svc = service(config, {"ebay_api": fake})
    config.searches[0].connectors = ["ebay_api"]
    svc.run(NOW)
    with session_scope() as db:
        assert db.get(SourceState, "ebay_api").calls_today == 1
    outcome = svc.run(NOW + timedelta(hours=1)).outcomes[0]
    assert outcome.status == "skipped" and "quota" in outcome.message
    # Le lendemain, le quota repart à zéro.
    assert svc.run(NOW + timedelta(days=1)).outcomes[0].status == "success"


def test_disappeared_listings_are_checked(config, fake):
    svc = service(config, {"fake": fake})
    svc.run(NOW)
    fake.items = []  # la recherche ne voit plus les annonces 1 et 2
    fake.gone = {"1"}
    fake.sold = {"2"}
    outcome = svc.run(NOW + timedelta(hours=25)).outcomes[0]
    assert outcome.disappeared == 2
    with session_scope() as db:
        statuses = dict(db.execute(select(Listing.external_id, Listing.status)).all())
    assert statuses == {"1": "removed", "2": "sold"}


def test_expire_unverifiable_and_purge(config):
    with session_scope() as db:
        normalizer = ListingNormalizer()
        normalizer.normalize(db, make_raw("lbc1", platform="leboncoin"))
        normalizer.normalize(db, make_raw("eb1", platform="ebay"))
    with session_scope() as db:
        assert expire_unverifiable(db, config, NOW + timedelta(days=15)) == 1
        assert purge_raw_payloads(db, config, NOW + timedelta(days=91)) == 2
    with session_scope() as db:
        statuses = dict(db.execute(select(Listing.platform, Listing.status)).all())
        assert statuses == {"leboncoin": "expired", "ebay": "active"}
        assert all(r.payload is None for r in db.scalars(select(RawListing)))


def test_sync_searches_deactivates_removed(config):
    with session_scope() as db:
        sync_searches(db, config)
    config.searches = []
    with session_scope() as db:
        sync_searches(db, config)
        search = db.scalars(select(SavedSearch)).one()
        assert search.is_active is False
