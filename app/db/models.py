"""Modèle de données complet (voir docs/modele-de-donnees.md pour les explications).

Conventions :
- montants en CENTIMES (entiers) + devise : pas d'erreur d'arrondi ;
- dates en UTC avec fuseau ;
- listes fermées (états, statuts) stockées en texte et contrôlées par les constantes ci-dessous ;
- attributs propres à une catégorie stockés en JSON, validés par le profil YAML de la catégorie.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, IdType, JsonType, TimestampMixin

# --- Listes fermées ------------------------------------------------------------------------

CONDITIONS = ("new", "like_new", "good", "fair", "for_parts", "unknown")
RAW_STATUSES = ("pending", "normalized", "error")
LISTING_STATUSES = ("active", "sold", "removed", "expired")
OBSERVATION_SOURCES = ("active_listing", "sold_listing", "own_sale", "manual")
CRITERIA = ("margin", "reliability", "liquidity", "risk", "effort", "capital")
ALERT_STATUSES = ("pending", "sent", "failed")
ALERT_FEEDBACK = ("interested", "bought", "ignored", "bad_alert")
INVENTORY_STATUSES = ("bought", "in_repair", "listed", "reserved", "sold", "returned", "lost")
JOB_STATUSES = ("running", "success", "error")
SEARCH_RUN_STATUSES = ("running", "success", "error", "blocked", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    """Construit une contrainte CHECK 'colonne IN (...)'."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def _fk(target: str, nullable: bool = True, ondelete: str = "SET NULL"):
    return mapped_column(IdType, ForeignKey(target, ondelete=ondelete), nullable=nullable)


# --- Annonces ------------------------------------------------------------------------------


class RawListing(IdMixin, TimestampMixin, Base):
    """Annonce brute, telle que reçue d'un connecteur. Le payload est purgé après 90 jours."""

    __tablename__ = "raw_listings"
    __table_args__ = (
        CheckConstraint(_in("status", RAW_STATUSES), name="status"),
        Index("ix_raw_listings_platform_external", "platform", "external_id"),
        Index("ix_raw_listings_status", "status"),
    )

    platform: Mapped[str] = mapped_column(String(50))
    connector: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JsonType)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_run_id: Mapped[int | None] = _fk("job_runs.id")


class Listing(IdMixin, TimestampMixin, Base):
    """Annonce normalisée : une ligne par annonce réelle, mise à jour à chaque passage."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("platform", "external_id"),
        CheckConstraint(_in("status", LISTING_STATUSES), name="status"),
        CheckConstraint(_in("condition", CONDITIONS), name="condition"),
        Index("ix_listings_status_first_seen", "status", "first_seen_at"),
        Index("ix_listings_category", "category_code"),
        Index("ix_listings_product", "product_id"),
    )

    platform: Mapped[str] = mapped_column(String(50))
    # Pour une annonce sans identifiant connu (texte collé), on utilise une empreinte de l'URL.
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    shipping_cents: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(20), default="unknown")
    condition_raw: Mapped[str | None] = mapped_column(Text)

    category_code: Mapped[str | None] = mapped_column(
        ForeignKey("categories.code", ondelete="SET NULL")
    )
    product_id: Mapped[int | None] = _fk("products.id")
    product_match_confidence: Mapped[float | None] = mapped_column(Float)
    extracted_attributes: Mapped[dict] = mapped_column(JsonType, default=dict)
    photos: Mapped[list] = mapped_column(JsonType, default=list)  # URL uniquement

    location_city: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    hand_delivery: Mapped[bool | None] = mapped_column(Boolean)
    shipping_available: Mapped[bool | None] = mapped_column(Boolean)

    # RGPD : identifiant vendeur PSEUDONYMISÉ (haché), jamais nom, téléphone ou e-mail.
    seller_ref: Mapped[str | None] = mapped_column(String(64))
    seller_rating: Mapped[float | None] = mapped_column(Float)
    seller_review_count: Mapped[int | None] = mapped_column(Integer)
    seller_is_pro: Mapped[bool | None] = mapped_column(Boolean)

    status: Mapped[str] = mapped_column(String(20), default="active")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Dernière vérification du statut auprès de la source, et date de fin (vendue, retirée…)
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_listing_id: Mapped[int | None] = _fk("raw_listings.id")

    product: Mapped["Product | None"] = relationship(back_populates="listings")
    price_history: Mapped[list["ListingPriceHistory"]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    scores: Mapped[list["Score"]] = relationship(back_populates="listing")


class ListingPriceHistory(IdMixin, Base):
    """Une ligne uniquement quand le prix d'une annonce change."""

    __tablename__ = "listing_price_history"
    __table_args__ = (Index("ix_price_history_listing_date", "listing_id", "observed_at"),)

    listing_id: Mapped[int] = _fk("listings.id", nullable=False, ondelete="CASCADE")
    price_cents: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    listing: Mapped[Listing] = relationship(back_populates="price_history")


