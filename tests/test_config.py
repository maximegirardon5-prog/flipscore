"""Les fichiers YAML du dossier config/ sont valides, et les erreurs sont bien détectées."""

import pytest

from app.core.business_config import CRITERIA, load_business_config
from app.core.errors import ConfigError


def test_real_config_is_valid():
    cfg = load_business_config("config")
    assert {"smartphone", "velo", "vetement_marque"} <= set(cfg.categories)
    assert {"ebay", "vinted", "leboncoin"} <= set(cfg.platforms)


def test_weights_are_normalized_and_overridden_by_category():
    cfg = load_business_config("config")
    default = cfg.weights_for(None)
    phone = cfg.weights_for("smartphone")
    assert set(default) == set(CRITERIA)
    assert sum(default.values()) == pytest.approx(1.0)
    assert sum(phone.values()) == pytest.approx(1.0)
    # Le profil smartphone renforce le poids du risque.
    assert phone["risk"] > default["risk"]


def test_price_relevant_attributes():
    cfg = load_business_config("config")
    assert "storage_gb" in cfg.categories["smartphone"].price_relevant_attributes
    assert "color" not in cfg.categories["smartphone"].price_relevant_attributes


def test_config_hash_changes_when_config_changes(config_copy):
    before = load_business_config(config_copy).content_hash()
    path = config_copy / "scoring.yaml"
    path.write_text(path.read_text().replace("margin: 0.35", "margin: 0.40"))
    assert load_business_config(config_copy).content_hash() != before


@pytest.mark.parametrize(
    ("file", "old", "new", "message"),
    [
        ("scoring.yaml", "margin: 0.35", "margni: 0.35", "margni"),  # faute de frappe
        ("categories/velo.yaml", "code: velo", "code: velo\nparent: inconnu", "parent inconnu"),
        ("categories/velo.yaml", "[leboncoin, ebay]", "[leboncoin, selency]", "selency"),
        ("defaults.yaml", "max_distance_km: 30", "max_distance_km: -5", "max_distance_km"),
        ("scoring.yaml", "weights:", "weights: [", "YAML invalide"),
    ],
)
def test_invalid_config_is_rejected_with_clear_message(config_copy, file, old, new, message):
    path = config_copy / file
    path.write_text(path.read_text().replace(old, new, 1))
    with pytest.raises(ConfigError, match=message):
        load_business_config(config_copy)


def test_category_file_name_must_match_code(config_copy):
    (config_copy / "categories" / "velo.yaml").rename(config_copy / "categories" / "bike.yaml")
    with pytest.raises(ConfigError, match="nom du fichier"):
        load_business_config(config_copy)


def test_new_category_needs_only_a_yaml_file(config_copy):
    (config_copy / "categories" / "console.yaml").write_text(
        "code: console\nname: Consoles\n"
        "attributes:\n  model: { type: text, required: true, price_relevant: true }\n"
    )
    assert "console" in load_business_config(config_copy).categories
