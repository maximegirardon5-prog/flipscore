"""Outils partagés par les tests : fabrique d'annonces brutes et faux connecteurs."""

from collections.abc import Iterator
from datetime import UTC, datetime

from app.core.errors import ListingGone, SourceTemporaryError
from app.sources.base import (
    ConnectorCapabilities,
    ListingDraft,
    RawListingData,
    SearchQuery,
    SourceConnector,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def make_raw(
    external_id: str = "1",
    price_cents: int = 30000,
    platform: str = "ebay",
    title: str = "iPhone 13 128 Go",
    **draft,
) -> RawListingData:
    return RawListingData(
        platform=platform,
        connector="fake",
        external_id=external_id,
        url=f"https://example.invalid/{platform}/{external_id}",
        fetched_at=NOW,
        payload={"id": external_id, "price": price_cents},
        draft=ListingDraft(title=title, price_cents=price_cents, **draft),
    )


class FakeConnector(SourceConnector):
    """Source simulée : renvoie la liste `items` (modifiable entre deux passages)."""

    code = "fake"
    platform = "ebay"
    capabilities = ConnectorCapabilities(search=True, fetch=True)

    def __init__(self, settings, items=None, fail_with: Exception | None = None):
        super().__init__(settings)
        self.items: list[RawListingData] = items or []
        self.fail_with = fail_with
        self.gone: set[str] = set()
        self.sold: set[str] = set()
        self.queries: list[SearchQuery] = []
        self.configured = True
        self.api_calls = 0
        self.call_budget: int | None = None

    def is_configured(self) -> bool:
        return self.configured

    def search(self, query: SearchQuery) -> Iterator[RawListingData]:
        self.queries.append(query)
        self.api_calls += 1
        if self.fail_with:
            raise self.fail_with
        yield from (item.model_copy(deep=True) for item in self.items)

    def fetch(self, ref: str) -> RawListingData:
        self.api_calls += 1
        if ref in self.gone:
            raise ListingGone(ref)
        raw = make_raw(ref)
        raw.draft.is_sold = ref in self.sold
        return raw

    def healthcheck(self) -> bool:
        return True


class BrokenConnector(FakeConnector):
    code = "broken"

    def search(self, query):
        raise SourceTemporaryError("la source ne répond pas")
