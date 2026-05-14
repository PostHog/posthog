"""Redis-backed cache for githog widget responses.

Two flavours:

- ``impact_cache_*`` — pickled PRImpactReport (binary, pydantic-shaped). A
  blast-radius computation is 5-30s of HogQL + multi-turn LLM, so this
  cache is essential. Keyed by ``(team, repo, pr, lookback_days)``.

- ``pr_response_cache_*`` — JSON-encoded plain dicts for the cheap-but-
  still-GitHub-API-bound endpoints (``/pull_request``, ``/pull_request_diff``).
  Used so revisiting a PR you've already opened is instant rather than
  re-hitting GitHub for metadata + files + diff every time.

In both cases failures are logged and swallowed — a broken cache must
never block the computation path.
"""

import json
import pickle
import logging
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

if TYPE_CHECKING:
    from ..facade.contracts import PRImpactReport


logger = logging.getLogger(__name__)


# Bump this when PRImpactReport / nested contracts change shape, so old
# pickled blobs aren't unpickled against an incompatible schema.
_CACHE_VERSION = "v4"
_CACHE_TTL_SECONDS = 24 * 60 * 60

# Separate version + TTL for the PR-response cache. TTL is shorter (1 hour)
# because PRs accumulate commits and comments and we don't want to serve
# week-old metadata when someone revisits.
_PR_RESPONSE_VERSION = "v1"
_PR_RESPONSE_TTL_SECONDS = 60 * 60


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


def pr_response_cache_key(endpoint: str, team_id: int, repository: str, pr_number: int) -> str:
    """Cache key for a per-PR JSON response (PR detail, PR diff, …).

    ``endpoint`` is a short name like ``"basic"`` or ``"diff"`` to keep
    different response shapes in distinct slots.
    """
    safe_repo = repository.lower().replace(" ", "_")
    return f"githog:pr_response:{_PR_RESPONSE_VERSION}:{endpoint}:{team_id}:{safe_repo}:{pr_number}"


def get_cached_pr_response(key: str) -> dict[str, Any] | None:
    """Return a cached JSON-encoded response payload, or None on miss / decode error."""
    try:
        raw = cache.get(key)
    except Exception:
        logger.warning("githog: pr response cache get failed", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        logger.warning("githog: pr response cache decode failed, treating as miss", exc_info=True)
        return None


def set_cached_pr_response(key: str, payload: dict[str, Any]) -> None:
    """Store a JSON-encoded response payload. Failures are logged, never raised."""
    try:
        cache.set(key, json.dumps(payload), timeout=_PR_RESPONSE_TTL_SECONDS)
    except Exception:
        logger.warning("githog: pr response cache set failed", exc_info=True)
