"""Country-name to ISO 3166-1 alpha-2 mapping for provider responses.

Providers (Harmonic) return long English country names; the `icp_country` group
property holds ISO alpha-2 codes. The base mapping comes from babel's CLDR
territory data (already a dependency), inverted name->code; `_ALIASES` covers
provider spellings where CLDR prefers a different form (e.g. CLDR says
"Türkiye" and "Hong Kong SAR China").
"""

from functools import lru_cache
from typing import Optional

from babel import Locale

_ALIASES: dict[str, str] = {
    "united states of america": "US",
    "usa": "US",
    "united kingdom of great britain and northern ireland": "GB",
    "uk": "GB",
    "turkey": "TR",
    "hong kong": "HK",
    "macau": "MO",
    "palestine": "PS",
    "ivory coast": "CI",
    "cape verde": "CV",
    "democratic republic of the congo": "CD",
    "republic of the congo": "CG",
    "laos": "LA",
    "brunei": "BN",
    "syria": "SY",
    "tanzania": "TZ",
    "moldova": "MD",
    "north korea": "KP",
}


def _normalize(name: str) -> str:
    # CLDR spells names like "Côte d'Ivoire" with a typographic apostrophe (U+2019);
    # providers send a straight one. Fold them so both forms resolve.
    return name.strip().lower().replace("’", "'")


@lru_cache(maxsize=1)
def _name_to_code() -> dict[str, str]:
    # Lazy so importing this module stays off the django.setup() hot path.
    territories = Locale("en").territories
    inverted = {_normalize(name): code for code, name in territories.items() if len(code) == 2 and code.isalpha()}
    return {**inverted, **_ALIASES}


def country_name_to_iso_code(name: Optional[str]) -> Optional[str]:
    """Return the ISO alpha-2 code for a provider country name, or None when unmapped."""
    if not name or not isinstance(name, str):
        return None
    normalized = _normalize(name)
    mapping = _name_to_code()
    if len(normalized) == 2 and normalized.upper() in mapping.values():
        return normalized.upper()
    return mapping.get(normalized)
