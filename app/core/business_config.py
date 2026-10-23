"""Configuration métier : fichiers YAML du dossier `config/`.

Pourquoi des fichiers YAML ?
- modifiables depuis le site GitHub, sans toucher au code ;
- historique et retour arrière gratuits (Git) ;
- validés par les tests AVANT mise en ligne : une faute de frappe ne casse pas l'app.

Structure :
    config/scoring.yaml        pondérations par défaut, seuils de confiance et d'alerte
    config/platforms.yaml      frais par plateforme
    config/defaults.yaml       réglages personnels par défaut (surchargés par la table `settings`)
    config/collection.yaml     réglages de la collecte (fréquences, quotas, pannes, expiration)
    config/searches.yaml       recherches enregistrées (mots-clés, catégorie, zone, budget)
    config/categories/*.yaml   un fichier par catégorie (= un plugin de catégorie)

Ordre de priorité des réglages : table `settings` > YAML de la catégorie > YAML par défaut.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.errors import ConfigError

CRITERIA = ("margin", "reliability", "liquidity", "risk", "effort", "capital")
CONDITIONS = ("new", "like_new", "good", "fair", "for_parts", "unknown")


class _Strict(BaseModel):
    # Refuse les clés inconnues : une faute de frappe ("wieght") est signalée, pas ignorée.
    model_config = ConfigDict(extra="forbid")


# --- Scoring -------------------------------------------------------------------------------


class Weights(_Strict):
    """Poids des critères. Ils sont renormalisés pour que leur somme fasse 1."""

    margin: float = Field(ge=0)
    reliability: float = Field(ge=0)
    liquidity: float = Field(ge=0)
    risk: float = Field(ge=0)
    effort: float = Field(ge=0)
    capital: float = Field(ge=0)

    @model_validator(mode="after")
    def _not_all_zero(self) -> "Weights":
        if sum(self.as_dict().values()) <= 0:
            raise ValueError("au moins un poids doit être positif")
        return self

    def as_dict(self) -> dict[str, float]:
        return {c: getattr(self, c) for c in CRITERIA}

    def normalized(self) -> dict[str, float]:
        total = sum(self.as_dict().values())
        return {c: w / total for c, w in self.as_dict().items()}


class PartialWeights(_Strict):
    """Surcharge partielle des poids par une catégorie."""

    margin: float | None = Field(default=None, ge=0)
    reliability: float | None = Field(default=None, ge=0)
    liquidity: float | None = Field(default=None, ge=0)
    risk: float | None = Field(default=None, ge=0)
    effort: float | None = Field(default=None, ge=0)
    capital: float | None = Field(default=None, ge=0)


class ConfidenceThresholds(_Strict):
    low_below: float = Field(ge=0, le=1)
    high_from: float = Field(ge=0, le=1)


class AlertDefaults(_Strict):
    min_score: int = Field(ge=0, le=100)
    min_margin_cents: int = Field(ge=0)
    min_confidence: float = Field(ge=0, le=1)


class ScoringConfig(_Strict):
    engine_version: str
    weights: Weights
    confidence: ConfidenceThresholds
    alerts: AlertDefaults


# --- Plateformes ---------------------------------------------------------------------------


class PlatformFees(_Strict):
    seller_fee_pct: float = Field(ge=0, le=100, description="Commission vendeur en %")
    seller_fixed_fee_cents: int = Field(ge=0, default=0)
    buyer_fee_pct: float = Field(ge=0, le=100, default=0)
    buyer_fixed_fee_cents: int = Field(ge=0, default=0)
    payment_fee_pct: float = Field(ge=0, le=100, default=0)


class Platform(_Strict):
    name: str
    access_mode: list[Literal["api", "manual", "email", "extension"]]
    fees: PlatformFees
    can_buy: bool = True
    can_sell: bool = True
    notes: str = ""


# --- Réglages personnels par défaut --------------------------------------------------------


class PersonalDefaults(_Strict):
    home_postal_code: str | None = None
    max_distance_km: float = Field(ge=0)
    fuel_cost_cents_per_km: int = Field(ge=0)
    hourly_rate_cents: int = Field(ge=0, description="Valeur de ton heure de travail")
    storage_capacity: Literal["low", "medium", "high"]
    tax_rate_pct: float = Field(ge=0, le=100, description="0 tant que tu es particulier")
    default_packaging_cents: int = Field(ge=0)


# --- Catégories (plugins) ------------------------------------------------------------------


class AttributeSpec(_Strict):
    type: Literal["int", "float", "text", "bool", "choice"]
    required: bool = False
    price_relevant: bool = False
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _choices_for_choice(self) -> "AttributeSpec":
        if self.type == "choice" and not self.choices:
            raise ValueError("un attribut de type 'choice' doit lister ses 'choices'")
        return self


class CategoryProfile(_Strict):
    code: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    parent: str | None = None
    keywords: list[str] = Field(default_factory=list, description="Aide à reconnaître la catégorie")
    attributes: dict[str, AttributeSpec] = Field(default_factory=dict)
    resale_platforms: list[str] = Field(default_factory=list)
    typical_shipping_cents: int = Field(ge=0, default=0)
    packaging_cents: int | None = Field(default=None, ge=0)
    repair_reserve_pct: float = Field(ge=0, le=100, default=0)
    typical_days_to_sell: int = Field(ge=0, default=14)
    storage_volume: Literal["small", "medium", "large"] = "small"
    risk_keywords: list[str] = Field(default_factory=list)
    counterfeit_risk: Literal["low", "medium", "high"] = "low"
    weights: PartialWeights | None = None
    # Catégories eBay (identifiants « feuilles ») pour affiner les recherches eBay. Optionnel.
    ebay_category_ids: list[str] = Field(default_factory=list)

    @property
    def price_relevant_attributes(self) -> list[str]:
        return sorted(k for k, spec in self.attributes.items() if spec.price_relevant)


# --- Collecte ------------------------------------------------------------------------------


class EbayCollection(_Strict):
    marketplace_id: str = Field(pattern=r"^EBAY_[A-Z]{2}$")
    item_location_country: str = Field(pattern=r"^[A-Z]{2}$")
    daily_call_budget: int = Field(ge=1, le=5000, description="Plafond d'appels par jour")
    page_size: int = Field(ge=1, le=200)
    max_pages_per_search: int = Field(ge=1, le=50)
    buying_options: list[Literal["FIXED_PRICE", "AUCTION", "BEST_OFFER", "CLASSIFIED_AD"]] = Field(
        default_factory=list
    )


class Disappearance(_Strict):
    check_after_hours: int = Field(ge=1)
    max_checks_per_run: int = Field(ge=0)
    expire_unverifiable_after_days: int = Field(ge=1)


class CircuitBreaker(_Strict):
    failures_before_pause: int = Field(ge=1)
    base_pause_minutes: int = Field(ge=1)
    max_pause_hours: int = Field(ge=1)


class CollectionConfig(_Strict):
    default_interval_minutes: int = Field(ge=60)
    raw_payload_retention_days: int = Field(ge=1)
    ebay: EbayCollection
    disappearance: Disappearance
    circuit_breaker: CircuitBreaker


class SearchSpec(_Strict):
    """Une recherche enregistrée (config/searches.yaml)."""

    code: str = Field(pattern=r"^[a-z0-9_]+$", description="Identifiant stable, ne pas changer")
    name: str
    keywords: str = Field(min_length=2)
    category: str | None = None
    connectors: list[str] = Field(min_length=1)
    max_price_eur: float | None = Field(default=None, ge=0)
    min_price_eur: float | None = Field(default=None, ge=0)
    conditions: list[Literal[CONDITIONS]] = Field(default_factory=list)  # type: ignore[valid-type]
    interval_minutes: int | None = Field(default=None, ge=60)
    local_pickup_only: bool = False
    postal_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    radius_km: float | None = Field(default=None, gt=0, le=500)
    active: bool = True

    @model_validator(mode="after")
    def _price_range(self) -> "SearchSpec":
        if (
            self.min_price_eur is not None
            and self.max_price_eur is not None
            and self.min_price_eur > self.max_price_eur
        ):
            raise ValueError("min_price_eur doit être inférieur à max_price_eur")
        return self


class SearchesFile(_Strict):
    searches: list[SearchSpec] = Field(default_factory=list)


# --- Ensemble ------------------------------------------------------------------------------


class BusinessConfig(BaseModel):
    scoring: ScoringConfig
    platforms: dict[str, Platform]
    defaults: PersonalDefaults
    categories: dict[str, CategoryProfile]
    collection: CollectionConfig
    searches: list[SearchSpec]

    def weights_for(self, category_code: str | None) -> dict[str, float]:
        """Poids effectifs (normalisés) pour une catégorie : défaut + surcharge catégorie."""
        merged = self.scoring.weights.as_dict()
        profile = self.categories.get(category_code) if category_code else None
        if profile and profile.weights:
            merged.update(profile.weights.model_dump(exclude_none=True))
        return Weights(**merged).normalized()

    def content_hash(self) -> str:
        """Empreinte de la configuration : sert à relier chaque score aux réglages utilisés."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()


