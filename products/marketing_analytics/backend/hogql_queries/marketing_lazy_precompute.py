"""Stale-while-revalidate (RFC 5861) for the marketing analytics read path.

Every precompute the dashboard reads — touchpoints, conversions, costs — is materialized by
`ensure_precomputed`, and when a window is stale that materialization runs *inline*: Postgres, Redis and
a synchronous ClickHouse INSERT, on the request thread. Instrumentation put ~10s of a ~13s dashboard load
there, with ClickHouse itself only ~1.2s.

It is stale on most loads by construction. The today-slice's TTL is 15 minutes
(`PRECOMPUTE_TTL_SECONDS["0d"]`) while the Dagster warmer runs hourly, so for roughly 45 of every 60
minutes a read finds it expired and rebuilds it before answering.

This module is the *serve* half: a user-facing read whose windows expired within the grace gets its
complete-but-stale rows back immediately instead of rebuilding them. `enqueue_stale_revalidation` is the
*revalidate* half: a stale hit schedules a background re-run so the next read is fresh, rather than
leaving freshness to the hourly warmer — which only covers the teams on its allowlist.

Requests that ARE a refresh mechanism must never take the grace: served their own stale rows they would
never recompute, and the data would never refresh again. `resolve_stale_while_revalidate_seconds` gates
that on the CACHE_WARMUP feature tag (which the Dagster warmer already sets) plus the trigger below.
"""

import json
import hashlib
from typing import Any

import structlog
from prometheus_client import Counter

from posthog import redis
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    ensure_precomputed,
)
from products.analytics_platform.backend.lazy_computation.stale_policy import resolve_stale_while_revalidate_seconds

logger = structlog.get_logger(__name__)

# The trigger the revalidation task runs under. Lives next to the trigger set so the two cannot drift.
REVALIDATION_TRIGGER = "marketingAnalyticsStaleRevalidation"

# Marketing's own refreshers. The Dagster warmer is already caught by the CACHE_WARMUP feature tag it
# sets, so it does not need naming here; this set is the belt for the revalidation task, which would
# otherwise serve itself stale and never recompute.
BACKGROUND_WARMING_TRIGGERS = frozenset({REVALIDATION_TRIGGER})

# How far past expiry a user-facing read may still be served from existing rows. Refresh normally lands
# within minutes via the revalidation task (plus the hourly warmer for allowlisted teams); this grace is
# the ceiling for when both of those fail. Must stay well under the framework's 48h ClickHouse expiry
# buffer, so the underlying rows are guaranteed to still exist.
STALE_WHILE_REVALIDATE_SECONDS = 6 * 60 * 60

# One revalidation per (team, query shape) per window. A dashboard renders several tiles off the same
# query shape and they all go stale together; without this they would each enqueue a rebuild of the same
# windows.
REVALIDATION_DEBOUNCE_SECONDS = 10 * 60

MARKETING_PRECOMPUTE_STALE_SERVED = Counter(
    "marketing_analytics_precompute_stale_served_total",
    "Reads served from expired-within-grace jobs instead of materializing inline (stale-while-revalidate).",
)

MARKETING_PRECOMPUTE_REVALIDATION_ENQUEUED = Counter(
    "marketing_analytics_precompute_revalidation_enqueued_total",
    "Background revalidation tasks enqueued after a stale-served read.",
)

MARKETING_PRECOMPUTE_REVALIDATION_ENQUEUE_FAILED = Counter(
    "marketing_analytics_precompute_revalidation_enqueue_failed_total",
    "Revalidation enqueues that failed (e.g. broker unavailable); the stale read is still served.",
)


def marketing_ensure_precomputed(*, team: Team, **kwargs: Any) -> LazyComputationResult:
    """`ensure_precomputed` for the marketing read path, with the product's serve-stale policy applied.

    User-facing calls get the grace; refreshers get none. Every read-path ensure (touchpoints,
    conversions, costs) must go through here — one left on the raw call still blocks the request thread
    on a stale window, which is the whole problem.
    """
    if "stale_while_revalidate_seconds" not in kwargs:
        kwargs["stale_while_revalidate_seconds"] = resolve_stale_while_revalidate_seconds(
            STALE_WHILE_REVALIDATE_SECONDS, BACKGROUND_WARMING_TRIGGERS
        )
    return ensure_precomputed(team=team, **kwargs)


def _query_shape_key(query: Any) -> str:
    payload = json.dumps(query.model_dump(mode="json", exclude_none=True), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def enqueue_stale_revalidation(*, team: Team, query: Any) -> None:
    """Schedule a background re-run so the next read of this query shape is fresh.

    Best-effort by design: this runs on the user-facing read path, before the stale rows are read, so a
    Redis or broker outage must degrade to "serve stale, warmer converges" and never fail the read.
    """
    # The task module imports this one for the trigger, so the reverse import stays local.
    from products.marketing_analytics.backend.tasks.lazy_precompute_revalidation import (  # noqa: PLC0415
        revalidate_marketing_analytics_precompute,
    )

    try:
        debounce_key = f"ma_swr_reval:{team.id}:{_query_shape_key(query)}"
        if not redis.get_client().set(debounce_key, "1", ex=REVALIDATION_DEBOUNCE_SECONDS, nx=True):
            return
        revalidate_marketing_analytics_precompute.delay(
            team_id=team.id, query=query.model_dump(mode="json", exclude_none=True)
        )
    except Exception:
        MARKETING_PRECOMPUTE_REVALIDATION_ENQUEUE_FAILED.inc()
        logger.warning("marketing_precompute.swr_revalidation_enqueue_failed", team_id=team.id, exc_info=True)
        return
    MARKETING_PRECOMPUTE_REVALIDATION_ENQUEUED.inc()
    logger.info("marketing_precompute.swr_revalidation_enqueued", team_id=team.id)


def handle_stale_served(*, team: Team, query: Any) -> None:
    """Everything the read path does once any of its ensures came back stale.

    Counts it, tags the upcoming read so query_log can separate stale-served from fresh reads, and
    enqueues the background revalidation.
    """
    MARKETING_PRECOMPUTE_STALE_SERVED.inc()
    tag_queries(precompute_stale=True)
    enqueue_stale_revalidation(team=team, query=query)
