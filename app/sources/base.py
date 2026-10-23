"""CONTRAT D'INTERFACE DES CONNECTEURS DE SOURCES.

Un connecteur = un fichier Python dans `app/sources/` contenant une classe qui hérite de
`SourceConnector`. Il est découvert automatiquement par le registre (`registry.py`) :
ajouter une plateforme ne demande AUCUNE modification du reste de l'application.

Rôle du connecteur : savoir parler à UNE source (API, e-mail, texte collé…) et rendre
des `RawListingData`. Il ne calcule rien, ne score rien et n'écrit pas en base.

Partage du travail :
- le connecteur remplit `payload` (données brutes complètes) et `draft` (les champs
  standards qu'il sait lire, car lui seul connaît le format de sa plateforme) ;
- le module `normalization` fait ensuite le travail générique : état standardisé,
  pseudonymisation du vendeur, distance, dédoublonnage, historique des prix.

Règles de bonne conduite (obligatoires) :
1. Respecter les CGU de la plateforme : pas de scraping de Leboncoin / Vinted.
2. Respecter `min_interval_seconds` entre deux appels (quotas, politesse).
3. Lever `SourceTemporaryError` pour une erreur passagère (on réessaiera plus tard) et
   `SourceBlockedError` si l'accès est refusé (on s'arrête, sans insister).
4. Ne jamais remonter de données personnelles inutiles (nom, téléphone, e-mail du vendeur).
"""

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.core.settings import Settings

# --- Formats d'entrée ----------------------------------------------------------------------


class SearchQuery(BaseModel):
    """Recherche demandée à un connecteur capable de chercher (ex. API eBay)."""

    keywords: str = Field(min_length=1)
    category_code: str | None = None
    min_price_cents: int | None = Field(default=None, ge=0)
    max_price_cents: int | None = Field(default=None, ge=0)
    postal_code: str | None = None
    radius_km: float | None = Field(default=None, ge=0)
    conditions: list[str] = Field(default_factory=list)  # états standards acceptés
    local_pickup_only: bool = False
    limit: int = Field(default=50, ge=1, le=10000)  # nombre maximum d'annonces au total


class ManualInput(BaseModel):
    """Annonce fournie par l'utilisateur : texte collé, lien, capture d'écran ou e-mail."""

    text: str | None = None
    url: HttpUrl | None = None
    image_bytes: bytes | None = None
    image_mime: str | None = None
    platform_hint: str | None = None  # ex. "vinted" si l'utilisateur le précise


# --- Format de sortie standard -------------------------------------------------------------


class ListingDraft(BaseModel):
    """Champs standards lus par le connecteur. Tout est optionnel sauf le titre et le prix :
    un connecteur remplit ce qu'il sait, la normalisation complète le reste."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    price_cents: int = Field(ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    description: str | None = None
    shipping_cents: int | None = Field(default=None, ge=0)
    # État standardisé, si le connecteur le connaît avec certitude (ex. codes d'état eBay).
    # Sinon, la normalisation le déduit de `condition_raw`.
    condition: Literal["new", "like_new", "good", "fair", "for_parts", "unknown"] | None = None
    condition_raw: str | None = None
    photos: list[str] = Field(default_factory=list)
    location_city: str | None = None
    postal_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    hand_delivery: bool | None = None
    shipping_available: bool | None = None
    # Identifiant vendeur BRUT : il sera haché par la normalisation, jamais stocké en clair.
    seller_id: str | None = None
    seller_rating: float | None = Field(default=None, ge=0)
    seller_review_count: int | None = Field(default=None, ge=0)
    seller_is_pro: bool | None = None
    published_at: datetime | None = None
    category_hint: str | None = None
    attributes_hint: dict[str, Any] = Field(default_factory=dict)
    is_sold: bool = False
    sold_price_cents: int | None = Field(default=None, ge=0)


class RawListingData(BaseModel):
    """Ce que TOUT connecteur doit renvoyer pour chaque annonce."""

    platform: str
    connector: str
    external_id: str | None = None
    url: str | None = None
    fetched_at: datetime
    payload: dict[str, Any] = Field(description="Données brutes complètes, telles que reçues")
    draft: ListingDraft

    def content_hash(self) -> str:
        """Empreinte du contenu : deux réceptions identiques ne sont stockées qu'une fois."""
        blob = json.dumps(
            {
                "platform": self.platform,
                "id": self.external_id,
                "url": self.url,
                "draft": self.draft.model_dump(mode="json"),
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(blob).hexdigest()


class ConnectorCapabilities(BaseModel):
    """Ce que sait faire un connecteur. Le reste de l'app s'adapte à ces capacités."""

    search: bool = False  # chercher des annonces (surveillance automatique)
    fetch: bool = False  # récupérer une annonce par URL ou identifiant
    parse_manual: bool = False  # analyser une saisie manuelle (texte, image, e-mail)
    sold_data: bool = False  # fournir des prix réellement vendus


# --- Le contrat ----------------------------------------------------------------------------


class SourceConnector(ABC):
    """Classe de base de tous les connecteurs."""

    #: Identifiant unique du connecteur, ex. "ebay_api", "manual_text".
    code: ClassVar[str]
    #: Plateforme concernée, ex. "ebay". Doit exister dans config/platforms.yaml
    #: (sauf "any" pour un connecteur multi-plateformes comme le texte collé).
    platform: ClassVar[str]
    #: Capacités du connecteur.
    capabilities: ClassVar[ConnectorCapabilities]
    #: Délai minimal entre deux appels à la source, en secondes.
    min_interval_seconds: ClassVar[float] = 0.0
    #: False pour un connecteur de démonstration ou de test.
    enabled_in_production: ClassVar[bool] = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        """True si les secrets nécessaires (clés API…) sont présents."""
        return True

    def search(self, query: SearchQuery) -> Iterator[RawListingData]:
        raise NotImplementedError(f"{self.code} ne sait pas chercher")

    def fetch(self, ref: str) -> RawListingData:
        raise NotImplementedError(f"{self.code} ne sait pas récupérer une annonce")

    def parse_manual(self, data: ManualInput) -> list[RawListingData]:
        raise NotImplementedError(f"{self.code} ne sait pas analyser une saisie manuelle")

    @abstractmethod
    def healthcheck(self) -> bool:
        """Vérifie rapidement que la source répond (sans consommer de quota inutilement)."""