def _read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"Fichier de configuration manquant : {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML invalide dans {path} : {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} doit contenir un dictionnaire YAML")
    return data


def _validate(model: type[BaseModel], data: dict, path: Path):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Configuration invalide dans {path} :\n{e}") from e


def load_business_config(config_dir: str | Path = "config") -> BusinessConfig:
    """Lit et valide tous les fichiers YAML. Lève ConfigError avec un message clair."""
    root = Path(config_dir)

    scoring = _validate(ScoringConfig, _read_yaml(root / "scoring.yaml"), root / "scoring.yaml")
    defaults = _validate(
        PersonalDefaults, _read_yaml(root / "defaults.yaml"), root / "defaults.yaml"
    )

    platforms_raw = _read_yaml(root / "platforms.yaml")
    platforms = {
        code: _validate(Platform, data, root / "platforms.yaml")
        for code, data in platforms_raw.items()
    }

    categories: dict[str, CategoryProfile] = {}
    for path in sorted((root / "categories").glob("*.yaml")):
        profile = _validate(CategoryProfile, _read_yaml(path), path)
        if profile.code in categories:
            raise ConfigError(f"Code de catégorie en double : {profile.code} ({path})")
        if path.stem != profile.code:
            raise ConfigError(f"{path} : le nom du fichier doit être '{profile.code}.yaml'")
        categories[profile.code] = profile

    # Vérifications croisées entre fichiers.
    for profile in categories.values():
        if profile.parent and profile.parent not in categories:
            raise ConfigError(f"Catégorie '{profile.code}' : parent inconnu '{profile.parent}'")
        for p in profile.resale_platforms:
            if p not in platforms:
                raise ConfigError(
                    f"Catégorie '{profile.code}' : plateforme de revente inconnue '{p}'"
                )

    collection = _validate(
        CollectionConfig, _read_yaml(root / "collection.yaml"), root / "collection.yaml"
    )
    searches_file = _validate(
        SearchesFile, _read_yaml(root / "searches.yaml"), root / "searches.yaml"
    )
    seen_codes: set[str] = set()
    for search in searches_file.searches:
        if search.code in seen_codes:
            raise ConfigError(f"searches.yaml : code de recherche en double '{search.code}'")
        seen_codes.add(search.code)
        if search.category and search.category not in categories:
            raise ConfigError(
                f"searches.yaml : recherche '{search.code}', catégorie inconnue '{search.category}'"
            )
        if search.local_pickup_only and not (search.postal_code or defaults.home_postal_code):
            raise ConfigError(
                f"searches.yaml : recherche '{search.code}' en main propre sans code postal "
                "(renseigne postal_code ici ou home_postal_code dans defaults.yaml)"
            )

    return BusinessConfig(
        scoring=scoring,
        platforms=platforms,
        defaults=defaults,
        categories=categories,
        collection=collection,
        searches=searches_file.searches,
    )


@lru_cache
def get_business_config() -> BusinessConfig:
    from app.core.settings import get_settings

    return load_business_config(get_settings().config_dir)
