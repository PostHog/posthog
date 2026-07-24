"""Shared eligibility gate + helpers for web-analytics lazy precompute paths.

Both the web overview lazy precompute and the web stats PATHS lazy precompute
share the same rollout/safety gate (org feature flag + per-query opt-out,
whole-hour timezone, no conversion goal, no sampling, no v2 UUID sessions,
any event/person filter shape, bounded date range) and the same TTL / session-pad
/ UTC-day helpers. Keeping a single source of truth avoids the paths drifting apart.
The per-team distinct-shape ceiling (`try_reserve_precompute_shape`) lives here
too, bounding how many namespaces the loosened filter gate lets a team mint.
"""

import json
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.conf import settings

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.schema import SessionsV2JoinMode

from posthog.hogql import ast
from posthog.hogql.property import get_property_type, property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog import redis
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.analytics_platform.backend.lazy_computation.stale_policy import (
    is_background_warming_request as shared_is_background_warming_request,
    resolve_stale_while_revalidate_seconds,
)

logger = structlog.get_logger(__name__)

# Reactive per-team OOM cap. A very high-cardinality team's wide-window GROUP BY
# (session, breakdown) can OOM the precompute INSERT. We run uncapped until that happens;
# on an OOM we pin the team (one Redis key per team, self-healing TTL) so its later requests
# build their TTL schedule with a 1-day `max_window_days` cap — bounding each insert's GROUP
# BY by job *width*, at any window age (so a year-over-year compare's old previous period is
# capped too), while keeping the team's normal TTL grading. The capping lives entirely in the
# schedule handed to `ensure_precomputed`, so the executor needs no per-team knowledge.
OOM_PIN_WINDOW_DAYS = 1
TEAM_OOM_PIN_REDIS_PREFIX = "preagg:oom_pinned:"
OOM_PIN_TTL_SECONDS = 14 * 24 * 60 * 60


def _oom_pin_key(team_id: int) -> str:
    return f"{TEAM_OOM_PIN_REDIS_PREFIX}{team_id}"


def is_team_oom_pinned(team_id: int) -> bool:
    """Whether the team has hit an OOM recently and should cap its insert windows.

    Best-effort: a Redis failure reads as not-pinned (uncapped default) — never blocks the insert."""
    try:
        return redis.get_client().get(_oom_pin_key(team_id)) is not None
    except Exception:
        return False


def pin_team_oom(team_id: int) -> None:
    """Pin (or refresh) a team's OOM cap after an OOM. Best-effort; self-healing TTL."""
    try:
        redis.get_client().set(_oom_pin_key(team_id), "1", ex=OOM_PIN_TTL_SECONDS)
    except Exception:
        logger.warning("web_precompute.oom_pin_failed", team_id=team_id, exc_info=True)


def clear_team_oom_pin(team_id: int) -> bool:
    """Remove a team's OOM pin so its next inserts run at full window width again.

    Returns whether a pin existed. Unlike the read/write helpers this is NOT
    best-effort: it is only called from operator tooling, where a Redis failure
    should surface instead of silently reporting the pin as cleared."""
    return redis.get_client().delete(_oom_pin_key(team_id)) > 0


