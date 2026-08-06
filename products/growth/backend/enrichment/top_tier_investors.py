"""Curated top-tier VC list backing the `enrichment_top_tier_recent_round` signal.

v0, hand-curated from the ICP owner's Aug 2026 sprint-planning definition of "top-tier"
investor — an explicit product definition, not derived from any external ranking or
dataset. Edit TOP_TIER_VCS (and `_ALIASES` for spelling/abbreviation variants) directly
as that definition evolves; this module is the only source of truth for it.
"""

import re
from functools import lru_cache

TOP_TIER_VCS: frozenset[str] = frozenset(
    {
        "Sequoia Capital",
        "Andreessen Horowitz",
        "Benchmark",
        "Accel",
        "Founders Fund",
        "Greylock",
        "Lightspeed Venture Partners",
        "Index Ventures",
        "Kleiner Perkins",
        "Bessemer Venture Partners",
        "GV",
        "Khosla Ventures",
        "Thrive Capital",
        "ICONIQ",
        "Insight Partners",
        "General Catalyst",
        "Coatue",
        "Tiger Global",
        "Y Combinator",
        "First Round Capital",
        "Union Square Ventures",
        "Redpoint",
        "CRV",
        "Battery Ventures",
        "NEA",
        "IVP",
        "Menlo Ventures",
        "Spark Capital",
        "Felicis",
        "Craft Ventures",
        "Initialized Capital",
        "Emergence Capital",
        "Sapphire Ventures",
        "Scale Venture Partners",
        "Two Sigma Ventures",
        "DST Global",
        "SoftBank Vision Fund",
        "Addition",
        "Ribbit Capital",
        "Paradigm",
        "a16z crypto",
        "8VC",
        "Lux Capital",
        "Obvious Ventures",
        "Amplify Partners",
        "Boldstart Ventures",
        "Uncork Capital",
        "Homebrew",
        "Costanoa Ventures",
        "Wing Venture Capital",
    }
)

# Alternate spellings/abbreviations a provider might report, keyed pre-normalized (see
# _normalize) and valued with the TOP_TIER_VCS entry they stand for. Only needed where the
# two differ after normalization; exact matches need no entry.
_ALIASES: dict[str, str] = {
    "a16z": "Andreessen Horowitz",
    "yc": "Y Combinator",
    "google ventures": "GV",
    "usv": "Union Square Ventures",
    "new enterprise associates": "NEA",
    "charles river ventures": "CRV",
    "institutional venture partners": "IVP",
    "kleiner perkins caufield byers": "Kleiner Perkins",
    "insight venture partners": "Insight Partners",
    "softbank": "SoftBank Vision Fund",
    "first round": "First Round Capital",
    "greylock partners": "Greylock",
    "iconiq capital": "ICONIQ",
    "coatue management": "Coatue",
    "tiger global management": "Tiger Global",
    "felicis ventures": "Felicis",
    "wing vc": "Wing Venture Capital",
    "scale vp": "Scale Venture Partners",
    "emergence capital partners": "Emergence Capital",
    "bessemer": "Bessemer Venture Partners",
    "lightspeed": "Lightspeed Venture Partners",
    "general catalyst partners": "General Catalyst",
    "sequoia": "Sequoia Capital",
}


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name.lower())).strip()


@lru_cache(maxsize=1)
def _normalized_names() -> frozenset[str]:
    return frozenset({_normalize(name) for name in TOP_TIER_VCS} | set(_ALIASES.keys()))


def is_top_tier_investor(name: str) -> bool:
    """Case/punctuation-insensitive, alias-aware membership check against TOP_TIER_VCS."""
    if not isinstance(name, str) or not name.strip():
        return False
    return _normalize(name) in _normalized_names()
