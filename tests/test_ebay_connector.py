"""Connecteur eBay testé contre une API eBay SIMULÉE (aucun appel réseau réel)."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.business_config import load_business_config
from app.core.errors import (
    ListingGone,
    SourceBlockedError,
    SourceError,
    SourceQuotaExceeded,
    SourceTemporaryError,
)
from app.core.settings import Settings
from app.sources.base import SearchQuery
from app.sources.ebay_api import EbayConnector, to_cents


def item(n: int, **extra) -> dict:
    data = {
        "itemId": f"v1|{n}|0",
        "title": f"iPhone 13 128 Go n°{n}",
        "price": {"value": "320.50", "currency": "EUR"},
        "condition": "Occasion",
        "conditionId": "3000",
        "image": {"imageUrl": f"https://i.ebayimg.com/{n}.jpg"},
        "itemWebUrl": f"https://www.ebay.fr/itm/{n}",
        "itemLocation": {"city": "Lyon", "postalCode": "69***", "country": "FR"},
        "seller": {
            "username": "vendeur_secret",
            "feedbackPercentage": "99.1",
            "feedbackScore": 250,
            "sellerAccountType": "INDIVIDUAL",
        },
        "shippingOptions": [{"shippingCost": {"value": "6.00", "currency": "EUR"}}],
        "itemCreationDate": "2026-09-30T10:00:00.000Z",
    }
    data.update(extra)
    return data


class FakeEbay:
    """Simule les points d'accès eBay utilisés. `responses` permet d'injecter des erreurs."""

    def __init__(self, total_items: int = 5, page_size: int = 2):
        self.items = [item(n) for n in range(1, total_items + 1)]
        self.page_size = page_size
        self.requests: list[httpx.Request] = []
        self.forced: list[httpx.Response] = []  # réponses imposées, consommées dans l'ordre
        self.token_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/oauth2/token"):
            self.token_calls += 1
            return httpx.Response(
                200, json={"access_token": f"tok{self.token_calls}", "expires_in": 7200}
            )
        if self.forced:
            return self.forced.pop(0)
        if "/item_summary/search" in request.url.path:
            params = parse_qs(urlparse(str(request.url)).query)
            offset, limit = int(params["offset"][0]), int(params["limit"][0])
            page = self.items[offset : offset + limit]
            body = {"total": len(self.items), "itemSummaries": page}
            if offset + limit < len(self.items):
                body["next"] = "https://api.ebay.com/next"
            return httpx.Response(200, json=body)
        if "/buy/browse/v1/item/" in request.url.path:
            ref = request.url.path.rsplit("/", 1)[-1]
            if ref.startswith("v1%7C404") or ref.startswith("v1|404"):
                return httpx.Response(404, json={"errors": [{"message": "Item not found"}]})
            data = item(1, itemId="v1|1|0")
            if "777" in ref:
                data["estimatedAvailabilities"] = [{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]
            return httpx.Response(200, json=data)
        return httpx.Response(500)


@pytest.fixture
def fake_ebay():
    return FakeEbay()


@pytest.fixture
def connector(fake_ebay):
    cfg = load_business_config("config")
    cfg.collection.ebay.page_size = fake_ebay.page_size
    settings = Settings(ebay_client_id="id", ebay_client_secret="secret")
    return EbayConnector(
        settings, config=cfg, transport=httpx.MockTransport(fake_ebay), sleep=lambda s: None
    )


def search_requests(fake: FakeEbay) -> list[httpx.Request]:
    return [r for r in fake.requests if "item_summary" in r.url.path]


def test_not_configured_without_keys():
    assert not EbayConnector(Settings(ebay_client_id=None, ebay_client_secret=None)).is_configured()


def test_to_cents():
    assert to_cents({"value": "320.50"}) == 32050
    assert to_cents({"value": "0.1"}) == 10
    assert to_cents(None) is None
    assert to_cents({"value": "abc"}) is None


def test_search_paginates_and_maps_listings(connector, fake_ebay):
    results = list(connector.search(SearchQuery(keywords="iphone 13", limit=100)))
    assert len(results) == 5
    assert len(search_requests(fake_ebay)) == 3  # 2 + 2 + 1
    raw = results[0]
    assert raw.platform == "ebay" and raw.external_id == "v1|1|0"
    assert raw.draft.price_cents == 32050
    assert raw.draft.shipping_cents == 600
    assert raw.draft.condition == "good"
    assert raw.draft.seller_is_pro is False
    assert raw.draft.photos == ["https://i.ebayimg.com/1.jpg"]
    assert connector.api_calls == 4  # 1 jeton + 3 pages


def test_search_respects_max_pages(connector, fake_ebay):
    connector.config.collection.ebay.max_pages_per_search = 1
    assert len(list(connector.search(SearchQuery(keywords="iphone")))) == 2


def test_seller_username_is_never_stored(connector):
    raw = next(connector.search(SearchQuery(keywords="iphone")))
    assert raw.draft.seller_id == "vendeur_secret"  # transmis pour être haché…
    assert "vendeur_secret" not in json.dumps(raw.payload)  # …mais absent des données brutes


def test_request_headers_and_filters(connector, fake_ebay):
    query = SearchQuery(
        keywords="iphone 13",
        min_price_cents=12000,
        max_price_cents=35000,
        conditions=["good"],
        postal_code="69001",
    )
    next(connector.search(query))
    request = search_requests(fake_ebay)[0]
    assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_FR"
    assert request.headers["Authorization"] == "Bearer tok1"
    assert (
        "zip%3D69001" in request.headers["X-EBAY-C-ENDUSERCTX"]
        or "zip=69001" in request.headers["X-EBAY-C-ENDUSERCTX"]
    )
    filters = parse_qs(urlparse(str(request.url)).query)["filter"][0]
    assert "price:[120.00..350.00]" in filters
    assert "priceCurrency:EUR" in filters
    assert "conditionIds:{2020|2030|2990|3000|4000|5000}" in filters
    assert "itemLocationCountry:FR" in filters


def test_local_pickup_filters(connector):
    filters = connector.build_filters(
        SearchQuery(keywords="vélo", local_pickup_only=True, postal_code="69001", radius_km=25)
    )
    for part in [
        "pickupCountry:FR",
        "pickupPostalCode:69001",
        "pickupRadius:25",
        "pickupRadiusUnit:km",
        "deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}",
    ]:
        assert part in filters
    assert "itemLocationCountry" not in filters


def test_expired_token_is_renewed_once(connector, fake_ebay):
    fake_ebay.forced = [httpx.Response(401)]
    results = list(connector.search(SearchQuery(keywords="iphone", limit=2)))
    assert len(results) == 2
    assert fake_ebay.token_calls == 2


def test_temporary_errors_are_retried(connector, fake_ebay):
    fake_ebay.forced = [httpx.Response(503), httpx.Response(429)]
    assert len(list(connector.search(SearchQuery(keywords="iphone", limit=2)))) == 2


def test_persistent_errors_raise_temporary_error(connector, fake_ebay):
    fake_ebay.forced = [httpx.Response(503)] * 10
    with pytest.raises(SourceTemporaryError):
        list(connector.search(SearchQuery(keywords="iphone")))


def test_access_denied_stops_immediately(connector, fake_ebay):
    fake_ebay.forced = [httpx.Response(403)]
    with pytest.raises(SourceBlockedError):
        list(connector.search(SearchQuery(keywords="iphone")))
    assert len(search_requests(fake_ebay)) == 1  # aucune nouvelle tentative


def test_bad_request_raises_with_ebay_message(connector, fake_ebay):
    fake_ebay.forced = [httpx.Response(400, json={"errors": [{"message": "Invalid filter"}]})]
    with pytest.raises(SourceError, match="Invalid filter"):
        list(connector.search(SearchQuery(keywords="iphone")))


def test_call_budget_is_enforced(connector):
    connector.call_budget = 2  # 1 jeton + 1 page
    with pytest.raises(SourceQuotaExceeded):
        list(connector.search(SearchQuery(keywords="iphone", limit=100)))
    assert connector.api_calls == 2


def test_fetch_existing_sold_and_gone(connector):
    assert connector.fetch("v1|1|0").draft.is_sold is False
    assert connector.fetch("v1|777|0").draft.is_sold is True
    with pytest.raises(ListingGone):
        connector.fetch("v1|404|0")


def test_authentication_failure_hides_secrets(fake_ebay):
    def refuse(request):
        return httpx.Response(401, json={"error": "invalid_client"})

    connector = EbayConnector(
        Settings(ebay_client_id="id", ebay_client_secret="supersecret"),
        config=load_business_config("config"),
        transport=httpx.MockTransport(refuse),
        sleep=lambda s: None,
    )
    with pytest.raises(SourceError) as excinfo:
        list(connector.search(SearchQuery(keywords="x")))
    assert "supersecret" not in str(excinfo.value)
    assert connector.healthcheck() is False
