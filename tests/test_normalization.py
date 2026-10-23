from sqlalchemy import func, select

from app.db.models import Listing, ListingPriceHistory, RawListing
from app.normalization.conditions import condition_from_ebay, condition_from_text
from app.normalization.service import ListingNormalizer, listing_key, pseudonymize
from tests.helpers import NOW, make_raw


def test_conditions_from_text():
    assert condition_from_text("Très bon état") == "like_new"
    assert condition_from_text("Neuf avec étiquette") == "new"
    assert condition_from_text("Comme neuf") == "like_new"
    assert condition_from_text("Bon état général") == "good"
    assert condition_from_text("Pour pièces, ne s'allume pas") == "for_parts"
    assert condition_from_text("état correct, quelques rayures") == "fair"
    assert condition_from_text(None) == "unknown"
    assert condition_from_text("blabla") == "unknown"


def test_conditions_from_ebay_codes():
    assert condition_from_ebay("1000") == "new"
    assert condition_from_ebay("3000") == "good"
    assert condition_from_ebay("7000") == "for_parts"
    assert condition_from_ebay("9999", "Comme neuf") == "like_new"  # code inconnu : texte


def test_new_listing_is_created_with_initial_price(db):
    result = ListingNormalizer().normalize(db, make_raw(condition_raw="Bon état"))
    assert result.is_new
    listing = result.listing
    assert listing.condition == "good"
    assert listing.status == "active"
    assert [h.price_cents for h in listing.price_history] == [30000]


def test_same_listing_twice_is_not_duplicated(db):
    normalizer = ListingNormalizer()
    normalizer.normalize(db, make_raw())
    second = normalizer.normalize(db, make_raw())
    assert not second.is_new and not second.price_changed
    assert db.scalar(select(func.count()).select_from(Listing)) == 1
    assert db.scalar(select(func.count()).select_from(RawListing)) == 1  # brut identique


def test_price_change_is_recorded(db):
    normalizer = ListingNormalizer()
    normalizer.normalize(db, make_raw(price_cents=32000))
    result = normalizer.normalize(db, make_raw(price_cents=29000))
    assert result.price_changed and result.old_price_cents == 32000
    assert result.listing.price_cents == 29000
    history = db.scalars(select(ListingPriceHistory.price_cents).order_by(ListingPriceHistory.id))
    assert list(history) == [32000, 29000]


def test_seller_is_pseudonymized(db):
    listing = ListingNormalizer().normalize(db, make_raw(seller_id="jean.dupont")).listing
    assert listing.seller_ref and "jean" not in listing.seller_ref
    assert listing.seller_ref == pseudonymize("ebay", "jean.dupont")
    assert pseudonymize("ebay", None) is None


def test_reappearing_listing_becomes_active_again(db):
    normalizer = ListingNormalizer()
    listing = normalizer.normalize(db, make_raw()).listing
    listing.status = "expired"
    db.flush()
    assert normalizer.normalize(db, make_raw()).listing.status == "active"


def test_sold_flag_marks_listing_sold(db):
    listing = ListingNormalizer().normalize(db, make_raw(is_sold=True)).listing
    assert listing.status == "sold" and listing.ended_at is not None


def test_listing_key_without_external_id():
    raw = make_raw()
    raw.external_id = None
    assert listing_key(raw).startswith("h:")
    assert listing_key(raw) == listing_key(raw.model_copy())


def test_category_from_search_is_applied(db):
    from app.core.business_config import get_business_config
    from app.db.sync import sync_categories

    sync_categories(db, get_business_config())
    listing = ListingNormalizer().normalize(db, make_raw(), category_code="smartphone").listing
    assert listing.category_code == "smartphone"
    assert listing.first_seen_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)
