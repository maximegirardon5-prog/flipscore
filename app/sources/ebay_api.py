"""Connecteur eBay : API officielle « Browse » (https://developer.ebay.com/api-docs/buy/browse/).

Fonctionnement :
- authentification « application » (client credentials) : un jeton valable ~2 h, renouvelé
  automatiquement ;
- recherche sur eBay.fr (mots-clés, budget, états, catégories eBay optionnelles), annonces
  situées en France, ou uniquement en remise en main propre autour d'un code postal ;
- pagination jusqu'à la limite demandée ;
- plafond d'appels par passage (`call_budget`, fixé par la collecte d'après le quota du jour) ;
- erreurs passagères : nouvelles tentatives ; accès refusé : arrêt net.

Données personnelles : le pseudo du vendeur est retiré des données brutes avant tout stockage
(il n'est transmis à la normalisation que pour être haché). Aucune donnée personnelle eBay
n'est donc conservée, ce qui justifie l'exemption « Marketplace Account Deletion ».

Licence eBay : les données eBay ne doivent pas être envoyées à une IA qui s'en sert pour
s'entraîner (paliers gratuits notamment).
"""

import base64
import copy
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from app.core.business_config import BusinessConfig, get_business_config
from app.core.errors import ListingGone, SourceError, SourceQuotaExceeded
from app.core.logging import get_logger
from app.core.settings import Settings
from app.normalization.conditions import condition_from_ebay
from app.sources.base import (
    ConnectorCapabilities,
    ListingDraft,
    RawListingData,
    SearchQuery,
    SourceConnector,
)
from app.sources.http import PoliteHttpClient

log = get_logger(__name__)

HOSTS = {"production": "https://api.ebay.com", "sandbox": "https://api.sandbox.ebay.com"}
SCOPE = "https://api.ebay.com/oauth/api_scope"

# États standards -> codes d'état eBay (filtre conditionIds).
CONDITION_IDS = {
    "new": ["1000", "1500", "1750"],
    "like_new": ["2000", "2010", "2500", "2750"],
    "good": ["2020", "2030", "2990", "3000", "4000", "5000"],
    "fair": ["3010", "6000"],
    "for_parts": ["7000"],
}


