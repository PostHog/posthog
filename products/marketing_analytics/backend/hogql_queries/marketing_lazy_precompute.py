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
from contextlib import suppress
from typing import Any

import structlog
from prometheus_client import Counter

from posthog import redis
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    EXPIRY_BUFFER_SECONDS,
    LazyComputationResult,
    ensure_precomputed,
)
from products.analytics_platform.backend.lazy_computation.stale_policy import is_background_warming_request

logger = structlog.get_logger(__name__)

# The trigger the revalidation task runs under. Lives next to the trigger set so the two cannot drift.
REVALIDATION_TRIGGER = "marketingAnalyticsStaleRevalidation"

# Marketing's own refreshers. The Dagster warmer is already caught by the CACHE_WARMUP feature tag it
# sets, so it does not need naming here; this set is the belt for the revalidation task, which would
# otherwise serve itself stale and never recompute.
BACKGROUND_WARMING_TRIGGERS = frozenset({REVALIDATION_TRIGGER})

# One revalidation per (team, query shape) per window. A dashboard renders several tiles off the same
# query shape and they all go stale together; without this they would each enqueue a rebuild of the same
# windows.
REVALIDATION_DEBOUNCE_SECONDS = 10 * 60

# If the enqueue itself fails (broker blip), hold the debounce slot only this long instead of the full
# window. Long enough not to retry `.delay()` on every stale read during an outage — each failed publish
# adds latency to a user-facing read — short enough that revalidation resumes soon after the broker heals,
# rather than staying suppressed for 10 minutes with no rebuild in flight.
ENQUEUE_FAILURE_BACKOFF_SECONDS = 30

# Fields that shape only the final read, never what gets materialized, so they must not split the debounce
# key — paging or re-sorting a stale table would otherwise enqueue a rebuild per interaction. Kept
# deliberately narrow: excluding a field that *does* select precomputes (`select` gates which conversion
# goals are built) would debounce away a revalidation that was actually needed.
FINAL_READ_ONLY_FIELDS = frozenset({"limit", "offset", "orderBy", "response", "tags", "dataColorTheme"})

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

MARKETING_PRECOMPUTE_NOT_READY_WARMED = Counter(
    "marketing_analytics_precompute_not_ready_warmed_total",
    "Background warms enqueued because a read found no precompute for its window (cold team on-demand).",
)


# Precompute-only reads serve stale rows up to just under the framework's 48h ClickHouse-row lifetime
# ceiling (EXPIRY_BUFFER_SECONDS). Past that the rows may be GC'd, so a read reports not-ready instead of
# risking a job_id that no longer has data behind it. Normal freshness is far tighter (hourly warmer +
# short TTL); this is only the ceiling for when warming falls badly behind.
PRECOMPUTE_ONLY_MAX_STALE_SECONDS = EXPIRY_BUFFER_SECONDS - 60 * 60  # 47h, safely below the 48h buffer


def marketing_ensure_precomputed(*, team: Team, **kwargs: Any) -> LazyComputationResult:
    """`ensure_precomputed` for the marketing read path: precompute-only serving.

    User-facing reads never materialize inline. They serve whatever the warmer produced — fresh, or stale
    up to `PRECOMPUTE_ONLY_MAX_STALE_SECONDS` — and report not-ready (`ready=False`) when a window was
    never warmed. The warmer is the sole producer, so the request thread is never blocked on a synchronous
    INSERT. Every read-path ensure (touchpoints, conversions, costs) goes through here — one left on the
    raw call would reintroduce inline materialization, which is the whole problem.

    Background refreshers (the revalidation task) are the exception: they *are* the mechanism that keeps
    the precompute fresh, so they must run inserts and take no grace. `is_background_warming_request`
    classifies them by the CACHE_WARMUP tag / revalidation trigger, exactly as the old grace policy did.
    """
    if is_background_warming_request(BACKGROUND_WARMING_TRIGGERS):
        return ensure_precomputed(team=team, **kwargs)
    kwargs.setdefault("run_inserts", False)
    kwargs.setdefault("stale_while_revalidate_seconds", PRECOMPUTE_ONLY_MAX_STALE_SECONDS)
    return ensure_precomputed(team=team, **kwargs)


def _query_shape_key(query: Any) -> str:
    payload = json.dumps(
        query.model_dump(mode="json", exclude_none=True, exclude=set(FINAL_READ_ONLY_FIELDS)),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _scope_to_revalidation(query: Any) -> Any:
    """Drop compare mode so the revalidation rebuilds only the window that actually went stale.

    A compare read runs two independent runners (current + previous), each of which detects its own
    staleness and enqueues its own window. Leaving compare on would make the task re-derive a second,
    un-requested comparison window on top of the one it needs — double the ensure work per task.
    """
    compare_filter = getattr(query, "compareFilter", None)
    if compare_filter is None or not getattr(compare_filter, "compare", False):
        return query
    # Drop the filter entirely rather than just flipping compare off, so a compare read and a plain read
    # of the same window collapse onto one debounce slot instead of scheduling near-identical rebuilds.
    scoped = query.model_copy(deep=True)
    scoped.compareFilter = None
    return scoped


def enqueue_stale_revalidation(*, team: Team, query: Any) -> None:
    """Schedule a background re-run so the next read of this query shape is fresh.

    Best-effort by design: this runs on the user-facing read path, before the stale rows are read, so a
    Redis or broker outage must degrade to "serve stale, warmer converges" and never fail the read.
    """
    # The task module imports this one for the trigger, so the reverse import stays local.
    from products.marketing_analytics.backend.tasks.lazy_precompute_revalidation import (  # noqa: PLC0415
        revalidate_marketing_analytics_precompute,
    )

    query = _scope_to_revalidation(query)
    claimed = False
    debounce_key: str | None = None
    try:
        debounce_key = f"ma_swr_reval:{team.id}:{_query_shape_key(query)}"
        claimed = bool(redis.get_client().set(debounce_key, "1", ex=REVALIDATION_DEBOUNCE_SECONDS, nx=True))
        if not claimed:
            return
        revalidate_marketing_analytics_precompute.delay(
            team_id=team.id, query=query.model_dump(mode="json", exclude_none=True)
        )
    except Exception:
        # We may have claimed the debounce slot before the enqueue failed. Shrink it to a brief backoff so
        # the next stale read retries soon, rather than being suppressed for the full window with no
        # rebuild in flight — while not retrying on every read during a broker outage.
        if claimed and debounce_key is not None:
            with suppress(Exception):
                redis.get_client().set(debounce_key, "1", ex=ENQUEUE_FAILURE_BACKOFF_SECONDS)
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


def handle_not_ready(*, team: Team, query: Any) -> None:
    """A read found no warm precompute for its window — a cold team outside the rolling warm set.

    Enqueue a one-off background warm (debounced, same as revalidation) so the team's next visit is
    served. The user sees the "computing" state until the warm lands.
    """
    MARKETING_PRECOMPUTE_NOT_READY_WARMED.inc()
    enqueue_stale_revalidation(team=team, query=query)
