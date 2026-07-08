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

from posthog.schema import EventPropertyFilter, PropertyOperator, SessionsV2JoinMode

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog import redis
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


def web_ensure_precomputed(*, team: Team, **kwargs: Any) -> LazyComputationResult:
    """`ensure_precomputed` for web analytics, with reactive per-team OOM capping.

    A team runs uncapped until one of its precompute inserts OOMs; that pins it so later
    requests build their TTL schedule with a 1-day `max_window_days` cap (job width bounded
    at any window age). The request that hits the OOM still fails here and falls back to the
    live query — the cap only takes effect next time.
    """
    pinned = is_team_oom_pinned(team.id)
    if pinned and "ttl_seconds" in kwargs:
        existing = kwargs["ttl_seconds"]
        # Stamp the width cap onto whatever schedule the caller passed: an int/dict gets
        # parsed with the cap; an already-built TtlSchedule (also accepted by
        # ensure_precomputed) just gets the cap re-stamped — parse_ttl_schedule can't take one.
        if isinstance(existing, TtlSchedule):
            kwargs["ttl_seconds"] = replace(existing, max_window_days=OOM_PIN_WINDOW_DAYS)
        else:
            kwargs["ttl_seconds"] = parse_ttl_schedule(existing, team.timezone, max_window_days=OOM_PIN_WINDOW_DAYS)
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
# 1. Freshness — today gets 2h (recomputing it more often buys nothing: the ~6h
#    HogQL result cache already fronts these queries, so a cache hit never reads
#    the precompute). Older windows get progressively longer TTLs.
# 2. Job sizing — `split_ranges_by_ttl` merges *consecutive days with the same
#    TTL* into one job. Distinct per-week TTLs therefore force weekly job
#    boundaries, so a 31-day warm splits into ≤7-day jobs instead of one ~24-day
#    block. That keeps each per-day INSERT's events↔sessions scan bounded — the
#    24-day merge is what drove the multi-hundred-million-row scans that OOM the
#    insert on very high-traffic teams.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 2 * 60 * 60,  # today
    "1d": 60 * 60,  # yesterday
    "7d": 24 * 60 * 60,  # days 2–7   → one ~6d job
    "14d": 2 * 24 * 60 * 60,  # days 8–14  → one 7d job
    "21d": 4 * 24 * 60 * 60,  # days 15–21 → one 7d job
    "28d": 7 * 24 * 60 * 60,  # days 22–28 → one 7d job
    "35d": 10 * 24 * 60 * 60,  # days 29–35 → one 7d job (covers the tail of a 31d warm)
    "default": 14 * 24 * 60 * 60,  # days 36+
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
