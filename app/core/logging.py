"""Journalisation.

- En développement : lignes lisibles par un humain.
- En production : une ligne JSON par événement, facile à filtrer dans les journaux
  Vercel / GitHub Actions.

Utilisation dans n'importe quel module :
    from app.core.logging import get_logger
    log = get_logger(__name__)
    log.info("annonce normalisée", extra={"listing_id": 42})
"""

import json
import logging
import sys
from datetime import UTC, datetime

# Attributs standards d'un LogRecord, à ne pas recopier dans le JSON.
_STANDARD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Champs ajoutés via extra={...}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure la journalisation une fois, au démarrage de l'app ou d'une tâche."""
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
