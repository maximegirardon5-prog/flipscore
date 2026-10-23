"""Le schéma fonctionne de bout en bout : de l'annonce au profit réel."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.business_config import get_business_config
from app.db import models as m
from app.db.sync import sync_categories

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _listing(**kw) -> m.Listing:
    data = dict(
        platform="ebay",
        external_id="123",
        title="iPhone 13",
        price_cents=30000,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    data.update(kw)
    return m.Listing(**data)


def test_sync_categories_is_idempotent(db):
    cfg = get_business_config()
    assert sync_categories(db, cfg) == len(cfg.categories)
    assert sync_categories(db, cfg) == 0  # deuxième passage : rien ne change
    assert db.get(m.Category, "velo").name == "Vélos"


def test_full_chain_listing_product_score(db):
    sync_categories(db, get_business_config())
    product = m.Product(
        category_code="smartphone",
        brand="Apple",
        model="iPhone 13",
        canonical_name="iPhone 13 128 Go",
        attributes={"storage_gb": 128},
        fingerprint="smartphone|apple|iphone 13|storage_gb=128",
    )
    listing = _listing(
        category_code="smartphone",
        product=product,
        extracted_attributes={"storage_gb": 128, "battery_health": 88},
    )
    listing.price_history.append(m.ListingPriceHistory(price_cents=32000, observed_at=NOW))
    listing.price_history.append(m.ListingPriceHistory(price_cents=30000, observed_at=NOW))
    db.add(listing)
    db.flush()

    score = m.Score(
        listing_id=listing.id,
        total=78,
        confidence=0.6,
        confidence_label="moyenne",
        summary="Bonne affaire",
        engine_version="test",
        computed_at=NOW,
    )
    score.criteria.append(
        m.ScoreCriterion(
            criterion="margin", sub_score=80, weight=0.35, contribution=28, explanation="Marge 85 €"
        )
    )
    db.add(score)
    db.flush()

    assert listing.product.canonical_name == "iPhone 13 128 Go"
    assert len(listing.price_history) == 2
    assert listing.scores[0].criteria[0].criterion == "margin"


def test_same_listing_cannot_be_inserted_twice(db):
    db.add(_listing())
    db.flush()
    db.add(_listing())
    with pytest.raises(IntegrityError):
        db.flush()


def test_invalid_condition_is_rejected(db):
    db.add(_listing(condition="cassé"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_alert_is_never_duplicated(db):
    listing = _listing()
    search = m.SavedSearch(name="iPhone", query="iphone 13")
    db.add_all([listing, search])
    db.flush()
    db.add(m.Alert(saved_search_id=search.id, listing_id=listing.id))
    db.flush()
    db.add(m.Alert(saved_search_id=search.id, listing_id=listing.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_profit_view_computes_real_profit(db):
    item = m.InventoryItem(title="Vélo gravel", status="sold")
    item.purchase = m.Purchase(
        purchased_at=NOW,
        price_cents=50000,
        buyer_fees_cents=0,
        shipping_cents=0,
        travel_cost_cents=1000,
    )
    item.costs.append(m.ItemCost(date=NOW, type="repair", amount_cents=2500))
    item.sale = m.Sale(
        sold_at=NOW,
        platform="leboncoin",
        price_cents=70000,
        platform_fees_cents=0,
        shipping_cost_cents=0,
        packaging_cents=0,
    )
    db.add(item)
    db.flush()

    row = db.execute(
        text("SELECT profit_cents FROM v_item_profit WHERE inventory_item_id = :id"),
        {"id": item.id},
    ).one()
    # 700 € vente − 500 € achat − 10 € trajet − 25 € réparation = 165 €
    assert row.profit_cents == 16500


def test_json_attributes_roundtrip(db):
    sync_categories(db, get_business_config())
    db.add(
        m.Product(
            category_code="velo",
            canonical_name="Gravel M",
            attributes={"bike_type": "gravel", "frame_size": "M", "electric": False},
            fingerprint="velo|gravel|m",
        )
    )
    db.flush()
    product = db.scalars(select(m.Product)).one()
    assert product.attributes["frame_size"] == "M"
