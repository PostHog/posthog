"""Shared eligibility gate + helpers for web-analytics lazy precompute paths.

Both the web overview lazy precompute and the web stats PATHS lazy precompute
share the same rollout/safety gate (org feature flag + per-query opt-in,
whole-hour timezone, no conversion goal, no sampling, no v2 UUID sessions,
precomputable user filters, bounded date range) and the same TTL /
session-pad / UTC-day helpers. Keeping a single source of truth avoids
the two paths drifting apart. See `validate_user_filters` for which filters
are precomputable and why.
"""

import json
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.conf import settings

import structlog
import posthoganalytics

from posthog.schema import (
    EventPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
    SessionsV2JoinMode,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.models import Team
from posthog.schema_enums import PersonsOnEventsMode

logger = structlog.get_logger(__name__)

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

# --- Expanded user-filter eligibility ----------------------------------------
# Gated per team via WEB_ANALYTICS_PRECOMPUTE_EXPANDED_FILTERS_TEAM_IDS.
#
# The precomputability rule
# -------------------------
# A precompute job bakes the user filter into its INSERT `WHERE` and stores the
# resulting aggregate keyed by the filter's hash; a read just serves that stored
# aggregate. So a filter is only safe to precompute if its truth value is a pure
# function of the events the job scans — it must not be able to change after the
# job runs unless the underlying events change. If it can change independently
# (dynamic / out-of-band state), the stored aggregate silently goes stale and we
# serve wrong numbers, and no TTL short enough saves us. We therefore gate on
# filter *type*, not on a curated key list (a key list neither bounds cardinality
# — `$pathname` is higher-cardinality than most — nor captures this rule):
#
#   - event   properties → always safe: evaluated directly against scanned events.
#   - session properties → always safe: derived from those same events.
#   - person  properties → safe ONLY under a person-on-events POE mode, where
#       `person.properties.*` resolves to the value stamped on the event at
#       ingestion (immutable). Under DISABLED / *_PROPERTIES_JOINED the same HogQL
#       joins the *current* persons table, so the value changes when a person is
#       updated — unsafe; falls through to raw. See `_EVENT_TIME_POE_MODES`.
#   - cohort / behavioral → never: membership is recomputed out-of-band, so a
#       baked job goes stale independently of its TTL.
#   - anything else (hogql, group, element, data warehouse, …) → not supported.
#
# Operators and values are unconstrained: the WHERE is built with the same
# `property_to_expr` the raw query uses, so the precompute matches raw by
# construction for any operator (icontains / gt / is_not / is_set / …) or value
# shape. We bound only the *number* of combined filters; per-filter cardinality
# is bounded by the job TTL — a one-off filter computes once (no costlier than
# the raw query it replaces) and then expires.
EXPANDED_MAX_FILTERS = 5

# POE modes under which `person.properties.*` resolves to the event-time-stamped
# value on the events table (deterministic) rather than a join to the current
# persons table. Person-property filters are precomputable only under these.
_EVENT_TIME_POE_MODES: frozenset[PersonsOnEventsMode] = frozenset(
    {
        PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
    }
)

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
    """Filter whose truth value isn't a function of the scanned events (cohort,
    behavioral, hogql, group, …) — can't be re-aggregated, so it falls through to raw."""

    def __init__(self, filter_type: object):
        self.filter_type = filter_type
        super().__init__(f"type={filter_type!r}")


class PersonFilterRequiresEventTimePoe(LazyPrecomputeIneligible):
    """Person-property filter under a POE mode that joins current person values
    (DISABLED / *_PROPERTIES_JOINED) — the stored aggregate would go stale on a
    person update, so it falls through to raw."""


class MissingDateRange(LazyPrecomputeIneligible):
    pass


class DateRangeOverMax(LazyPrecomputeIneligible):
    def __init__(self, days: int):
        self.days = days
        super().__init__(f"days={days} max={MAX_PRECOMPUTE_DAYS}")


def expanded_filters_enabled_for_team(team: Team) -> bool:
    return team.id in settings.WEB_ANALYTICS_PRECOMPUTE_EXPANDED_FILTERS_TEAM_IDS


def validate_user_filters(team: Team, properties: list) -> None:
    """Raise a `LazyPrecomputeIneligible` subclass if the user filters can't be precomputed.

    Single source of truth shared by both gates (`check_common_eligibility` and
    `check_common_eligible`) so the MVP and expanded paths can't drift between them.
    """
    if not properties:
        return

    if not expanded_filters_enabled_for_team(team):
        # MVP path — byte-identical to the original gate: <=1 EventPropertyFilter
        # on `$host`, operator exact, non-empty string value.
        if len(properties) > 1:
            raise TooManyFilters()
        prop = properties[0]
        if not isinstance(prop, EventPropertyFilter):
            raise NonEventPropertyFilter()
        if prop.key not in SUPPORTED_USER_FILTER_KEYS:
            raise UnsupportedFilterKey(prop.key)
        if prop.operator != PropertyOperator.EXACT:
            raise UnsupportedFilterOperator(prop.operator)
        if not isinstance(prop.value, str) or not prop.value:
            raise NonStringOrEmptyFilterValue()
        return

    # Expanded path (team-gated). Type-based, not key-based: admit event/session
    # filters unconditionally and person filters only under an event-time POE
    # mode; reject everything else. Any key/operator/value is fine because the
    # WHERE is built with `property_to_expr` (parity with raw by construction);
    # we bound only the filter count, with the TTL bounding per-filter cardinality.
    # See the precomputability rule above for the full reasoning.
    if len(properties) > EXPANDED_MAX_FILTERS:
        raise TooManyFilters()
    person_props_precomputable = team.person_on_events_mode in _EVENT_TIME_POE_MODES
    for prop in properties:
        if isinstance(prop, EventPropertyFilter | SessionPropertyFilter):
            continue
        if isinstance(prop, PersonPropertyFilter):
            if not person_props_precomputable:
                raise PersonFilterRequiresEventTimePoe()
            continue
        raise UnsupportedFilterType(getattr(prop, "type", type(prop).__name__))


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

    if use_web_analytics_precompute is not True:
        raise PerQueryOptInNotSet()

    if not is_integer_timezone(team.timezone):
        raise NonIntegerTimezone()

    if conversion_goal is not None:
        raise ConversionGoalUnsupported()

    if sampling is not None and getattr(sampling, "enabled", False):
        raise SamplingEnabled()

    if modifiers and getattr(modifiers, "sessionsV2JoinMode", None) == SessionsV2JoinMode.UUID:
        raise SessionsV2UuidMode()

    validate_user_filters(team, properties)

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


def host_filter_expr(properties: list, team: Team) -> ast.Expr:
    """Translate the gated user filter list to an AST expression.

    The returned AST is what `ensure_precomputed` hashes into the cache key —
    different filters therefore become different precomputed jobs.

    Expanded teams build the WHERE with `property_to_expr` (parity with the raw
    query). Non-expanded teams keep the exact `$host` equals(...) AST so existing
    jobs' cache keys don't churn.
    """
    if not properties:
        return ast.Constant(value=True)
    if expanded_filters_enabled_for_team(team):
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
