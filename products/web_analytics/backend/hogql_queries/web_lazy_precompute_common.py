"""Shared eligibility gate + helpers for web-analytics lazy precompute paths.

Both the web overview lazy precompute and the web stats PATHS lazy precompute
share the same rollout/safety gate (org feature flag + per-query opt-in,
whole-hour timezone, no conversion goal, no sampling, no v2 UUID sessions,
at most one `$host` exact filter, bounded date range) and the same TTL /
session-pad / UTC-day helpers. Keeping a single source of truth avoids
the two paths drifting apart.
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

from posthog.schema import EventPropertyFilter, PropertyOperator, SessionsV2JoinMode

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog import redis
from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, tag_queries
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
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

# Requests tagged with any of these triggers ARE the refresh mechanism: they must never
# be served stale (they'd freeze the cache serving stale to themselves) and they keep
# the framework's full wait budget. This named set is the belt; the primary gate in
# `is_background_warming_request` is the CACHE_WARMUP feature tag, which classifies
# refreshers by category — including warmers this module doesn't know by name (e.g.
# the generic insight cache warmer, trigger "warmingV2"), which would otherwise be
# served stale and persist it into the insight cache under a fresh timestamp.
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
    if get_query_tag_value("feature") == Feature.CACHE_WARMUP:
        return True
    return get_query_tag_value("trigger") in BACKGROUND_WARMING_TRIGGERS


def enqueue_stale_revalidation(*, team: Team, query: Any, family: str) -> None:
    """Enqueue a background re-run of `query` so a stale-served read gets fresh data next time.

    Best-effort: this runs on the user-facing read path before the stale rows are read,
    so a broker outage must degrade to "serve stale, warmer converges" — never abort the
    read into the expensive live fallback.
    """
    # The task module imports this module (for the trigger constant), so the reverse
    # import must stay local to avoid a cycle.
    from products.web_analytics.backend.tasks.lazy_precompute_revalidation import (  # noqa: PLC0415
        revalidate_web_analytics_precompute,
    )

    try:
        revalidate_web_analytics_precompute.delay(
            team_id=team.id, query=query.model_dump(mode="json", exclude_none=True)
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
    stale-served vs fresh reads, and enqueues the background revalidation. Enqueues at
    most once per request: the `precompute_stale` tag it sets doubles as the marker, so
    a compare-period ensure coming back stale after the current-period one doesn't mint
    a second task for the same query (one re-run covers both periods).
    """
    WEB_ANALYTICS_LAZY_PRECOMPUTE_STALE_SERVED.labels(family=family).inc()
    already_handled = get_query_tag_value("precompute_stale") is True
    tag_queries(precompute_stale=True)
    if already_handled:
        return
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
    if "stale_while_revalidate_seconds" not in kwargs:
        kwargs["stale_while_revalidate_seconds"] = (
            None if is_background_warming_request() else STALE_WHILE_REVALIDATE_SECONDS
        )
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


class PerQueryOptInNotSet(LazyPrecomputeIneligible):
    pass


class PerQueryOptedOut(LazyPrecomputeIneligible):
    """Unrestricted team where the user explicitly turned precompute off."""

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


def is_precompute_unrestricted_for_team(team: Team) -> bool:
    """Whether a team may precompute *any* web analytics query.

    Unrestricted teams bypass the single-`$host`-exact filter-shape gate (any
    property filter becomes a distinct cache key) and treat the per-query toggle
    as opt-out rather than opt-in. Driven by the dedicated
    `WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS` env-var setting.
    """
    return team.id in settings.WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS


def is_precompute_enabled_for_team(team: Team) -> bool:
    """Whether a team should take the lazy precompute path.

    Short-circuits on the `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` env-var
    setting before evaluating the org rollout flag. The list is the shared
    source of truth with the eager warmer, and — unlike the flag — does not rely
    on local flag-definition evaluation, which isn't reliably available outside
    the Django app (e.g. the Dagster warmer, where `only_evaluate_locally`
    returned falsy and silently dropped the warmer onto the raw path).

    Unrestricted teams are implicitly enrolled — membership in the unrestricted
    list is enough, so a team need not appear in both settings.
    """
    if team.id in settings.WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS:
        return True
    if is_precompute_unrestricted_for_team(team):
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

    unrestricted = is_precompute_unrestricted_for_team(team)

    # Unrestricted teams default to opt-out: only an explicit `False` rejects.
    # Restricted teams keep the opt-in default (`None`/`False` both reject).
    if unrestricted:
        if use_web_analytics_precompute is False:
            raise PerQueryOptedOut()
    elif use_web_analytics_precompute is not True:
        raise PerQueryOptInNotSet()

    if not is_integer_timezone(team.timezone):
        raise NonIntegerTimezone()

    if conversion_goal is not None:
        raise ConversionGoalUnsupported()

    if sampling is not None and getattr(sampling, "enabled", False):
        raise SamplingEnabled()

    if modifiers and getattr(modifiers, "sessionsV2JoinMode", None) == SessionsV2JoinMode.UUID:
        raise SessionsV2UuidMode()

    # Unrestricted teams accept any filter shape — `host_filter_expr` translates
    # arbitrary filters via `property_to_expr`, and each distinct filter set
    # becomes a distinct cache key. Filters the INSERT can't express fail the
    # job and fall back to the live query automatically.
    if not unrestricted:
        if len(properties) > 1:
            raise TooManyFilters()
        for prop in properties:
            if not isinstance(prop, EventPropertyFilter):
                raise NonEventPropertyFilter()
            if prop.key not in SUPPORTED_USER_FILTER_KEYS:
                raise UnsupportedFilterKey(prop.key)
            if prop.operator != PropertyOperator.EXACT:
                raise UnsupportedFilterOperator(prop.operator)
            if not isinstance(prop.value, str) or not prop.value:
                raise NonStringOrEmptyFilterValue()

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
    dumped = query.model_dump(mode="json", exclude_none=True, by_alias=False)
    for key in _FILTERS_ELIGIBILITY_HASH_IGNORED_QUERY_FIELDS:
        dumped.pop(key, None)
    payload = {"query": dumped, "timezone": team_timezone}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def host_filter_expr(properties: list, *, team: Team) -> ast.Expr:
    """Translate the user filter list to an AST expression.

    The returned AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.

    Unrestricted teams may pass arbitrary filters, so their list is translated
    via the general `property_to_expr`. Restricted teams keep the hand-built
    single-`$host` `equals` so their existing cache keys don't churn.
    """
    if not properties:
        return ast.Constant(value=True)
    if is_precompute_unrestricted_for_team(team):
        return property_to_expr(properties, team=team)
    host_filter = properties[0]
    assert isinstance(host_filter, EventPropertyFilter)
    return ast.Call(
        name="equals",
        args=[
            ast.Field(chain=["events", "properties", host_filter.key]),
            ast.Constant(value=host_filter.value),
        ],
    )


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
