"""Configuration métier : fichiers YAML du dossier `config/`.

Pourquoi des fichiers YAML ?
- modifiables depuis le site GitHub, sans toucher au code ;
- historique et retour arrière gratuits (Git) ;
- validés par les tests AVANT mise en ligne : une faute de frappe ne casse pas l'app.

Structure :
    config/scoring.yaml        pondérations par défaut, seuils de confiance et d'alerte
    config/platforms.yaml      frais par plateforme
    config/defaults.yaml       réglages personnels par défaut (surchargés par la table `settings`)
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

    @property
    def price_relevant_attributes(self) -> list[str]:
        return sorted(k for k, spec in self.attributes.items() if spec.price_relevant)


# --- Ensemble ------------------------------------------------------------------------------


class BusinessConfig(BaseModel):
    scoring: ScoringConfig
    platforms: dict[str, Platform]
    defaults: PersonalDefaults
    categories: dict[str, CategoryProfile]

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

    return BusinessConfig(
        scoring=scoring, platforms=platforms, defaults=defaults, categories=categories
    )


@lru_cache
def get_business_config() -> BusinessConfig:
    from app.core.settings import get_settings

    return load_business_config(get_settings().config_dir)
