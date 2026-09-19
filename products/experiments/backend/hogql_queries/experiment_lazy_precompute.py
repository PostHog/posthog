"""Stale-while-revalidate (RFC 5861) for the experiment read path.

Experiment results are cached for a day, and the timeseries warming workflows
(`posthog/temporal/experiments/`) recompute every running experiment's metrics once a day. A read
that lands after the cached result expires and before the next warm recomputes inline, and that
recompute also rebuilds every precompute window whose TTL ran out. The 18-hour band for days 2-4
always has, because nothing refreshes it between warms. The rebuild runs on the request thread, so
the first person to open the experiment that day waits for it.

This module is the *serve* half: a user-facing read whose windows expired within the grace gets its
complete-but-stale rows back at once instead of rebuilding them. The *revalidate* half is the daily
warmer, which takes no grace and so always rebuilds; a read past the grace rebuilds inline as before.

Requests that ARE a refresh mechanism must never take the grace. Served their own stale rows, they
persist them as a fresh result and never recompute, which freezes the data instead of only slowing
it down. `resolve_stale_while_revalidate_seconds` gates that on the CACHE_WARMUP feature tag plus
the triggers below.
"""

from typing import Any

import structlog
from prometheus_client import Counter

from posthog.clickhouse.query_tagging import get_query_tag_value, tag_queries
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    ensure_precomputed,
)
from products.analytics_platform.backend.lazy_computation.stale_policy import resolve_stale_while_revalidate_seconds

logger = structlog.get_logger(__name__)

# Gates the whole mechanism, so it can be rolled out gradually and killed without a deploy. Off means
# a read materializes inline exactly as it did before this existed. Fail-safe: `feature_enabled_or_false`
# returns False if flag evaluation breaks, which degrades to that same pre-existing behaviour.
SERVE_STALE_FLAG = "experiments-serve-stale-precompute"

# The triggers every experiment refresher runs under. Each one rebuilds precompute for somebody else
# to read, so none of them may be served stale. The recalculation workflow is already caught by the
# CACHE_WARMUP feature tag it sets; these are the callers that identify themselves by trigger alone.
TIMESERIES_WARMING_TRIGGER = "warming/experiment_timeseries"
TIMESERIES_BACKFILL_TRIGGER = "warming/experiment_timeseries_backfill"
# The canary compares a precomputed read against a direct events scan. Stale rows would read as a
# divergence, so it must always build what it measures.
CANARY_TRIGGER = "experiment_precompute_canary"

BACKGROUND_WARMING_TRIGGERS = frozenset({TIMESERIES_WARMING_TRIGGER, TIMESERIES_BACKFILL_TRIGGER, CANARY_TRIGGER})

# How far past expiry a user-facing read may still be served from existing rows. Sized to one warming
# cadence: the warmer is what replaces the data, so the grace only has to cover the gap between a
# window expiring and the next daily warm rebuilding it. Half the framework's 48h ClickHouse expiry
# buffer, so a graced job's rows are still there with a day to spare.
STALE_WHILE_REVALIDATE_SECONDS = 24 * 60 * 60

# Execution modes that mean "recompute, disregard the cache". A retry or a manual refresh arrives as
# one of these, and the grace would hand it back the rows the person is trying to replace.
FORCED_REFRESH_EXECUTION_MODES = frozenset(
    {ExecutionMode.CALCULATE_BLOCKING_ALWAYS.value, ExecutionMode.CALCULATE_ASYNC_ALWAYS.value}
)

EXPERIMENT_PRECOMPUTE_STALE_SERVED = Counter(
    "experiment_precompute_stale_served_total",
    "Experiment reads served from expired-within-grace jobs instead of rebuilding inline.",
    labelnames=["table"],
)


def serve_stale_enabled(team: Team) -> bool:
    """Whether this team may be served stale precomputes, cached on the team instance.

    One experiment page load runs an ensure per metric plus one for exposures, so caching here keeps
    it to a single flag evaluation per request without leaking across requests, because a fresh team
    is loaded per request.

    Test authors: the cache lives on `team._experiments_serve_stale_flag`; clear it if you reuse a
    team across cases with different flag mocks.
    """
    cached = getattr(team, "_experiments_serve_stale_flag", None)
    if cached is not None:
        return cached
    enabled = feature_enabled_or_false(
        SERVE_STALE_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization.id)},
        group_properties={"organization": {"id": str(team.organization.id)}},
    )
    team._experiments_serve_stale_flag = enabled  # type: ignore[attr-defined]
    return enabled


def experiment_ensure_precomputed(*, team: Team, **kwargs: Any) -> LazyComputationResult:
    """`ensure_precomputed` for the experiment read path, with the product's serve-stale policy applied.

    User-facing reads get the grace. Refreshers, forced refreshes, and everyone when the flag is
    off get none.

    Every read-path ensure (exposures, metric events) must go through here, because one left on the
    raw call still blocks the request thread on an expired window, which is the whole problem.
    """
    if "stale_while_revalidate_seconds" not in kwargs:
        forced = get_query_tag_value("execution_mode") in FORCED_REFRESH_EXECUTION_MODES
        kwargs["stale_while_revalidate_seconds"] = (
            resolve_stale_while_revalidate_seconds(STALE_WHILE_REVALIDATE_SECONDS, BACKGROUND_WARMING_TRIGGERS)
            if serve_stale_enabled(team) and not forced
            else None
        )
    return ensure_precomputed(team=team, **kwargs)


def handle_stale_served(*, team: Team, experiment_id: int, table: str) -> None:
    """Count a stale-served read and tag the query, so query_log separates it from a fresh read."""
    EXPERIMENT_PRECOMPUTE_STALE_SERVED.labels(table=table).inc()
    tag_queries(precompute_stale=True)
    logger.info(
        "experiment_precompute.stale_served",
        team_id=team.id,
        experiment_id=experiment_id,
        table=table,
    )
