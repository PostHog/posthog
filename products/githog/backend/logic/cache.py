"""Redis-backed cache for PRImpactReport.

Computing a blast radius involves several HogQL queries plus a multi-turn
LLM call — 5-30 seconds end to end. Caching keeps revisits snappy and
makes "manual refresh" the explicit gesture for forcing recomputation.

Keying strategy: ``(team_id, repository, pr_number, lookback_days)``.
The repo + PR number identify the PR; lookback is part of the key so
different windows are independently cached. Diff content is *not* part
of the key — when a new commit lands on the PR, the user can click
refresh; we deliberately don't auto-invalidate, since on-push refetch
would re-trigger the expensive LLM call.

TTL is 24 hours: long enough that revisiting a PR feels instant, short
enough that stale data on long-lived branches eventually self-heals.

Failures are logged and swallowed. A broken cache must never block the
computation path.
"""

import pickle
import logging
from typing import TYPE_CHECKING

from django.core.cache import cache

if TYPE_CHECKING:
    from ..facade.contracts import PRImpactReport


logger = logging.getLogger(__name__)


# Bump this when PRImpactReport / nested contracts change shape, so old
# pickled blobs aren't unpickled against an incompatible schema.
_CACHE_VERSION = "v3"
_CACHE_TTL_SECONDS = 24 * 60 * 60


def impact_cache_key(team_id: int, repository: str, pr_number: int, lookback_days: int) -> str:
    """Stable cache key for a (team, repo, PR, window) tuple."""
    # Repository is `owner/name` — case-insensitive on GitHub. Lowercasing avoids
    # cache misses when the caller capitalizes the org differently than GitHub does.
    safe_repo = repository.lower().replace(" ", "_")
    return f"githog:impact:{_CACHE_VERSION}:{team_id}:{safe_repo}:{pr_number}:{lookback_days}"


def get_cached_impact(key: str) -> "PRImpactReport | None":
    """Return the cached report or None on miss / unpickle error."""
    try:
        raw = cache.get(key)
    except Exception:
        logger.warning("githog: impact cache get failed", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return pickle.loads(raw)
    except Exception:
        # Schema drift or corrupted blob — treat as a miss and let the caller recompute.
        logger.warning("githog: impact cache unpickle failed, treating as miss", exc_info=True)
        return None


def set_cached_impact(key: str, report: "PRImpactReport") -> None:
    """Store a freshly-computed report. Cache failures are logged, never raised."""
    try:
        cache.set(key, pickle.dumps(report), timeout=_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("githog: impact cache set failed", exc_info=True)