def to_cents(amount: dict | None) -> int | None:
    """{"value": "320.50", "currency": "EUR"} -> 32050. None si absent ou illisible."""
    if not amount or amount.get("value") in (None, ""):
        return None
    try:
        return int((Decimal(str(amount["value"])) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class EbayConnector(SourceConnector):
    code = "ebay_api"
    platform = "ebay"
    capabilities = ConnectorCapabilities(search=True, fetch=True)
    min_interval_seconds = 0.2

    def __init__(
        self,
        settings: Settings,
        *,
        config: BusinessConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(settings)
        self._config = config
        self._transport = transport
        self._sleep = sleep
        self._http: PoliteHttpClient | None = None
        self._token: str | None = None
        self._token_expires_at = 0.0
        #: Nombre maximal d'appels autorisés pour ce passage (None = pas de limite locale).
        self.call_budget: int | None = None
        #: Appels effectués (comptés pour le quota du jour).
        self.api_calls = 0

    # --- configuration ---------------------------------------------------------------------

    @property
    def config(self) -> BusinessConfig:
        if self._config is None:
            self._config = get_business_config()
        return self._config

    @property
    def base_url(self) -> str:
        return HOSTS[self.settings.ebay_env]

    def is_configured(self) -> bool:
        return bool(self.settings.ebay_client_id and self.settings.ebay_client_secret)

    @property
    def http(self) -> PoliteHttpClient:
        if self._http is None:
            self._http = PoliteHttpClient(
                "ebay",
                min_interval_seconds=self.min_interval_seconds,
                transport=self._transport,
                sleep=self._sleep,
            )
        return self._http

    # --- appels bas niveau -----------------------------------------------------------------

    def _count_call(self) -> None:
        if self.call_budget is not None and self.api_calls >= self.call_budget:
            raise SourceQuotaExceeded("eBay : plafond d'appels atteint pour ce passage")
        self.api_calls += 1

    def _get_token(self, force: bool = False) -> str:
        if self._token and not force and time.monotonic() < self._token_expires_at:
            return self._token
        if not self.is_configured():
            raise SourceError("eBay : EBAY_CLIENT_ID / EBAY_CLIENT_SECRET manquants")
        secret = self.settings.ebay_client_secret.get_secret_value()  # type: ignore[union-attr]
        basic = base64.b64encode(f"{self.settings.ebay_client_id}:{secret}".encode()).decode()
        self._count_call()
        response = self.http.request(
            "POST",
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        if response.status_code != 200:
            # Ne jamais journaliser les clés : seulement le code d'erreur.
            raise SourceError(f"eBay : authentification refusée (HTTP {response.status_code})")
        body = response.json()
        self._token = body["access_token"]
        # Marge de 5 minutes avant l'expiration annoncée.
        self._token_expires_at = time.monotonic() + max(int(body.get("expires_in", 7200)) - 300, 60)
        return self._token

    def _api_get(
        self, path: str, params: dict[str, Any] | None = None, postal_code: str | None = None
    ) -> httpx.Response:
        headers = {
            "X-EBAY-C-MARKETPLACE-ID": self.config.collection.ebay.marketplace_id,
            "Accept-Language": "fr-FR",
        }
        if postal_code:
            # Permet à eBay de calculer les frais de port vers ton code postal.
            headers["X-EBAY-C-ENDUSERCTX"] = quote(
                f"contextualLocation=country=FR,zip={postal_code}", safe="="
            )
        for attempt in range(2):
            headers["Authorization"] = f"Bearer {self._get_token(force=attempt > 0)}"
            self._count_call()
            response = self.http.request(
                "GET", f"{self.base_url}{path}", params=params, headers=headers
            )
            if response.status_code != 401:  # 401 = jeton expiré : on le renouvelle une fois
                return response
        return response

    # --- construction de la recherche ------------------------------------------------------

    def build_filters(self, query: SearchQuery) -> str:
        cfg = self.config
        parts: list[str] = []
        if query.min_price_cents is not None or query.max_price_cents is not None:
            low = f"{query.min_price_cents / 100:.2f}" if query.min_price_cents is not None else ""
            high = f"{query.max_price_cents / 100:.2f}" if query.max_price_cents is not None else ""
            parts += [f"price:[{low}..{high}]", "priceCurrency:EUR"]
        if query.conditions:
            ids = [i for c in query.conditions for i in CONDITION_IDS.get(c, [])]
            if ids:
                parts.append("conditionIds:{" + "|".join(ids) + "}")
        if cfg.collection.ebay.buying_options:
            parts.append("buyingOptions:{" + "|".join(cfg.collection.ebay.buying_options) + "}")
        if query.local_pickup_only:
            postal = query.postal_code or cfg.defaults.home_postal_code
            radius = query.radius_km or cfg.defaults.max_distance_km
            # eBay exige les 4 filtres de retrait + deliveryOptions ensemble.
            parts += [
                "pickupCountry:FR",
                f"pickupPostalCode:{postal}",
                f"pickupRadius:{int(radius)}",
                "pickupRadiusUnit:km",
                "deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}",
            ]
        else:
            parts.append(f"itemLocationCountry:{cfg.collection.ebay.item_location_country}")
        return ",".join(parts)

    def _category_ids(self, query: SearchQuery) -> str | None:
        profile = self.config.categories.get(query.category_code or "")
        return (
            ",".join(profile.ebay_category_ids) if profile and profile.ebay_category_ids else None
        )

    # --- contrat SourceConnector ----------------------------------------------------------

    def search(self, query: SearchQuery) -> Iterator[RawListingData]:
        ebay_cfg = self.config.collection.ebay
        page_size = min(ebay_cfg.page_size, query.limit)
        params: dict[str, Any] = {
            "q": query.keywords,
            "limit": page_size,
            "sort": "newlyListed",
            "filter": self.build_filters(query),
        }
        if category_ids := self._category_ids(query):
            params["category_ids"] = category_ids
        postal = query.postal_code or self.config.defaults.home_postal_code

        yielded = 0
        for page in range(ebay_cfg.max_pages_per_search):
            params["offset"] = page * page_size
            response = self._api_get("/buy/browse/v1/item_summary/search", params, postal)
            if response.status_code != 200:
                raise SourceError(
                    f"eBay : recherche refusée (HTTP {response.status_code}) "
                    f"{_error_message(response)}"
                )
            body = response.json()
            items = body.get("itemSummaries", [])
            for item in items:
                yield self._to_raw(item)
                yielded += 1
                if yielded >= query.limit:
                    return
            # Fin des résultats : pas de page suivante ou page incomplète.
            if not body.get("next") or len(items) < page_size:
                return

    def fetch(self, ref: str) -> RawListingData:
        """Récupère une annonce par son identifiant eBay (ex. « v1|123456789|0 »).

        Lève ListingGone si l'annonce n'existe plus (404) ; une annonce épuisée est renvoyée
        avec `draft.is_sold = True`.
        """
        response = self._api_get(f"/buy/browse/v1/item/{quote(ref, safe='')}")
        if response.status_code in (404, 410):
            raise ListingGone(ref, "removed")
        if response.status_code != 200:
            raise SourceError(
                f"eBay : lecture refusée (HTTP {response.status_code}) {_error_message(response)}"
            )
        item = response.json()
        raw = self._to_raw(item)
        statuses = {
            a.get("estimatedAvailabilityStatus") for a in item.get("estimatedAvailabilities", [])
        }
        if statuses == {"OUT_OF_STOCK"}:
            raw.draft.is_sold = True
        return raw

    def healthcheck(self) -> bool:
        if not self.is_configured():
            return False
        try:
            self._get_token()
        except SourceError:
            return False
        return True

    # --- traduction d'une annonce eBay -----------------------------------------------------

    def _to_raw(self, item: dict[str, Any]) -> RawListingData:
        location = item.get("itemLocation") or {}
        seller = item.get("seller") or {}
        shipping = (item.get("shippingOptions") or [{}])[0]
        photos = [
            img["imageUrl"]
            for img in [item.get("image") or {}, *item.get("additionalImages", [])]
            if img.get("imageUrl")
        ]
        rating = seller.get("feedbackPercentage")

        draft = ListingDraft(
            title=item.get("title") or "(sans titre)",
            price_cents=to_cents(item.get("price")) or 0,
            currency=(item.get("price") or {}).get("currency", "EUR"),
            description=item.get("shortDescription"),
            shipping_cents=to_cents(shipping.get("shippingCost")),
            condition=condition_from_ebay(item.get("conditionId"), item.get("condition")),
            condition_raw=item.get("condition"),
            photos=photos,
            location_city=location.get("city"),
            postal_code=location.get("postalCode"),
            hand_delivery=bool(item.get("pickupOptions")) or None,
            shipping_available=bool(item.get("shippingOptions")) or None,
            seller_id=seller.get("username"),
            seller_rating=float(rating) if rating not in (None, "") else None,
            seller_review_count=seller.get("feedbackScore"),
            seller_is_pro=_is_business_seller(seller),
            published_at=parse_date(item.get("itemCreationDate")),
        )
        return RawListingData(
            platform=self.platform,
            connector=self.code,
            external_id=item.get("itemId"),
            url=item.get("itemWebUrl"),
            fetched_at=datetime.now(UTC),
            payload=_strip_personal_data(item),
            draft=draft,
        )

    def close(self) -> None:
        if self._http:
            self._http.close()


def _is_business_seller(seller: dict) -> bool | None:
    account_type = seller.get("sellerAccountType")
    if account_type == "BUSINESS":
        return True
    if account_type == "INDIVIDUAL":
        return False
    return None


def _strip_personal_data(item: dict[str, Any]) -> dict[str, Any]:
    """Copie de l'annonce sans le pseudo du vendeur (minimisation RGPD / licence eBay)."""
    clean = copy.deepcopy(item)
    if isinstance(clean.get("seller"), dict):
        clean["seller"].pop("username", None)
        clean["seller"].pop("userId", None)
    return clean


def _error_message(response: httpx.Response) -> str:
    try:
        errors = response.json().get("errors", [])
        return "; ".join(e.get("message", "") for e in errors)[:300]
    except ValueError:
        return ""
