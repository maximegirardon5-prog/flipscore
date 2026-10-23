"""Synchronise la table `categories` avec les fichiers config/categories/*.yaml."""

import hashlib
import json

from sqlalchemy.orm import Session

from app.core.business_config import BusinessConfig
from app.core.logging import get_logger
from app.db.models import Category

log = get_logger(__name__)


def sync_categories(db: Session, config: BusinessConfig) -> int:
    """Crée ou met à jour une ligne par catégorie. Ne supprime rien (l'historique y fait
    référence). Renvoie le nombre de catégories créées ou modifiées."""
    changed = 0
    # Parents d'abord, pour respecter la clé étrangère parent_code.
    profiles = sorted(config.categories.values(), key=lambda p: p.parent is not None)
    for profile in profiles:
        digest = hashlib.sha256(
            json.dumps(profile.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        row = db.get(Category, profile.code)
        if row is None:
            db.add(
                Category(
                    code=profile.code,
                    name=profile.name,
                    parent_code=profile.parent,
                    profile_hash=digest,
                )
            )
            changed += 1
        elif row.profile_hash != digest:
            row.name, row.parent_code, row.profile_hash = profile.name, profile.parent, digest
            changed += 1
        db.flush()
    log.info("catégories synchronisées", extra={"changed": changed})
    return changed