# --- Produits et catégories ----------------------------------------------------------------


class Category(TimestampMixin, Base):
    """Copie en base des fichiers config/categories/*.yaml (garantit l'intégrité des liens)."""

    __tablename__ = "categories"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    parent_code: Mapped[str | None] = mapped_column(
        ForeignKey("categories.code", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120))
    profile_hash: Mapped[str | None] = mapped_column(String(64))


class Product(IdMixin, TimestampMixin, Base):
    """Référence générique (ex. « iPhone 13 128 Go »). Plusieurs annonces → un produit."""

    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_cat_brand_model", "category_code", "brand", "model"),
        Index(
            "ix_products_attributes_gin",
            "attributes",
            postgresql_using="gin",
            # Index GIN : PostgreSQL uniquement (ignoré sous SQLite).
            postgresql_ops={"attributes": "jsonb_path_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    category_code: Mapped[str] = mapped_column(ForeignKey("categories.code"))
    brand: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(200))
    variant: Mapped[str | None] = mapped_column(String(200))
    canonical_name: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JsonType, default=dict)
    identifiers: Mapped[dict] = mapped_column(JsonType, default=dict)  # EAN, MPN…
    # Clé normalisée catégorie + marque + modèle + attributs qui font varier le prix.
    fingerprint: Mapped[str] = mapped_column(String(300), unique=True)

    listings: Mapped[list[Listing]] = relationship(back_populates="product")
    observations: Mapped[list["PriceObservation"]] = relationship(back_populates="product")


class PriceObservation(IdMixin, TimestampMixin, Base):
    """Un prix connu pour un produit : le carburant du moteur d'estimation."""

    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint(_in("source_type", OBSERVATION_SOURCES), name="source_type"),
        CheckConstraint(_in("condition", CONDITIONS), name="condition"),
        CheckConstraint("quality >= 0 AND quality <= 1", name="quality_range"),
        Index("ix_observations_product_cond_date", "product_id", "condition", "observed_at"),
    )

    product_id: Mapped[int] = _fk("products.id", nullable=False, ondelete="CASCADE")
    listing_id: Mapped[int | None] = _fk("listings.id")
    source_type: Mapped[str] = mapped_column(String(20))
    platform: Mapped[str] = mapped_column(String(50))
    condition: Mapped[str] = mapped_column(String(20), default="unknown")
    price_cents: Mapped[int] = mapped_column(Integer)
    sold_price_cents: Mapped[int | None] = mapped_column(Integer)
    shipping_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    days_to_sell: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[float] = mapped_column(Float, default=0.5)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)

    product: Mapped[Product] = relationship(back_populates="observations")


class Estimate(IdMixin, Base):
    """Estimation du prix de revente, mise en cache."""

    __tablename__ = "estimates"
    __table_args__ = (
        CheckConstraint(_in("condition", CONDITIONS), name="condition"),
        Index("ix_estimates_product_cond_date", "product_id", "condition", "computed_at"),
    )

    product_id: Mapped[int] = _fk("products.id", nullable=False, ondelete="CASCADE")
    condition: Mapped[str] = mapped_column(String(20))
    price_low_cents: Mapped[int] = mapped_column(Integer)
    price_median_cents: Mapped[int] = mapped_column(Integer)
    price_high_cents: Mapped[int] = mapped_column(Integer)
    sell_days_estimate: Mapped[int | None] = mapped_column(Integer)
    comparables_count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(50))
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Score ---------------------------------------------------------------------------------


