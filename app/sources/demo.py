"""Connecteur de DÉMONSTRATION : renvoie des annonces fictives, sans aucun accès réseau.

Il sert de modèle pour écrire un vrai connecteur et de jeu de données pour les tests.
Désactivé en production.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

from app.sources.base import (
    ConnectorCapabilities,
    ListingDraft,
    ManualInput,
    RawListingData,
    SearchQuery,
    SourceConnector,
)

_FIXTURES = [
    {
        "id": "demo-1",
        "title": "iPhone 13 128 Go noir, batterie 88 %",
        "price": 32000,
        "condition": "Très bon état",
        "city": "Lyon",
        "category": "smartphone",
        "attributes": {"storage_gb": 128, "battery_health": 88},
    },
    {
        "id": "demo-2",
        "title": "Vélo gravel aluminium taille M, Shimano 105",
        "price": 65000,
        "condition": "Bon état",
        "city": "Villeurbanne",
        "category": "velo",
        "attributes": {"bike_type": "gravel", "frame_size": "M", "groupset": "Shimano 105"},
    },
    {
        "id": "demo-3",
        "title": "Veste en laine homme taille L",
        "price": 4500,
        "condition": "Neuf avec étiquette",
        "city": "Lyon",
        "category": "vetement_marque",
        "attributes": {"size": "L", "gender": "homme", "material": "laine"},
    },
]


class DemoConnector(SourceConnector):
    code = "demo"
    platform = "any"
    capabilities = ConnectorCapabilities(search=True, fetch=True, parse_manual=True)
    enabled_in_production = False

    def _to_raw(self, item: dict) -> RawListingData:
        return RawListingData(
            platform="demo",
            connector=self.code,
            external_id=item["id"],
            url=f"https://example.invalid/annonce/{item['id']}",
            fetched_at=datetime.now(UTC),
            payload=item,
            draft=ListingDraft(
                title=item["title"],
                price_cents=item["price"],
                condition_raw=item["condition"],
                location_city=item["city"],
                category_hint=item["category"],
                attributes_hint=item["attributes"],
                seller_id=f"vendeur-{item['id']}",
            ),
        )

    def search(self, query: SearchQuery) -> Iterator[RawListingData]:
        words = query.keywords.lower().split()
        matches = [i for i in _FIXTURES if any(w in i["title"].lower() for w in words)]
        if query.max_price_cents is not None:
            matches = [i for i in matches if i["price"] <= query.max_price_cents]
        for item in matches[: query.limit]:
            yield self._to_raw(item)

    def fetch(self, ref: str) -> RawListingData:
        for item in _FIXTURES:
            if ref in (item["id"], f"https://example.invalid/annonce/{item['id']}"):
                return self._to_raw(item)
        raise KeyError(f"Annonce de démonstration introuvable : {ref}")

    def parse_manual(self, data: ManualInput) -> list[RawListingData]:
        if not data.text:
            return []
        first_line = data.text.strip().splitlines()[0]
        return [
            RawListingData(
                platform=data.platform_hint or "demo",
                connector=self.code,
                fetched_at=datetime.now(UTC),
                payload={"text": data.text},
                draft=ListingDraft(title=first_line, price_cents=0),
            )
        ]

    def healthcheck(self) -> bool:
        return True
