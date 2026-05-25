"""Canonical metadata for native marketing integrations: snake-case keys, display
names, and the static UTM aliases used to recognize ad-platform traffic.

Keep alias keys lowercase and alphanumeric-only — `normalize()` strips everything
else before lookup.
"""

from collections.abc import Iterator, Mapping
from functools import cache
from types import MappingProxyType
from typing import Literal

from posthog.schema import NativeMarketingSource

NativeIntegration = Literal[
    "google_ads",
    "meta_ads",
    "bing_ads",
    "linkedin_ads",
    "reddit_ads",
    "pinterest_ads",
    "snapchat_ads",
    "tiktok_ads",
]


# Mapping from NativeMarketingSource to the snake-case key used everywhere
# downstream (URL params, scope hints, suggestion targets).
NATIVE_TO_KEY: dict[NativeMarketingSource, NativeIntegration] = {
    NativeMarketingSource.GOOGLE_ADS: "google_ads",
    NativeMarketingSource.META_ADS: "meta_ads",
    NativeMarketingSource.BING_ADS: "bing_ads",
    NativeMarketingSource.LINKEDIN_ADS: "linkedin_ads",
    NativeMarketingSource.REDDIT_ADS: "reddit_ads",
    NativeMarketingSource.PINTEREST_ADS: "pinterest_ads",
    NativeMarketingSource.SNAPCHAT_ADS: "snapchat_ads",
    NativeMarketingSource.TIK_TOK_ADS: "tiktok_ads",
}

KEY_TO_NATIVE: dict[NativeIntegration, NativeMarketingSource] = {v: k for k, v in NATIVE_TO_KEY.items()}


# Mapping from `ExternalDataSource.source_type` (PascalCase strings the DW
# layer uses) to NativeMarketingSource. Pinned explicitly because
# ExternalDataSourceType has many non-marketing entries.
EXTERNAL_SOURCE_TYPE_TO_NATIVE: dict[str, NativeMarketingSource] = {
    "GoogleAds": NativeMarketingSource.GOOGLE_ADS,
    "MetaAds": NativeMarketingSource.META_ADS,
    "BingAds": NativeMarketingSource.BING_ADS,
    "LinkedinAds": NativeMarketingSource.LINKEDIN_ADS,
    "RedditAds": NativeMarketingSource.REDDIT_ADS,
    "PinterestAds": NativeMarketingSource.PINTEREST_ADS,
    "SnapchatAds": NativeMarketingSource.SNAPCHAT_ADS,
    "TikTokAds": NativeMarketingSource.TIK_TOK_ADS,
}

# Human-facing names for surfaces that produce text (LLMs, UI, error messages).
DISPLAY_NAMES: dict[NativeMarketingSource, str] = {
    NativeMarketingSource.GOOGLE_ADS: "Google Ads",
    NativeMarketingSource.META_ADS: "Meta Ads",
    NativeMarketingSource.BING_ADS: "Bing Ads",
    NativeMarketingSource.LINKEDIN_ADS: "LinkedIn Ads",
    NativeMarketingSource.REDDIT_ADS: "Reddit Ads",
    NativeMarketingSource.PINTEREST_ADS: "Pinterest Ads",
    NativeMarketingSource.SNAPCHAT_ADS: "Snapchat Ads",
    NativeMarketingSource.TIK_TOK_ADS: "TikTok Ads",
}


def display_name_for_key(key: NativeIntegration) -> str:
    return DISPLAY_NAMES[KEY_TO_NATIVE[key]]


def normalize(value: str) -> str:
    """Lowercase and strip non-alphanumerics. `Facebook-Ads` → `facebookads`."""
    return "".join(c.lower() for c in value if c.isalnum())


def _build_canonical_aliases() -> dict[str, NativeIntegration]:
    """Build the alias table from `INTEGRATION_DEFAULT_SOURCES` (the source of truth
    shared with adapters and the dashboard, so they agree on what's integrated).

    Lazy to avoid a circular import: the constants module imports services
    indirectly during Django app boot.
    """
    from products.marketing_analytics.backend.hogql_queries.constants import INTEGRATION_DEFAULT_SOURCES

    out: dict[str, NativeIntegration] = {}
    for native, defaults in INTEGRATION_DEFAULT_SOURCES.items():
        target = NATIVE_TO_KEY.get(native)
        if target is None:
            continue
        for value in defaults:
            out[normalize(value)] = target
    return out


@cache
def canonical_source_aliases() -> Mapping[str, NativeIntegration]:
    """Canonical alias table from the official `*DefaultSources` enums. Cached and
    returned as a read-only `MappingProxyType`; keys are normalized."""
    return MappingProxyType(_build_canonical_aliases())


def lookup_alias(raw_utm_source: str) -> NativeIntegration | None:
    """Exact hit against the canonical alias table only. To also honor a team's
    `custom_source_mappings`, use `build_combined_alias_map` + `lookup_in`."""
    return canonical_source_aliases().get(normalize(raw_utm_source))


@cache
def aliases_for(integration: NativeIntegration) -> frozenset[str]:
    """All known raw values resolving to this integration (normalized).

    Cached — `attribution_health` and `mapping_suggester` call this in tight loops.
    """
    return frozenset(alias for alias, target in canonical_source_aliases().items() if target == integration)


def iter_custom_source_mappings(
    custom_source_mappings: dict | None,
) -> Iterator[tuple[NativeIntegration, str]]:
    """Yield (target_native_key, raw_utm_source) pairs from a team's
    `custom_source_mappings`, skipping unknown integration types.

    Single source of truth for iterating the config — both the alias map and
    `utm_audit` consume this so enum-resolution rules don't drift.
    """
    if not custom_source_mappings:
        return
    for integration_type, custom_sources in custom_source_mappings.items():
        try:
            native = NativeMarketingSource(integration_type)
        except ValueError:
            continue
        target = NATIVE_TO_KEY.get(native)
        if target is None:
            continue
        for raw in custom_sources or []:
            if not raw:
                continue
            yield target, str(raw)


def build_combined_alias_map(custom_source_mappings: dict | None) -> dict[str, NativeIntegration]:
    """Merge the canonical alias table with the team's `custom_source_mappings`.

    The team config keys are PascalCase NativeMarketingSource values (e.g.
    'GoogleAds') and the values are arbitrary user-configured raw utm_source
    strings (e.g. `['meta2', 'fb-paid']`). We normalize keys consistently so a
    single dict lookup answers the question.

    Team mappings WIN over the canonical table — a user can override `fb` to
    point somewhere unusual if they really want to.
    """
    combined: dict[str, NativeIntegration] = dict(canonical_source_aliases())
    for target, raw in iter_custom_source_mappings(custom_source_mappings):
        combined[normalize(raw)] = target
    return combined


def lookup_in(value: str, alias_map: dict[str, NativeIntegration]) -> NativeIntegration | None:
    """Lookup against a precomputed alias map (typically from `build_combined_alias_map`)."""
    return alias_map.get(normalize(value))
