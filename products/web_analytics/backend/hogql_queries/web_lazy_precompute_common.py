"""Shared eligibility gate + helpers for web-analytics lazy precompute paths.

Both the web overview lazy precompute and the web stats PATHS lazy precompute
share the same rollout/safety gate (org feature flag + per-query opt-in,
whole-hour timezone, no conversion goal, no sampling, no v2 UUID sessions,
at most one `$host` exact filter, bounded date range) and the same TTL /
session-pad / UTC-day helpers. Keeping a single source of truth avoids
the two paths drifting apart.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import structlog
import posthoganalytics

from posthog.schema import EventPropertyFilter, PropertyOperator, SessionsV2JoinMode

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.models import Team

logger = structlog.get_logger(__name__)

# Hourly UTC bucketing TTL schedule. Today gets 15 min so dashboards stay
# fresh; older buckets get longer TTLs so we don't keep recomputing them.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
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
    if not is_org_feature_flag_enabled(team):
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


def host_filter_expr(properties: list) -> ast.Expr:
    """Translate the (gated-down-to-≤1) user filter list to an AST expression.

    The returned AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.
    """
    if not properties:
        return ast.Constant(value=True)
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
