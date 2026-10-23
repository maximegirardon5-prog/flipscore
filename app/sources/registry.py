"""Registre des connecteurs : découverte automatique des plugins de `app/sources/`.

Tout module de ce dossier qui définit une sous-classe de `SourceConnector` avec un `code`
est enregistré. Il suffit donc de déposer un fichier pour ajouter une source.
"""

import importlib
import inspect
import pkgutil
from functools import lru_cache

import app.sources as sources_pkg
from app.core.errors import ConfigError
from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.sources.base import SourceConnector

log = get_logger(__name__)

_INTERNAL_MODULES = {"base", "registry"}


@lru_cache
def discover_connectors() -> dict[str, type[SourceConnector]]:
    """Importe chaque module de app/sources et renvoie {code: classe}."""
    found: dict[str, type[SourceConnector]] = {}
    for mod_info in pkgutil.iter_modules(sources_pkg.__path__):
        if mod_info.name in _INTERNAL_MODULES or mod_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{sources_pkg.__name__}.{mod_info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, SourceConnector)
                and cls is not SourceConnector
                and not inspect.isabstract(cls)
                and cls.__module__ == module.__name__
            ):
                if cls.code in found:
                    raise ConfigError(f"Deux connecteurs utilisent le code '{cls.code}'")
                found[cls.code] = cls
                log.debug("connecteur découvert", extra={"connector": cls.code})
    return found


def get_connector(code: str, settings: Settings | None = None) -> SourceConnector:
    """Instancie un connecteur par son code."""
    connectors = discover_connectors()
    if code not in connectors:
        raise ConfigError(f"Connecteur inconnu : '{code}'. Disponibles : {sorted(connectors)}")
    return connectors[code](settings or get_settings())


def available_connectors(settings: Settings | None = None) -> list[SourceConnector]:
    """Connecteurs utilisables dans l'environnement courant (configurés et autorisés)."""
    settings = settings or get_settings()
    result = []
    for cls in discover_connectors().values():
        if settings.is_production and not cls.enabled_in_production:
            continue
        connector = cls(settings)
        if connector.is_configured():
            result.append(connector)
    return result
