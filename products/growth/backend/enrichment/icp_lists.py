"""RevOps-curated lists for ICP fit scoring: the container, the loader, and the sheet-export parsers.

The curated tag buckets and quality-investor names live in versioned IcpScoringConfig rows
(rails are code; brains are rows — the EnrichmentPromptConfig precedent), so RevOps'
quarterly review lands without a deploy and the internal sheets never get committed to this
public repo. This module turns the active row into the frozen CuratedLists the scorer
consumes, normalized once at load, cached with a short TTL so the signup path doesn't
re-read the row per score while a newly-activated row still takes effect within a minute.

No active row means fit scoring is skipped (callers degrade to writing firmographics with
no score) — never a crash and never a silently empty-list score, which would floor the
Capital/AIPilled/SoftwareRelevance components for every org and look like a real
evaluation.

Django-free at import on purpose: the scorer and its tests import CuratedLists/norm from
here, and only load_active_lists touches the ORM (lazily), so the pure scoring path never
drags model imports in.
"""

import time
import typing
import threading
import dataclasses
from collections import Counter
from typing import Any, Optional

if typing.TYPE_CHECKING:
    from products.growth.backend.models import IcpScoringConfig

# Buckets a tag row's recommendation may name; anything else (e.g. "ignore") is skipped.
TAG_BUCKETS = frozenset({"dq", "capital_quality", "software_positive", "software_negative", "ai_positive"})

# The one non-bucket recommendation value the sheet uses deliberately; not a typo to flag.
_IGNORE_RECOMMENDATION = "ignore"

_CACHE_TTL_SECONDS = 60

_cache_lock = threading.Lock()
_cached: Optional[tuple[float, Optional["CuratedLists"]]] = None


def norm(value: Optional[str]) -> str:
    """Case + and/& normalization for tag and investor matching."""
    return (value or "").lower().replace(" and ", " & ").strip()


@dataclasses.dataclass(frozen=True)
class CuratedLists:
    """The RevOps-curated tag buckets and quality-investor names, pre-normalized via norm().

    Built from the active IcpScoringConfig row; tests construct small synthetic instances
    directly. dq/software_negative are curation metadata carried for auditability — the
    scoring formula does not read them today.
    """

    version: str
    capital_quality: frozenset[str] = frozenset()
    ai_positive: frozenset[str] = frozenset()
    software_positive: frozenset[str] = frozenset()
    software_negative: frozenset[str] = frozenset()
    dq: frozenset[str] = frozenset()
    quality_investors: frozenset[str] = frozenset()


def build_curated_lists(config: "IcpScoringConfig") -> CuratedLists:
    """Parse one config row's JSON into pre-normalized frozensets.

    Malformed rows are skipped rather than raising: a partially-bad sheet export should
    degrade to a slightly smaller list, not take down scoring.
    """
    buckets: dict[str, set[str]] = {bucket: set() for bucket in TAG_BUCKETS}
    for row in config.tags if isinstance(config.tags, list) else []:
        if not isinstance(row, dict):
            continue
        tag = norm(row.get("tag"))
        if not tag:
            continue
        for bucket in str(row.get("recommendation") or "").split("+"):
            bucket = bucket.strip().lower()
            if bucket in buckets:
                buckets[bucket].add(tag)

    investors: set[str] = set()
    for row in config.quality_investors if isinstance(config.quality_investors, list) else []:
        if not isinstance(row, dict):
            continue
        name = norm(row.get("investor"))
        if name:
            investors.add(name)
        aliases = row.get("aliases")
        for alias in aliases if isinstance(aliases, list) else []:
            alias = norm(alias if isinstance(alias, str) else None)
            if alias:
                investors.add(alias)

    return CuratedLists(
        version=config.version,
        capital_quality=frozenset(buckets["capital_quality"]),
        ai_positive=frozenset(buckets["ai_positive"]),
        software_positive=frozenset(buckets["software_positive"]),
        software_negative=frozenset(buckets["software_negative"]),
        dq=frozenset(buckets["dq"]),
        quality_investors=frozenset(investors),
    )


def load_active_lists() -> Optional[CuratedLists]:
    """The active config row as CuratedLists, or None when no row is active."""
    from products.growth.backend.models import (
        IcpScoringConfig,  # noqa: PLC0415 — keep this module Django-free at import
    )

    global _cached
    with _cache_lock:
        if _cached is not None and time.monotonic() - _cached[0] < _CACHE_TTL_SECONDS:
            return _cached[1]

    config = IcpScoringConfig.objects.filter(is_active=True).first()
    lists = build_curated_lists(config) if config is not None else None

    # Stamp the entry after the query so a slow read can't silently shrink the TTL.
    now = time.monotonic()
    with _cache_lock:
        _cached = (now, lists)
    return lists


def clear_lists_cache() -> None:
    """Test hook; also useful right after activating a new row from a shell."""
    global _cached
    with _cache_lock:
        _cached = None


def parse_tags_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize RevOps' tag-sheet export rows into the stored shape.

    Applies the one standing import-time decision (Mine, 2026-08-13): AI Grant batch tags
    count as BOTH quality capital and AI signal, whatever single bucket the sheet assigned —
    stored rows then carry the effective assignment visibly instead of hiding it in loader
    code.
    """
    stored = []
    for row in rows:
        tag = (row.get("tag") or "").strip()
        if not tag:
            continue
        recommendation = (row.get("recommendation") or "").strip()
        if norm(tag).startswith("ai grant batch"):
            # Normalize tokens the same way build_curated_lists does, so a cased/spaced
            # sheet export ("Capital_Quality ") keeps its buckets through this rewrite.
            effective = {
                normalized
                for bucket in recommendation.split("+")
                if (normalized := bucket.strip().lower()) in TAG_BUCKETS
            }
            effective.update({"capital_quality", "ai_positive"})
            recommendation = "+".join(sorted(effective))
        stored.append(
            {
                "tag": tag,
                "type": (row.get("type") or "").strip(),
                "recommendation": recommendation,
                "reason": (row.get("reason") or "").strip(),
                "note": (row.get("note") or "").strip(),
            }
        )
    return stored


def unrecognized_recommendation_tokens(tags: list[dict[str, Any]]) -> Counter[str]:
    """Count recommendation tokens that match neither a TAG_BUCKETS bucket nor "ignore".

    Normalizes the same way build_curated_lists does, so a token this misses is exactly one
    that would otherwise silently drop out of every bucket at load time.
    """
    counts: Counter[str] = Counter()
    for row in tags:
        for token in str(row.get("recommendation") or "").split("+"):
            token = token.strip().lower()
            if token and token not in TAG_BUCKETS and token != _IGNORE_RECOMMENDATION:
                counts[token] += 1
    return counts


def parse_investors_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize RevOps' investor-sheet export rows ("aliases" pipe-separated) into the stored shape."""
    stored = []
    for row in rows:
        investor = (row.get("investor") or "").strip()
        if not investor:
            continue
        aliases = [alias.strip() for alias in (row.get("aliases") or "").split("|") if alias.strip()]
        stored.append({"investor": investor, "aliases": aliases, "notes": (row.get("notes") or "").strip()})
    return stored
