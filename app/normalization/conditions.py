"""Traduction des états d'annonce (texte libre, codes eBay) vers les états standards :
new, like_new, good, fair, for_parts, unknown."""

import re
import unicodedata

# Codes d'état eBay (conditionId) -> état standard.
EBAY_CONDITION_IDS = {
    "1000": "new",  # Neuf
    "1500": "new",  # Neuf autre (sans emballage)
    "1750": "new",  # Neuf avec défauts
    "2000": "like_new",  # Reconditionné certifié
    "2010": "like_new",  # Reconditionné excellent
    "2020": "good",  # Reconditionné très bon
    "2030": "good",  # Reconditionné bon
    "2500": "like_new",  # Reconditionné par le vendeur
    "2750": "like_new",  # Comme neuf
    "2990": "good",  # Occasion excellent (cartes, etc.)
    "3000": "good",  # Occasion
    "3010": "fair",  # Occasion bon
    "4000": "good",  # Très bon état
    "5000": "good",  # Bon état
    "6000": "fair",  # État acceptable
    "7000": "for_parts",  # Pour pièces ou ne fonctionne pas
}

# Règles par mots-clés, testées dans l'ordre : la première qui correspond l'emporte.
# L'ordre compte : « pour pièces » avant « bon état », « comme neuf » avant « neuf ».
_RULES: list[tuple[str, str]] = [
    (
        r"pour pieces|hors service|\bhs\b|ne fonctionne pas|ne s'allume pas|en panne|defectueux",
        "for_parts",
    ),
    (
        r"comme neuf|tres bon etat|excellent etat|parfait etat|etat neuf|jamais porte|"
        r"neuf sans etiquette|reconditionne",
        "like_new",
    ),
    (r"\bneuf\b|neuve|sous blister|avec etiquette|jamais servi|scelle", "new"),
    (r"bon etat|occasion|tres bon|porte quelques fois|legeres traces", "good"),
    (r"etat correct|etat moyen|satisfaisant|acceptable|usure|traces d'usage|rayures", "fair"),
]
_COMPILED = [(re.compile(pattern), cond) for pattern, cond in _RULES]


def _fold(text: str) -> str:
    """Minuscules sans accents, pour comparer « Très bon état » et « tres bon etat »."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def condition_from_text(text: str | None) -> str:
    if not text:
        return "unknown"
    folded = _fold(text)
    for pattern, condition in _COMPILED:
        if pattern.search(folded):
            return condition
    return "unknown"


def condition_from_ebay(condition_id: str | None, label: str | None = None) -> str:
    if condition_id and condition_id in EBAY_CONDITION_IDS:
        return EBAY_CONDITION_IDS[condition_id]
    return condition_from_text(label)