def list_oom_pinned_team_ids() -> list[int]:
    """Team ids currently OOM-pinned, via a prefix SCAN (operator tooling only)."""
    prefix = TEAM_OOM_PIN_REDIS_PREFIX
    team_ids = []
    for key in redis.get_client().scan_iter(match=f"{prefix}*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        team_ids.append(int(key_str[len(prefix) :]))
    return sorted(team_ids)


# Per-team distinct-shape ceiling. With the filter gate loosened, any filter combination
# becomes its own precompute namespace, so a pathological team could mint unbounded shapes.
# This is a coarse backstop, not a quota: a team builds shapes freely until it holds this
# many distinct ones, after which *new* shapes fall back to the live query (existing shapes
# keep serving and refreshing). Enforced only on build paths and only here, on the
# web-analytics side of the framework boundary, so the shared lazy_computation framework —
# and its other consumers (e.g. experiments) — is never capped. The set's TTL is stamped
# once when its first shape is added, so the whole counter resets periodically rather than
# accreting cold shapes forever; a still-exploding team simply refills within the window.
TEAM_SHAPE_SET_REDIS_PREFIX = "preagg:team_shapes:"
TEAM_SHAPE_SET_TTL_SECONDS = 30 * 24 * 60 * 60  # matches the warmed -30d depth


def _team_shape_set_key(team_id: int) -> str:
    return f"{TEAM_SHAPE_SET_REDIS_PREFIX}{team_id}"


def try_reserve_precompute_shape(team_id: int, shape_hash: str) -> bool:
    """Reserve a build slot for `shape_hash` under the team's distinct-shape ceiling.

    Returns True when the shape may build — it was already counted, the cap is disabled,
    or there was room (and it's now counted). Returns False only when the team is at the
    ceiling AND this shape is new: the one case we drop early. Best-effort: any Redis
    failure returns True (fail open — a backstop must never block a legitimate build).

    The count is approximate under concurrency (sismember/scard/sadd aren't atomic), which
    is fine for a coarse ceiling: a few concurrent new shapes may overshoot by a handful."""
    ceiling = settings.WEB_ANALYTICS_PRECOMPUTE_MAX_SHAPES_PER_TEAM
    if ceiling <= 0:
        return True
    try:
        client = redis.get_client()
        key = _team_shape_set_key(team_id)
        if client.sismember(key, shape_hash):
            return True
        count = client.scard(key)
        if count >= ceiling:
            return False
        client.sadd(key, shape_hash)
        if count == 0:
            client.expire(key, TEAM_SHAPE_SET_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("web_precompute.shape_cap_check_failed", team_id=team_id, exc_info=True)
        return True


# --- Stale-while-revalidate (RFC 5861) -------------------------------------------------
#
# The lazy executor's `stale_while_revalidate_seconds` is the *serve* half: user-facing
# requests whose windows expired within the grace get their complete-but-stale rows
# instantly instead of recomputing inline. The helpers below are the *revalidate* half:
# a stale hit enqueues a Celery task that re-runs the query in the background so the
# next fetch is fresh, instead of relying solely on the hourly eager warmer (which only
# covers warmed query shapes). Duplicate enqueues need no dedup layer: the HogQL result
# cache fronts these queries (stale hits are rare per shape), the framework's PENDING-job
# unique index collapses concurrent recomputes to one insert, and the ANALYTICS_LIMITED
# queue plus task `expires` pace and shed anything redundant — the same load profile the
# pre-serve-stale inline path already tolerated at user-request concurrency.

# The trigger tag the revalidation task runs under. Lives here, next to the trigger set,
# so the two cannot drift apart.
REVALIDATION_TRIGGER = "webAnalyticsStaleRevalidation"

# Web's own refreshers. These ARE the refresh mechanism: they must never be served stale
# (they'd freeze the cache serving stale to themselves) and they keep the framework's full
# wait budget. Warmers shared across products (e.g. the generic insight cache warmer,
# trigger "warmingV2") live in SHARED_BACKGROUND_WARMING_TRIGGERS and are unioned in by
# `is_background_warming_request`. This named set is the belt; the primary gate there is the
# CACHE_WARMUP feature tag, which classifies refreshers by category — including warmers this
# module doesn't know by name.
BACKGROUND_WARMING_TRIGGERS = frozenset(
    {
        "webAnalyticsEagerBaselineWarming",
        "webAnalyticsQueryWarming",
        REVALIDATION_TRIGGER,
    }
)

# Stale-while-revalidate window for *user-facing* requests: windows that expired within
# this grace are served from their existing (complete-but-stale) rows instantly instead
# of recomputing inline, and a background revalidation is enqueued. Refresh normally
# arrives within minutes via the revalidation task (plus the hourly eager warmer for
# warmed shapes) — the grace is the ceiling for revalidation failures and warmer
# outages. Must stay well under the framework's 48h ClickHouse expiry buffer (rows must
# still exist).
STALE_WHILE_REVALIDATE_SECONDS = 6 * 60 * 60

WEB_ANALYTICS_LAZY_PRECOMPUTE_CHECK_MISS = Counter(
    "web_analytics_lazy_precompute_check_miss_total",
    "User-facing reads that found no covering READY jobs, fell back to the live query, and enqueued a background warm.",
    labelnames=["family"],
)

WEB_ANALYTICS_LAZY_PRECOMPUTE_SHAPE_CAPPED = Counter(
    "web_analytics_lazy_precompute_shape_capped_total",
    "Precompute builds skipped because the team was at its distinct-shape ceiling; the query served live instead.",
    labelnames=["family"],
)

WEB_ANALYTICS_LAZY_PRECOMPUTE_STALE_SERVED = Counter(
    "web_analytics_lazy_precompute_stale_served_total",
    "Reads served from expired-within-grace jobs instead of recomputing inline (stale-while-revalidate).",
    labelnames=["family"],
)

WEB_ANALYTICS_LAZY_PRECOMPUTE_REVALIDATION_ENQUEUED = Counter(
    "web_analytics_lazy_precompute_revalidation_enqueued_total",
    "Background revalidation tasks enqueued after a stale-served read.",
    labelnames=["family"],
)

WEB_ANALYTICS_LAZY_PRECOMPUTE_REVALIDATION_ENQUEUE_FAILED = Counter(
    "web_analytics_lazy_precompute_revalidation_enqueue_failed_total",
    "Revalidation enqueues that failed (e.g. broker unavailable); the stale read is still served.",
    labelnames=["family"],
)


def is_background_warming_request() -> bool:
    return shared_is_background_warming_request(BACKGROUND_WARMING_TRIGGERS)


# One revalidation per (team, family, query shape) per window: a dashboard burst — or a
# user hammering forced refresh on a stale tile — fires many stale serves for the same
# shape and they must collapse to a single background rebuild. Keyed per shape (not per
# request) so two different stale families in one request each still get their refresh.
REVALIDATION_DEBOUNCE_SECONDS = 10 * 60

# The shape debounce alone does not bound DISTINCT shapes: filters and date ranges are
# request-controlled, so a user (or runaway client) could mint arbitrarily many shapes
# and with them arbitrarily many queued warms. Cap total enqueues per team per debounce
# window; a full dashboard is ~8 families and a compare-period burst doubles some, so
# the budget comfortably covers legitimate use while bounding worker-held delayed tasks
# and background query volume alike.
#
# Scope: this budget only ever applies to USER-FACING requests. Both enqueue callers
# are unreachable from warming traffic — the check-miss enqueue in
# `web_ensure_precomputed` is gated on `not is_background_warming_request()`, and
# `handle_stale_served` can only fire for reads that received the stale grace, which
# warming requests never do. Dagster/celery warmers are unaffected.
REVALIDATION_TEAM_BUDGET_PER_WINDOW = 25

# Head start for the interactive burst: warms enqueued by a dashboard load run on the
# same team/cluster query slots as the dashboard's own live queries, so firing them
# immediately makes the background work contend with the very read it is serving.
# Dashboard bursts finish in seconds — 20s comfortably outlasts the slowest
# burst observed while keeping the warm (whose purpose is the NEXT visit)
# close behind. Celery holds countdown tasks worker-side until runnable, but
# the per-shape debounce bounds in-flight delayed tasks to at most one per
# (team, family, shape) per debounce window — a trickle, not a backlog.
REVALIDATION_START_DELAY_SECONDS = 20


def enqueue_stale_revalidation(*, team: Team, query: Any, family: str) -> None:
    """Enqueue a background re-run of `query` so a stale-served read gets fresh data next time.

    Debounced via Redis per (team, family, query shape). Best-effort: this runs on the
    user-facing read path before the stale rows are read, so a Redis or broker outage
    must degrade to "serve stale, warmer converges" — never abort the read into the
    expensive live fallback.
    """
    # The task module imports this module (for the trigger constant), so the reverse
    # import must stay local to avoid a cycle.
    from products.web_analytics.backend.tasks.lazy_precompute_revalidation import (  # noqa: PLC0415
        REVALIDATION_EXPIRES_SECONDS,
        revalidate_web_analytics_precompute,
    )

    try:
        client = redis.get_client()
        debounce_key = f"web_swr_reval:{team.id}:{family}:{compute_filters_eligibility_hash(query, team.timezone)[:16]}"
        if not client.set(debounce_key, "1", ex=REVALIDATION_DEBOUNCE_SECONDS, nx=True):
            return
        budget_key = f"web_swr_reval_budget:{team.id}"
        spent = client.incr(budget_key)
        if spent == 1:
            client.expire(budget_key, REVALIDATION_DEBOUNCE_SECONDS)
        if spent > REVALIDATION_TEAM_BUDGET_PER_WINDOW:
            # Release the shape's debounce claim: no task was enqueued, so leaving
            # the key would lock the shape out of warming for the whole debounce
            # window even after the budget resets.
            client.delete(debounce_key)
            logger.warning("web_precompute.swr_revalidation_budget_exhausted", team_id=team.id, family=family)
            return
        revalidate_web_analytics_precompute.apply_async(
            kwargs={"team_id": team.id, "query": query.model_dump(mode="json", exclude_none=True)},
            countdown=REVALIDATION_START_DELAY_SECONDS,
            # `expires` is measured from publication; extend it by the countdown so
            # the queue keeps the task's full pickup window despite the head start.
            expires=REVALIDATION_START_DELAY_SECONDS + REVALIDATION_EXPIRES_SECONDS,
        )
    except Exception:
        WEB_ANALYTICS_LAZY_PRECOMPUTE_REVALIDATION_ENQUEUE_FAILED.labels(family=family).inc()
        logger.warning("web_precompute.swr_revalidation_enqueue_failed", team_id=team.id, family=family, exc_info=True)
        return
    WEB_ANALYTICS_LAZY_PRECOMPUTE_REVALIDATION_ENQUEUED.labels(family=family).inc()
    logger.info("web_precompute.swr_revalidation_enqueued", team_id=team.id, family=family)


def handle_stale_served(*, runner: Any, family: str) -> None:
    """Everything a read path does when an ensure came back `stale=True`.

    Counts the stale-served read, tags the upcoming read query so query_log can split
    stale-served vs fresh reads, and enqueues the background revalidation. The enqueue
    is debounced per (team, family, query shape) in Redis — a compare-period ensure
    coming back stale after the current-period one collapses to one task (one re-run
    covers both periods), while a *different* stale family in the same request still
    gets its own refresh.
    """
    WEB_ANALYTICS_LAZY_PRECOMPUTE_STALE_SERVED.labels(family=family).inc()
    tag_queries(precompute_stale=True)
    enqueue_stale_revalidation(team=runner.team, query=runner.query, family=family)


def web_ensure_precomputed(*, team: Team, **kwargs: Any) -> LazyComputationResult:
    """`ensure_precomputed` for web analytics, with reactive per-team OOM capping and
    the web-wide stale-while-revalidate policy.

    A team runs uncapped until one of its precompute inserts OOMs; that pins it so later
    requests build their TTL schedule with a 1-day `max_window_days` cap (job width bounded
    at any window age). The request that hits the OOM still fails here and falls back to the
    live query — the cap only takes effect next time.

    Every user-facing call gets the stale-while-revalidate grace by default; requests
    tagged with a background warming trigger never do (they are the refresh mechanism
    and would serve stale to themselves). Callers that see `stale=True` must hand the
    result to `handle_stale_served` so the background revalidation actually happens.
    """
    runner = kwargs.pop("runner", None)
    family = kwargs.pop("family", None)
    background = is_background_warming_request()
    if "stale_while_revalidate_seconds" not in kwargs:
        kwargs["stale_while_revalidate_seconds"] = resolve_stale_while_revalidate_seconds(
            STALE_WHILE_REVALIDATE_SECONDS, BACKGROUND_WARMING_TRIGGERS
        )
    # User-facing requests never compute inline: they are served from covering
    # READY jobs (fresh or within the stale grace) or told "miss" immediately so
    # the caller falls back to the live query. Construction happens only on
    # background triggers (warmers, the revalidation task) — a cold dashboard
    # must not pay for its own backfill.
    if "run_inserts" not in kwargs:
        kwargs["run_inserts"] = background
    # Per-team distinct-shape backstop. Only build paths can mint a new namespace, so this
    # only bites there (a user read is already run_inserts=False). At the ceiling, a *new*
    # shape drops back to a check-only pass — not ready → the caller serves live — instead
    # of building; shapes the team already holds are unaffected. Reuses the eligibility hash
    # so a shape counts the same however it reaches this build path.
    if kwargs.get("run_inserts") and runner is not None:
        shape_hash = compute_shape_cap_key(runner.query, team.timezone, getattr(runner, "_test_account_filters", None))
        if not try_reserve_precompute_shape(team.id, shape_hash):
            kwargs["run_inserts"] = False
            WEB_ANALYTICS_LAZY_PRECOMPUTE_SHAPE_CAPPED.labels(family=family or "unknown").inc()
            logger.info("web_precompute.shape_capped", team_id=team.id, family=family)
    pinned = is_team_oom_pinned(team.id)
    if "ttl_seconds" in kwargs:
        existing = kwargs["ttl_seconds"]
        # Normalize whatever the caller passed into a TtlSchedule so web-wide policy can be
        # stamped on: an int/dict gets parsed; an already-built TtlSchedule (also accepted
        # by ensure_precomputed) gets its fields re-stamped via replace().
        # Every web schedule settles on the 24h session pad: a job computed before
        # `window_end + pad` captured still-evolving session metrics and must not sit on
        # a long band TTL — non-UTC teams' UTC-aligned edge windows can land in a
        # multi-day band while their sessions are still settling.
        if isinstance(existing, TtlSchedule):
            schedule = replace(existing, settling_period_seconds=SESSION_SETTLING_SECONDS)
        else:
            schedule = parse_ttl_schedule(existing, team.timezone, settling_period_seconds=SESSION_SETTLING_SECONDS)
        if pinned:
            schedule = replace(schedule, max_window_days=OOM_PIN_WINDOW_DAYS)
        kwargs["ttl_seconds"] = schedule
    result = ensure_precomputed(team=team, **kwargs)
    if not result.ready and not background and runner is not None and family is not None:
        # Check-only miss: warm in the background (debounced per team/family/shape)
        # so the next visit is served from precompute while this one goes live.
        WEB_ANALYTICS_LAZY_PRECOMPUTE_CHECK_MISS.labels(family=family).inc()
        enqueue_stale_revalidation(team=team, query=runner.query, family=family)
    if result.memory_exceeded:
        pin_team_oom(team.id)  # set or refresh the cap so a still-OOMing team stays pinned
        if not pinned:
            logger.warning("web_precompute.oom_pinned_team", team_id=team.id, table=str(kwargs.get("table")))
    return result


# Fields stripped from the query payload before hashing.
# These don't influence which precompute job_id a query would map to —
# `useWebAnalyticsPrecompute` is just the opt-in toggle, `modifiers` is
# HogQL execution hints applied after the fact, and the rest are
# metadata / pagination knobs applied at read time.
_FILTERS_ELIGIBILITY_HASH_IGNORED_QUERY_FIELDS: frozenset[str] = frozenset(
    {
        "useWebAnalyticsPrecompute",
        "modifiers",
        "version",
        "tags",
        "response",
        "limit",
        "offset",
        "limitBy",
    }
)

# Hourly UTC bucketing TTL schedule. Two jobs in one:
#
# 1. Freshness — today gets 4h and yesterday 6h. Both must comfortably outlast
#    the eager warmer's hourly force-refresh cadence: a user read that finds the
#    window stale pays a synchronous recompute before reading, so a TTL near the
#    warmer period (yesterday was 1h) races it and hands users multi-second
#    waits. Recomputing more often buys nothing anyway — the ~6h HogQL result
#    cache already fronts these queries, so a cache hit never reads the
#    precompute. Today and yesterday must keep *distinct* TTLs or
#    `split_ranges_by_ttl` fuses them into one 2-day job and every
#    today-refresh recomputes yesterday too.
#    Windows aged 2+ days are *session-final*: sessions cap at 24h (the insert
#    scans window_end+24h), so bounce/duration can no longer change, and
#    measured late-event ingestion beyond 49h is ≤0.03% of pageviews on the
#    worst enrolled team (~0% elsewhere). Their TTLs are therefore generous —
#    recomputing an immutable window buys nothing — and bounded in practice by
#    hash rotations (any AST-affecting deploy rebuilds everything anyway).
# 2. Job sizing — `split_ranges_by_ttl` merges *consecutive days with the same
#    TTL* into one job. Distinct per-week TTLs therefore force weekly job
#    boundaries, so a 31-day warm splits into ≤7-day jobs instead of one ~24-day
#    block. That keeps each per-day INSERT's events↔sessions scan bounded — the
#    24-day merge is what drove the multi-hundred-million-row scans that OOM the
#    insert on very high-traffic teams.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 4 * 60 * 60,  # today
    "1d": 6 * 60 * 60,  # yesterday
    "7d": 5 * 24 * 60 * 60,  # days 2–7   → one ~6d job
    "14d": 7 * 24 * 60 * 60,  # days 8–14  → one 7d job
    "21d": 10 * 24 * 60 * 60,  # days 15–21 → one 7d job
    "28d": 12 * 24 * 60 * 60,  # days 22–28 → one 7d job
    "35d": 14 * 24 * 60 * 60,  # days 29–35 → one 7d job (covers the tail of a 31d warm)
    "default": 21 * 24 * 60 * 60,  # days 36+
}

# MVP user-filter allowlist: only an EventPropertyFilter on `$host` with
# operator `exact` is admitted. Test-account filters are always allowed
# (their content is hashed into the cache key).
SUPPORTED_USER_FILTER_KEYS: set[str] = {"$host"}

# Upper bound on the precompute span. Above this, the framework would create
# enough daily jobs that the first request burns INSERT slots for minutes.
MAX_PRECOMPUTE_DAYS = 90

# Forward pad on the per-job event-scan window. Matches the JS SDK's
# 24 h hard SESSION_LENGTH_LIMIT and covers ~100% of population sessions.
# See web_overview_lazy_precompute.py for the full reasoning.
SESSION_FORWARD_PAD_MINUTES = 24 * 60

# How long after a window ends its session metrics can still change: sessions opened in
# the window keep evolving (bounce flips, duration grows) until they hit the SDK's 24h
# session cap — the same bound the insert's forward pad scans. Stamped onto every web
# TTL schedule as its settling period (see `web_ensure_precomputed`).
SESSION_SETTLING_SECONDS = SESSION_FORWARD_PAD_MINUTES * 60

# Org-level rollout flag — same one the frontend uses to show the "Allow
# precompute" toggle.
ORG_FEATURE_FLAG_KEY = "web-analytics-precompute-toggle"


class LazyPrecomputeIneligible(Exception):
    """Base class for reasons a lazy precompute path is not eligible.

    Subclass names are the canonical identifiers used in logs/metrics —
    keep them stable across releases.
    """


class OrgFeatureFlagDisabled(LazyPrecomputeIneligible):
    pass


class PerQueryOptedOut(LazyPrecomputeIneligible):
    """The user explicitly turned the "Allow precompute" toggle off."""

    pass


class NonIntegerTimezone(LazyPrecomputeIneligible):
    pass


class ConversionGoalUnsupported(LazyPrecomputeIneligible):
    pass


class SamplingEnabled(LazyPrecomputeIneligible):
    pass


class SessionsV2UuidMode(LazyPrecomputeIneligible):
    pass


class TooManyFilters(LazyPrecomputeIneligible):
    pass


class NonEventPropertyFilter(LazyPrecomputeIneligible):
    pass


class UnsupportedFilterKey(LazyPrecomputeIneligible):
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"key={key!r}")