class Score(IdMixin, Base):
    """Score d'opportunité, historisé et relié aux réglages exacts utilisés."""

    __tablename__ = "scores"
    __table_args__ = (
        CheckConstraint("total >= 0 AND total <= 100", name="total_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_scores_listing_date", "listing_id", "computed_at"),
        Index(
            "ix_scores_current_total",
            "total",
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
    )

    listing_id: Mapped[int] = _fk("listings.id", nullable=False, ondelete="CASCADE")
    estimate_id: Mapped[int | None] = _fk("estimates.id")
    total: Mapped[int] = mapped_column(SmallInteger)
    confidence: Mapped[float] = mapped_column(Float)
    confidence_label: Mapped[str] = mapped_column(String(10))
    net_margin_cents: Mapped[int | None] = mapped_column(Integer)
    roi_pct: Mapped[float | None] = mapped_column(Float)
    cost_breakdown: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    strengths: Mapped[list] = mapped_column(JsonType, default=list)
    weaknesses: Mapped[list] = mapped_column(JsonType, default=list)
    engine_version: Mapped[str] = mapped_column(String(30))
    config_snapshot_id: Mapped[int | None] = _fk("config_snapshots.id")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    listing: Mapped[Listing] = relationship(back_populates="scores")
    criteria: Mapped[list["ScoreCriterion"]] = relationship(
        back_populates="score", cascade="all, delete-orphan"
    )


class ScoreCriterion(IdMixin, Base):
    """Détail d'un critère du score : valeur brute, sous-score, poids, explication."""

    __tablename__ = "score_criteria"
    __table_args__ = (
        UniqueConstraint("score_id", "criterion"),
        CheckConstraint(_in("criterion", CRITERIA), name="criterion"),
        CheckConstraint("sub_score >= 0 AND sub_score <= 100", name="sub_score_range"),
    )

    score_id: Mapped[int] = _fk("scores.id", nullable=False, ondelete="CASCADE")
    criterion: Mapped[str] = mapped_column(String(20))
    raw_value: Mapped[float | None] = mapped_column(Float)
    raw_unit: Mapped[str | None] = mapped_column(String(20))
    sub_score: Mapped[int] = mapped_column(SmallInteger)
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    flags: Mapped[list] = mapped_column(JsonType, default=list)

    score: Mapped[Score] = relationship(back_populates="criteria")


# --- Recherches et alertes -----------------------------------------------------------------


class SavedSearch(IdMixin, TimestampMixin, Base):
    """Recherche enregistrée. Source de vérité : config/searches.yaml (synchronisé ici)."""

    __tablename__ = "saved_searches"

    code: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str] = mapped_column(Text)
    connectors: Mapped[list] = mapped_column(JsonType, default=list)
    category_code: Mapped[str | None] = mapped_column(
        ForeignKey("categories.code", ondelete="SET NULL")
    )
    min_price_cents: Mapped[int | None] = mapped_column(Integer)
    max_price_cents: Mapped[int | None] = mapped_column(Integer)
    conditions: Mapped[list] = mapped_column(JsonType, default=list)
    local_pickup_only: Mapped[bool] = mapped_column(Boolean, default=False)
    postal_code: Mapped[str | None] = mapped_column(String(10))
    radius_km: Mapped[float | None] = mapped_column(Float)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    filters: Mapped[dict] = mapped_column(JsonType, default=dict)  # filtres additionnels
    min_score: Mapped[int | None] = mapped_column(SmallInteger)
    min_margin_cents: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListingSearch(Base):
    """Lien annonce <-> recherche : quelles recherches ont trouvé quelle annonce, et quand.

    Sert à détecter les annonces disparues (plus revues par la recherche qui les trouvait).
    """

    __tablename__ = "listing_searches"
    __table_args__ = (
        Index("ix_listing_searches_search_last", "saved_search_id", "last_matched_at"),
    )

    listing_id: Mapped[int] = mapped_column(
        IdType, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    saved_search_id: Mapped[int] = mapped_column(
        IdType, ForeignKey("saved_searches.id", ondelete="CASCADE"), primary_key=True
    )
    first_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchRun(IdMixin, Base):
    """Une exécution d'une recherche sur une source : le journal lisible de la collecte."""

    __tablename__ = "search_runs"
    __table_args__ = (
        CheckConstraint(_in("status", SEARCH_RUN_STATUSES), name="status"),
        Index("ix_search_runs_started", "started_at"),
        Index("ix_search_runs_connector_started", "connector", "started_at"),
    )

    job_run_id: Mapped[int | None] = _fk("job_runs.id")
    saved_search_id: Mapped[int | None] = _fk("saved_searches.id")
    connector: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    found: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    price_changes: Mapped[int] = mapped_column(Integer, default=0)
    disappeared: Mapped[int] = mapped_column(Integer, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class SourceState(TimestampMixin, Base):
    """État de santé et quota de chaque source (une ligne par connecteur)."""

    __tablename__ = "source_states"

    connector: Mapped[str] = mapped_column(String(50), primary_key=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Quota : nombre d'appels consommés le jour `calls_day` (remis à zéro chaque jour, UTC).
    calls_day: Mapped[str | None] = mapped_column(String(10))
    calls_today: Mapped[int] = mapped_column(Integer, default=0)


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # Anti-doublon : jamais deux alertes pour la même annonce et la même recherche.
        UniqueConstraint("saved_search_id", "listing_id"),
        CheckConstraint(_in("status", ALERT_STATUSES), name="status"),
        CheckConstraint("feedback IS NULL OR " + _in("feedback", ALERT_FEEDBACK), name="feedback"),
    )

    saved_search_id: Mapped[int | None] = _fk("saved_searches.id", ondelete="CASCADE")
    listing_id: Mapped[int] = _fk("listings.id", nullable=False, ondelete="CASCADE")
    score_id: Mapped[int | None] = _fk("scores.id")
    channel: Mapped[str] = mapped_column(String(20), default="telegram")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    telegram_message_id: Mapped[str | None] = mapped_column(String(50))
    feedback: Mapped[str | None] = mapped_column(String(20))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


# --- Achats, ventes, stock -----------------------------------------------------------------


class InventoryItem(IdMixin, TimestampMixin, Base):
    """Un objet physique en ta possession."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint(_in("status", INVENTORY_STATUSES), name="status"),
        CheckConstraint(_in("condition", CONDITIONS), name="condition"),
        Index("ix_inventory_status", "status"),
    )

    title: Mapped[str] = mapped_column(Text)
    listing_id: Mapped[int | None] = _fk("listings.id")
    product_id: Mapped[int | None] = _fk("products.id")
    category_code: Mapped[str | None] = mapped_column(
        ForeignKey("categories.code", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="bought")
    condition: Mapped[str] = mapped_column(String(20), default="unknown")
    storage_location: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list] = mapped_column(JsonType, default=list)

    purchase: Mapped["Purchase | None"] = relationship(back_populates="item")
    sale: Mapped["Sale | None"] = relationship(back_populates="item")
    costs: Mapped[list["ItemCost"]] = relationship(back_populates="item")


class Purchase(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchases"

    inventory_item_id: Mapped[int] = mapped_column(
        IdType, ForeignKey("inventory_items.id", ondelete="CASCADE"), unique=True
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    platform: Mapped[str | None] = mapped_column(String(50))
    price_cents: Mapped[int] = mapped_column(Integer)
    buyer_fees_cents: Mapped[int] = mapped_column(Integer, default=0)
    shipping_cents: Mapped[int] = mapped_column(Integer, default=0)
    travel_km: Mapped[float | None] = mapped_column(Float)
    travel_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Score au moment de l'achat : permet de comparer prédiction et réalité.
    score_id: Mapped[int | None] = _fk("scores.id")

    item: Mapped[InventoryItem] = relationship(back_populates="purchase")


class Sale(IdMixin, TimestampMixin, Base):
    """Vente réelle. Aucune donnée sur l'acheteur n'est stockée (RGPD)."""

    __tablename__ = "sales"

    inventory_item_id: Mapped[int] = mapped_column(
        IdType, ForeignKey("inventory_items.id", ondelete="CASCADE"), unique=True
    )
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    platform: Mapped[str] = mapped_column(String(50))
    price_cents: Mapped[int] = mapped_column(Integer)
    platform_fees_cents: Mapped[int] = mapped_column(Integer, default=0)
    shipping_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    packaging_cents: Mapped[int] = mapped_column(Integer, default=0)

    item: Mapped[InventoryItem] = relationship(back_populates="sale")


class ItemCost(IdMixin, TimestampMixin, Base):
    """Frais annexes d'un objet : réparation, pièces, nettoyage…"""

    __tablename__ = "item_costs"

    inventory_item_id: Mapped[int] = _fk("inventory_items.id", nullable=False, ondelete="CASCADE")
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(30))
    amount_cents: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    item: Mapped[InventoryItem] = relationship(back_populates="costs")


# --- Tables techniques ---------------------------------------------------------------------


class Setting(TimestampMixin, Base):
    """Réglages personnels modifiables depuis l'interface (priorité sur les YAML)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JsonType)


class ConfigSnapshot(IdMixin, Base):
    """Copie figée de la configuration utilisée pour calculer des scores."""

    __tablename__ = "config_snapshots"

    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    content: Mapped[dict] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRun(IdMixin, Base):
    """Journal des tâches planifiées (GitHub Actions)."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="status"),
        Index("ix_job_runs_name_started", "job_name", "started_at"),
    )

    job_name: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class AiUsage(IdMixin, Base):
    """Chaque appel IA est compté : sert à faire respecter le plafond mensuel."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_created", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(50))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    listing_id: Mapped[int | None] = _fk("listings.id")
