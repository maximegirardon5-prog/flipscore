"""Paramètres techniques et secrets, lus depuis les variables d'environnement.

Ordre de lecture : variables d'environnement (Vercel, GitHub Actions) puis fichier `.env`
local. Aucun secret ne doit être écrit en dur dans le code.

Les réglages *métier* (frais, pondérations, catégories) ne sont pas ici : ils vivent dans
les fichiers YAML du dossier `config/` (voir `app/core/business_config.py`).
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./flipscore.db"
    log_level: str = "INFO"
    config_dir: str = "config"

    web_password: SecretStr = SecretStr("change-moi")

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    ai_provider: Literal["none", "gemini"] = "none"
    ai_api_key: SecretStr | None = None
    ai_monthly_budget_cents: int = 0

    ebay_client_id: str | None = None
    ebay_client_secret: SecretStr | None = None
    # "production" pour les vraies annonces, "sandbox" pour l'environnement de test d'eBay.
    ebay_env: Literal["production", "sandbox"] = "production"

    # Sel secret utilisé pour pseudonymiser les identifiants vendeurs (hachage).
    # À définir une fois en production, puis à ne plus changer.
    pseudonymization_salt: SecretStr = SecretStr("dev-salt-a-changer")

    gmail_address: str | None = None
    gmail_app_password: SecretStr | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Renvoie les paramètres (lus une seule fois puis mis en cache)."""
    return Settings()