class UnsupportedFilterOperator(LazyPrecomputeIneligible):
    def __init__(self, operator: object):
        self.operator = operator
        super().__init__(f"operator={operator!r}")


class NonStringOrEmptyFilterValue(LazyPrecomputeIneligible):
    pass


class UnsupportedFilterType(LazyPrecomputeIneligible):
    """A filter is not an event/person property — precompute only handles those,
    since session/cohort filters are applied differently on the live path per family."""

    def __init__(self, filter_type: object):
        self.filter_type = filter_type
        super().__init__(f"type={filter_type!r}")


class PropertyAccessControlled(LazyPrecomputeIneligible):
    """The team has property-level access controls — userless shared precompute
    can't honor per-user property restrictions, so the query stays on the live path."""


class MissingDateRange(LazyPrecomputeIneligible):
    pass


class DateRangeOverMax(LazyPrecomputeIneligible):
    def __init__(self, days: int):
        self.days = days
        super().__init__(f"days={days} max={MAX_PRECOMPUTE_DAYS}")


def is_org_feature_flag_enabled(team: Team) -> bool:
    """Evaluate the rollout flag locally — fails closed on flag-service errors."""
    return bool(
        posthoganalytics.feature_enabled(
            ORG_FEATURE_FLAG_KEY,
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def is_precompute_enabled_for_team(team: Team) -> bool:
    """Whether a team should take the lazy precompute path.

    Short-circuits on the `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` env-var
    setting before evaluating the org rollout flag. The list is the shared
    source of truth with the eager warmer, and — unlike the flag — does not rely
    on local flag-definition evaluation, which isn't reliably available outside
    the Django app (e.g. the Dagster warmer, where `only_evaluate_locally`
    returned falsy and silently dropped the warmer onto the raw path).
    """
    if team.id in settings.WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS:
        return True
    # Background warmers build buckets for every active team regardless of the
    # rollout flag: warming precedes read enablement, and flag evaluation is not
    # reliably available in the Dagster processes the warmers run in. User-facing
    # reads still require flag enrollment; the per-team shape ceiling keeps the
    # warmed set bounded.
    if is_background_warming_request():
        return True
    return is_org_feature_flag_enabled(team)


def check_common_eligibility(
    *,
    team: Team,
    use_web_analytics_precompute: Optional[bool],
    conversion_goal: Any,
    sampling: Any,
    modifiers: Any,
    properties: list,
    resolve_date_range: Callable[[], tuple[Optional[datetime], Optional[datetime]]],
) -> None:
    """Run the gate checks shared by all web-analytics lazy precompute paths.

    Raises a `LazyPrecomputeIneligible` subclass on failure; returns None on
    success. The caller is responsible for any additional per-runner checks
    (e.g. PATHS requires `breakdownBy=PAGE && includeBounceRate`).

    `resolve_date_range` is called lazily so the gate can reject cheap cases
    (org flag off, etc.) without touching `QueryDateRange.date_from()` —
    which can trigger a ClickHouse min-timestamp lookup for `-all` ranges.
    """
    if not is_precompute_enabled_for_team(team):
        raise OrgFeatureFlagDisabled()

    # Precompute defaults ON for every enrolled team: an untouched toggle
    # (`None`) takes the precompute path; only an explicit `False` (the
    # "Allow precompute" toggle turned off) opts a query out.
    if use_web_analytics_precompute is False:
        raise PerQueryOptedOut()

    if not is_integer_timezone(team.timezone):
        raise NonIntegerTimezone()

    if conversion_goal is not None:
        raise ConversionGoalUnsupported()

    if sampling is not None and getattr(sampling, "enabled", False):
        raise SamplingEnabled()

    if modifiers and getattr(modifiers, "sessionsV2JoinMode", None) == SessionsV2JoinMode.UUID:
        raise SessionsV2UuidMode()

    # Any event/person filter shape is accepted (any key, any operator, any number),
    # translated as a whole via `property_to_expr`; each distinct set becomes its own
    # cache key, bounded by the per-team shape ceiling in `web_ensure_precomputed`.
    # Session and cohort filters are refused: the precompute INSERT applies the whole
    # list userlessly, but the live runners handle those types differently per family
    # (web vitals drops them entirely), so precomputing them would serve a different
    # population than the live fallback. Those queries fall through to the live path,
    # which applies them correctly.
    for prop in properties:
        if get_property_type(prop) not in ("event", "person"):
            raise UnsupportedFilterType(get_property_type(prop))

    # Precompute results are built userless and shared across users by a
    # user-independent cache key, so they cannot honor per-user property
    # restrictions. If the team has any property-level access controls, skip
    # precompute entirely and let the live path enforce them per requesting user.
    if team_has_property_access_rules(team_id=team.id):
        raise PropertyAccessControlled()

    date_from, date_to = resolve_date_range()
    if date_from is None or date_to is None:
        raise MissingDateRange()

    days = (date_to - date_from).days
    if days > MAX_PRECOMPUTE_DAYS:
        raise DateRangeOverMax(days)


def log_eligibility_outcome(*, log_prefix: str, team_id: int, error: Optional[LazyPrecomputeIneligible]) -> None:
    """Emit the same `*_rejected` / `*_eligible` info log shape used by every
    lazy path so a single Loki query can attribute all fall-throughs."""
    if error is not None:
        logger.info(
            f"{log_prefix}_rejected",
            team_id=team_id,
            reason=type(error).__name__,
            detail=str(error) or None,
        )
    else:
        logger.info(f"{log_prefix}_eligible", team_id=team_id)


def compute_filters_eligibility_hash(query: Any, team_timezone: str) -> str:
    """Stable hash over the user-facing inputs that would fragment a precompute cache key.

    Emitted on the `web_analytics_query` and `lazy_computation.executed` structured
    log lines so the two can be joined and queries-per-distinct-cache-key (`q/key`)
    can be measured over multi-day windows — including for queries that didn't
    go through the lazy precompute path (different eligibility gating, different
    runner) but would have shared a job_id if they had.

    Same hashing mechanic as `compute_query_hash` in lazy_computation_executor
    (SHA-256 over canonical JSON). It is **not** numerically identical to the
    precompute job's `query_hash` — that one hashes the post-build INSERT AST —
    but it fragments along the same logical dimensions: query kind, property
    filters (with values), date range, breakdown, conversion goal, sampling,
    interval, compare filter, test-accounts toggle, and team timezone.
    """
    return _hash_query_fields(query, team_timezone, _FILTERS_ELIGIBILITY_HASH_IGNORED_QUERY_FIELDS)


# The precompute namespace (`compute_query_hash`) sentinelizes its time-window
# placeholders, so buckets are reused across requested date ranges: different
# ranges — and a compare query's current vs. previous period — of the same
# filter/breakdown shape map to ONE namespace. The shape cap therefore drops the
# range-varying fields on top of the eligibility-hash ignores, so it counts
# distinct namespaces rather than per-request shapes. Otherwise a user could
# exhaust the ceiling by replaying one filter with different ISO timestamps until
# new legitimate shapes are forced onto the live path (veria review).
_SHAPE_CAP_KEY_IGNORED_QUERY_FIELDS: frozenset[str] = _FILTERS_ELIGIBILITY_HASH_IGNORED_QUERY_FIELDS | frozenset(
    {"dateRange", "compareFilter"}
)


def compute_shape_cap_key(query: Any, team_timezone: str, test_account_filters: Optional[list] = None) -> str:
    """Namespace-identity key for the per-team shape cap: the eligibility hash with the
    time-window fields dropped (so date-range variants of one shape share a slot), plus
    the team's resolved test-account filters. Those resolve from team config into the
    INSERT AST — part of the namespace but absent from the query payload — so folding them
    in stops an admin from minting fresh namespaces onto one cap slot by editing the
    test-account filters (veria review)."""
    dumped = query.model_dump(mode="json", exclude_none=True, by_alias=False)
    for key in _SHAPE_CAP_KEY_IGNORED_QUERY_FIELDS:
        dumped.pop(key, None)
    tafs = [
        f.model_dump(mode="json", exclude_none=True) if hasattr(f, "model_dump") else f
        for f in (test_account_filters or [])
    ]
    payload = {"query": dumped, "timezone": team_timezone, "test_account_filters": tafs}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _hash_query_fields(query: Any, team_timezone: str, ignored_fields: frozenset[str]) -> str:
    dumped = query.model_dump(mode="json", exclude_none=True, by_alias=False)
    for key in ignored_fields:
        dumped.pop(key, None)
    payload = {"query": dumped, "timezone": team_timezone}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def host_filter_expr(properties: list, *, team: Team) -> ast.Expr:
    """Translate the user filter list to an AST expression.

    The returned AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs. Any filter
    list is translated via the general `property_to_expr`; filters the INSERT can't
    express fail the job and fall back to the live query automatically.
    """
    if not properties:
        return ast.Constant(value=True)
    return property_to_expr(properties, team=team)


def test_account_filter_expr(*, test_account_filters: list, team: Team) -> ast.Expr:
    """Convert the runner's resolved test-account filters into an AST.

    May return `ast.Constant(value=True)` when `filterTestAccounts=False` or
    the project has no test accounts configured.
    """
    if not test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(test_account_filters, team=team)


def floor_utc_day(dt_utc: datetime) -> datetime:
    return datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=UTC)


def ceil_utc_day(dt_utc: datetime) -> datetime:
    floor = floor_utc_day(dt_utc)
    if floor == dt_utc:
        return floor
    return floor + timedelta(days=1)
