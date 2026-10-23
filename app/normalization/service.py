"""Normalisation : RawListingData -> ligne `listings`.

Pour chaque annonce reçue :
1. archive la version brute (`raw_listings`), sauf si strictement identique à une version déjà
   reçue (empreinte du contenu) ;
2. crée ou met à jour l'annonce normalisée, unique par (plateforme, identifiant) ;
3. enregistre le changement de prix dans `listing_price_history` ;
4. remet en « active » une annonce qu'on croyait disparue et qui réapparaît.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.models import Listing, ListingPriceHistory, RawListing
from app.normalization.conditions import condition_from_text
from app.sources.base import RawListingData

log = get_logger(__name__)


@dataclass
class NormalizationResult:
    listing: Listing
    is_new: bool
    price_changed: bool
    old_price_cents: int | None = None


def pseudonymize(platform: str, seller_id: str | None) -> str | None:
    """Hache l'identifiant vendeur avec un sel secret : on peut reconnaître un même vendeur
    sans jamais stocker son pseudo (RGPD)."""
    if not seller_id:
        return None
    salt = get_settings().pseudonymization_salt.get_secret_value()
    return hashlib.sha256(f"{salt}|{platform}|{seller_id}".encode()).hexdigest()


def listing_key(raw: RawListingData) -> str:
    """Identifiant stable de l'annonce : celui de la plateforme, sinon une empreinte de l'URL,
    sinon une empreinte du titre et du prix (texte collé sans lien)."""
    if raw.external_id:
        return raw.external_id
    basis = raw.url or f"{raw.draft.title}|{raw.draft.price_cents}"
    return "h:" + hashlib.sha256(basis.encode()).hexdigest()[:40]


class ListingNormalizer:
    def normalize(
        self, db: Session, raw: RawListingData, category_code: str | None = None
    ) -> NormalizationResult:
        now = raw.fetched_at
        draft = raw.draft
        raw_row = self._archive_raw(db, raw)

        external_id = listing_key(raw)
        listing = db.scalar(
            select(Listing).where(
                Listing.platform == raw.platform, Listing.external_id == external_id
            )
        )
        condition = draft.condition or condition_from_text(draft.condition_raw)
        category = category_code or draft.category_hint
        status = "sold" if draft.is_sold else "active"

        fields = dict(
            url=raw.url,
            title=draft.title,
            description=draft.description,
            currency=draft.currency,
            shipping_cents=draft.shipping_cents,
            condition=condition,
            condition_raw=draft.condition_raw,
            photos=draft.photos,
            location_city=draft.location_city,
            postal_code=draft.postal_code,
            lat=draft.lat,
            lon=draft.lon,
            hand_delivery=draft.hand_delivery,
            shipping_available=draft.shipping_available,
            seller_ref=pseudonymize(raw.platform, draft.seller_id),
            seller_rating=draft.seller_rating,
            seller_review_count=draft.seller_review_count,
            seller_is_pro=draft.seller_is_pro,
            published_at=draft.published_at,
            raw_listing_id=raw_row.id if raw_row else None,
        )

        if listing is None:
            listing = Listing(
                platform=raw.platform,
                external_id=external_id,
                price_cents=draft.price_cents,
                category_code=category,
                extracted_attributes=draft.attributes_hint,
                status=status,
                first_seen_at=now,
                last_seen_at=now,
                ended_at=now if draft.is_sold else None,
                **fields,
            )
            listing.price_history.append(
                ListingPriceHistory(price_cents=draft.price_cents, observed_at=now)
            )
            db.add(listing)
            db.flush()
            return NormalizationResult(listing=listing, is_new=True, price_changed=False)

        # Annonce déjà connue : mise à jour sans effacer ce qu'on savait déjà.
        for key, value in fields.items():
            if value is not None and value != []:
                setattr(listing, key, value)
        if category and not listing.category_code:
            listing.category_code = category
        if draft.attributes_hint:
            listing.extracted_attributes = {**listing.extracted_attributes, **draft.attributes_hint}
        listing.last_seen_at = now
        if draft.is_sold:
            listing.status, listing.ended_at = "sold", listing.ended_at or now
        elif listing.status in ("removed", "expired"):
            listing.status, listing.ended_at = "active", None  # réapparue

        old_price = listing.price_cents
        price_changed = draft.price_cents != old_price and draft.price_cents > 0
        if price_changed:
            listing.price_cents = draft.price_cents
            listing.price_history.append(
                ListingPriceHistory(price_cents=draft.price_cents, observed_at=now)
            )
            log.info(
                "changement de prix",
                extra={"listing_id": listing.id, "old": old_price, "new": draft.price_cents},
            )
        db.flush()
        return NormalizationResult(
            listing=listing,
            is_new=False,
            price_changed=price_changed,
            old_price_cents=old_price if price_changed else None,
        )

    @staticmethod
    def _archive_raw(db: Session, raw: RawListingData) -> RawListing | None:
        """Archive la version brute. Une version identique déjà reçue n'est pas dupliquée."""
        digest = raw.content_hash()
        existing = db.scalar(select(RawListing).where(RawListing.content_hash == digest))
        if existing:
            return existing
        row = RawListing(
            platform=raw.platform,
            connector=raw.connector,
            external_id=raw.external_id,
            url=raw.url,
            payload=raw.payload,
            content_hash=digest,
            status="normalized",
            fetched_at=raw.fetched_at,
        )
        db.add(row)
        db.flush()
        return row


def mark_ended(listing: Listing, status: str, when: datetime) -> None:
    """Marque une annonce comme terminée : sold (vendue), removed (retirée), expired."""
    listing.status = status
    listing.ended_at = listing.ended_at or when
    listing.status_checked_at = when
