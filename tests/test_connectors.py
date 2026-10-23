"""Contrat des connecteurs : CHAQUE connecteur découvert est vérifié automatiquement.

Ajouter un fichier dans app/sources/ suffit pour qu'il soit testé ici.
"""

import pytest

from app.core.business_config import load_business_config
from app.core.errors import ConfigError
from app.core.settings import Settings
from app.sources.base import (
    ConnectorCapabilities,
    ManualInput,
    RawListingData,
    SearchQuery,
    SourceConnector,
)
from app.sources.registry import available_connectors, discover_connectors, get_connector

CONNECTORS = sorted(discover_connectors().items())


def test_at_least_the_demo_connector_is_discovered():
    assert "demo" in discover_connectors()


@pytest.mark.parametrize(("code", "cls"), CONNECTORS)
def test_connector_respects_contract(code, cls):
    assert issubclass(cls, SourceConnector)
    assert cls.code == code
    assert isinstance(cls.capabilities, ConnectorCapabilities)
    assert cls.min_interval_seconds >= 0
    platforms = set(load_business_config("config").platforms) | {"any"}
    assert cls.platform in platforms, f"plateforme '{cls.platform}' absente de platforms.yaml"
    assert any(cls.capabilities.model_dump().values()), "le connecteur ne sait rien faire"


def test_demo_search_returns_valid_raw_listings():
    connector = get_connector("demo")
    results = list(connector.search(SearchQuery(keywords="iphone")))
    assert len(results) == 1
    raw = results[0]
    assert isinstance(raw, RawListingData)
    assert raw.draft.price_cents == 32000
    assert len(raw.content_hash()) == 64


def test_demo_search_filters_by_price():
    connector = get_connector("demo")
    assert list(connector.search(SearchQuery(keywords="vélo", max_price_cents=10000))) == []


def test_demo_fetch_and_manual_parse():
    connector = get_connector("demo")
    assert connector.fetch("demo-2").draft.category_hint == "velo"
    parsed = connector.parse_manual(ManualInput(text="Veste laine L\n45 €", platform_hint="vinted"))
    assert parsed[0].platform == "vinted"


def test_unknown_connector_raises_clear_error():
    with pytest.raises(ConfigError, match="Connecteur inconnu"):
        get_connector("myspace")


def test_demo_connector_is_disabled_in_production():
    prod = Settings(app_env="production")
    assert "demo" not in {c.code for c in available_connectors(prod)}
