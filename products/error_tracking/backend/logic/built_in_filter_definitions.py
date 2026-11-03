"""Definitions of the built-in suppression filters.

A team that turns a filter on gets one `ErrorTrackingSuppressionRule` row with the filter's key
and a hash of the filters it was built from.
The refresh workflow rewrites every row whose hash differs from the current definition,
so a change here, including a change to the bot list it reads, reaches every team without a manual step.
The error tracking Temporal worker redeploys only when a file in its path filter changes,
so the errorTracking filter in .github/workflows/container-images-cd.yml must list every file
outside this product that the definitions read.

Every pattern here comes from PostHog's own data or from public facts:
React's error decoder pages, bundler and browser error text, and browser release history.
"""

import json
import hashlib
from typing import Any

from posthog.dataclasses import frozen

from products.web_analytics.backend.facade.bot_definitions import bot_user_agent_patterns

# The Rust HogVM caches a compiled regex only up to this length and compiles a longer one on every event.
# Keep in sync with MAX_CACHEABLE_PATTERN_LEN in rust/common/hogvm/src/util.rs.
MAX_CACHED_REGEX_LENGTH = 1024

# AI assistants fetch pages for a person, and generic HTTP libraries also send requests from real apps and SDKs.
_EXCLUDED_BOT_CATEGORIES = frozenset({"ai_assistant", "http_client"})

# React's decoder codes for hydration mismatches: https://react.dev/errors
_REACT_HYDRATION_ERROR_CODES = (418, 419, 421, 422, 423, 425)

# The browsers that bundlers such as Vite targeted by default for ES2020 output, plus Internet Explorer.
# Each pattern matches a major version below the cutoff, whether the SDK sends the version as a number or a string.
_LEGACY_BROWSER_VERSION_PATTERNS = {
    "Chrome": r"^(?:[0-9]|[1-7][0-9]|8[0-6])(?:\.|$)",
    "Microsoft Edge": r"^(?:[0-9]|[1-7][0-9]|8[0-7])(?:\.|$)",
    "Firefox": r"^(?:[0-9]|[1-6][0-9]|7[0-7])(?:\.|$)",
    "Safari": r"^(?:[0-9]|1[0-3])(?:\.|$)",
    "Mobile Safari": r"^(?:[0-9]|1[0-3])(?:\.|$)",
    "Opera": r"^(?:[0-9]|[1-6][0-9]|7[0-2])(?:\.|$)",
}
_ALWAYS_LEGACY_BROWSERS = ("Internet Explorer", "Internet Explorer Mobile")

_LOCAL_URL_PATTERN = r"(?i)^(?:file:|https?://(?:localhost|[^/?#]*\.localhost|127(?:\.[0-9]{1,3}){3}|0\.0\.0\.0|\[::1\])(?::[0-9]+)?(?:[/?#]|$))"


@frozen
class BuiltInFilter:
    key: str
    name: str
    description: str
    filters: dict[str, Any]

    @property
    def filters_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.filters, sort_keys=True).encode()).hexdigest()


def _leaf(key: str, operator: str, value: str | list[str]) -> dict[str, Any]:
    return {"key": key, "type": "event", "operator": operator, "value": value}


def chunk_alternation(patterns: list[str], max_length: int = MAX_CACHED_REGEX_LENGTH) -> list[str]:
    """Join patterns into as few `(?:a)|(?:b)` alternations as fit within `max_length` each."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for pattern in patterns:
        group = f"(?:{pattern})"
        if len(group) > max_length:
            raise ValueError(f"Pattern is longer than {max_length} characters: {pattern}")
        added_length = len(group) + (1 if current else 0)
        if current and current_length + added_length > max_length:
            chunks.append("|".join(current))
            current = []
            current_length = 0
            added_length = len(group)
        current.append(group)
        current_length += added_length
    if current:
        chunks.append("|".join(current))
    return chunks


def _web_crawler_filters() -> dict[str, Any]:
    patterns = bot_user_agent_patterns(exclude_categories=_EXCLUDED_BOT_CATEGORIES)
    return {
        "type": "OR",
        "values": [_leaf("$raw_user_agent", "regex", chunk) for chunk in chunk_alternation(patterns)],
    }


def _legacy_browser_filters() -> dict[str, Any]:
    groups: list[dict[str, Any]] = [
        {"type": "AND", "values": [_leaf("$browser", "exact", list(_ALWAYS_LEGACY_BROWSERS))]},
    ]
    groups.extend(
        {
            "type": "AND",
            "values": [_leaf("$browser", "exact", [browser]), _leaf("$browser_version", "regex", version_pattern)],
        }
        for browser, version_pattern in _LEGACY_BROWSER_VERSION_PATTERNS.items()
    )
    return {"type": "OR", "values": groups}


def _react_hydration_filters() -> dict[str, Any]:
    needles = [
        needle
        for code in _REACT_HYDRATION_ERROR_CODES
        for needle in (f"react.dev/errors/{code}", f"reactjs.org/docs/error-decoder.html?invariant={code}")
    ]
    return {"type": "OR", "values": [_leaf("$exception_values", "icontains", needles)]}


BUILT_IN_FILTERS: tuple[BuiltInFilter, ...] = (
    BuiltInFilter(
        key="web_crawlers",
        name="Web crawlers and bots",
        description="Drop exceptions from search engines, AI crawlers, uptime monitors and headless browsers.",
        filters=_web_crawler_filters(),
    ),
    BuiltInFilter(
        key="localhost",
        name="Local development",
        description="Drop exceptions from pages on localhost, a loopback address or a file: URL.",
        filters={"type": "OR", "values": [_leaf("$current_url", "regex", _LOCAL_URL_PATTERN)]},
    ),
    BuiltInFilter(
        key="legacy_browsers",
        name="Legacy browsers",
        description=(
            "Drop exceptions from Internet Explorer, Chrome before 87, Edge before 88, Firefox before 78, "
            "Safari before 14 and Opera before 73."
        ),
        filters=_legacy_browser_filters(),
    ),
    BuiltInFilter(
        key="react_hydration_errors",
        name="React hydration errors",
        description="Drop React errors about server-rendered HTML that doesn't match the page in the browser.",
        filters=_react_hydration_filters(),
    ),
    BuiltInFilter(
        key="chunk_load_errors",
        name="Chunk load errors",
        description="Drop errors from lazy-loaded scripts that fail to load, which often happens after a deploy.",
        filters={
            "type": "OR",
            "values": [
                _leaf("$exception_types", "exact", ["ChunkLoadError"]),
                _leaf(
                    "$exception_values",
                    "icontains",
                    [
                        # Chromium, Firefox and Safari word a failed dynamic import differently.
                        "Failed to fetch dynamically imported module",
                        "error loading dynamically imported module",
                        "Importing a module script failed",
                    ],
                ),
            ],
        },
    ),
    BuiltInFilter(
        key="resize_observer_loop",
        name="ResizeObserver loop errors",
        description="Drop the ResizeObserver loop warning that browsers report as an error.",
        filters={"type": "OR", "values": [_leaf("$exception_values", "icontains", ["ResizeObserver loop"])]},
    ),
)

BUILT_IN_FILTERS_BY_KEY: dict[str, BuiltInFilter] = {f.key: f for f in BUILT_IN_FILTERS}
