"""Shared lazy-precompute building blocks for web analytics query runners.

The web overview and web stats table runners both serve eligible queries from
on-demand precomputed ClickHouse tables via the `lazy_computation` framework.
The pieces that do not depend on which runner is calling — eligibility gating,
filter-expression construction, TTL/sizing constants, UTC-day helpers — live
here so both `web_overview_lazy_precompute.py` and `web_stats_lazy_precompute.py`
share one implementation.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Optional, Protocol, Union

import structlog
from prometheus_client import Counter

from posthog.schema import (
    EventPropertyFilter,
    PropertyOperator,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebVitalsPathBreakdownQuery,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.models.team import Team

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,  # noqa: F401 — re-exported; several runners import it from this module
    is_precompute_enabled_for_team,
    is_precompute_unrestricted_for_team,
)

logger = structlog.get_logger(__name__)


# Counts requests refused by `can_use_lazy_precompute`. `family` is the
# `log_prefix` (`web_overview` / `web_stats`); `reason` is the
# `LazyPrecomputeIneligible` subclass name. Together with `_fallback_total`
# and `_success_total`, callers can compute lazy adoption per family.
WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED = Counter(
    "web_analytics_lazy_precompute_rejected_total",
    "Requests refused by the lazy precompute gate, by family and rejection reason.",
    ["family", "reason"],
)

# Counts requests that passed the gate but couldn't be served from precompute
# (window empty, no jobs created, current/previous period not yet READY). The
# caller falls back to the raw / v2 path on each of these.
WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK = Counter(
    "web_analytics_lazy_precompute_fallback_total",
    "Lazy precompute fall-throughs after the gate accepted, by family and reason.",
    ["family", "reason"],
)

# Counts requests where the lazy path successfully returned a precomputed row.
WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS = Counter(
    "web_analytics_lazy_precompute_success_total",
    "Requests served from the lazy precompute path, by family.",
    ["family"],
)

# Today the gate accepts: empty user filters, or a single EventPropertyFilter
# on `$host` with operator `exact`. Test-account filters are always allowed
# (their content is hashed into the cache key).
SUPPORTED_USER_FILTER_KEYS: set[str] = {"$host"}

# Upper bound on the precompute span. Above this, the framework would create
# enough daily jobs that the first request burns INSERT slots for minutes.
MAX_PRECOMPUTE_DAYS = 90

# Forward pad on the per-job event-scan window. The lazy_computation framework
# chunks the precompute span into daily UTC jobs; each job covers
# `[time_window_min, time_window_max)`. A session starting at 23:50 with events
# spilling past midnight would lose its trailing events without a forward pad —
# the HAVING clause attributes the session to its start hour, but the events
# table scan needs to see those trailing events to compute correct per-session
# aggregates. Forward-only is sufficient: the HAVING keeps only sessions whose
# `min(session.$start_timestamp)` falls inside the job window, and every event
# of such a session has `timestamp >= session.$start_timestamp`, so backward
# scanning never picks up anything that survives HAVING.
#
# Sessions longer than 24 h crossing a UTC-day boundary are silently
# undercounted — a documented limitation, not a sizing target (24 h is the
# posthog-js hard cap, covering effectively the whole population).
SESSION_FORWARD_PAD_MINUTES = 24 * 60


class LazyPrecomputeRunner(Protocol):
    """Structural type for the attributes the shared helpers read off a runner.

    `WebOverviewQueryRunner`, `WebStatsTableQueryRunner` and
    `WebVitalsPathBreakdownQueryRunner` all satisfy this.
    """

    team: Team

    @property
    def query(self) -> Union[WebOverviewQuery, WebStatsTableQuery, WebVitalsPathBreakdownQuery]: ...

    @property
    def query_date_range(self) -> object: ...

    @property
    def _test_account_filters(self) -> list: ...

    @property
    def events_session_property(self) -> ast.Expr: ...


class LazyPrecomputeIneligible(Exception):
    """Base class for reasons the lazy precompute path is not eligible.

    Raised by the eligibility checks and caught by `can_use_lazy_precompute`,
    which logs the exception class name. Subclass names are the canonical
    identifiers used in logs/metrics — keep them stable across releases.
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


def can_use_lazy_precompute(
    runner: LazyPrecomputeRunner,
    *,
    log_prefix: str,
    extra_check: Optional[Callable[[LazyPrecomputeRunner], None]] = None,
    require_integer_timezone: bool = True,
) -> bool:
    """Return True iff the lazy precompute gate is eligible. Logs the rejection
    reason at INFO level so every fall-through can be attributed.

    `log_prefix` differentiates the log event name per runner (e.g.
    `web_overview` / `web_stats`). `extra_check` lets a runner add its own
    eligibility checks — it must raise a `LazyPrecomputeIneligible` subclass on
    rejection, and runs after the shared checks pass. `require_integer_timezone`
    can be opted out by runners whose bucket key is computed in the team's
    timezone (and therefore aligns cleanly for half-hour-offset teams too).
    """
    try:
        check_common_eligible(runner, require_integer_timezone=require_integer_timezone)
        if extra_check is not None:
            extra_check(runner)
    except LazyPrecomputeIneligible as exc:
        reason = type(exc).__name__
        WEB_ANALYTICS_LAZY_PRECOMPUTE_REJECTED.labels(family=log_prefix, reason=reason).inc()
        logger.info(
            f"{log_prefix}_lazy_precompute_rejected",
            team_id=runner.team.pk,
            reason=reason,
            detail=str(exc) or None,
        )
        return False
    logger.info(
        f"{log_prefix}_lazy_precompute_eligible",
        team_id=runner.team.pk,
    )
    return True


def check_common_eligible(runner: LazyPrecomputeRunner, *, require_integer_timezone: bool = True) -> None:
    """Raise a `LazyPrecomputeIneligible` subclass if the query can't go through
    the lazy path on grounds that apply to every web analytics runner. Returns
    None on success.

    `require_integer_timezone` defaults to True for hourly-UTC-bucketed runners
    (overview, stats). Runners that bucket in the team's timezone can opt out.
    """
    query = runner.query

    # Rollout gate: shared PostHog feature flag AND per-query opt-in.
    #   - `web-analytics-precompute-toggle` (PostHog feature flag): the same
    #     flag the frontend already uses to show/hide the "Allow precompute"
    #     button in the Web Analytics ScenePanel. The flag is evaluated at the
    #     organization level. The SDK swallows its own exceptions and returns
    #     None (falsy) on failure, so a flag-service outage fails-closed.
    #   - `query.useWebAnalyticsPrecompute` (per-query parameter set by the
    #     "Allow precompute" toggle).
    if not is_precompute_enabled_for_team(runner.team):
        raise OrgFeatureFlagDisabled()

    unrestricted = is_precompute_unrestricted_for_team(runner.team)

    # Unrestricted teams default to opt-out: only an explicit `False` rejects.
    # Restricted teams keep the opt-in default (`None`/`False` both reject).
    if unrestricted:
        if query.useWebAnalyticsPrecompute is False:
            raise PerQueryOptedOut()
    elif query.useWebAnalyticsPrecompute is not True:
        raise PerQueryOptInNotSet()

    # Half-hour-offset timezones (IST +5:30, Newfoundland -3:30, Nepal +5:45, etc.)
    # can't be served by UTC hourly buckets without sub-hour precision. Skip them
    # rather than return wrong totals on the boundary days. Runners that bucket
    # by team-tz day instead (e.g. web vitals) can opt out of this check.
    if require_integer_timezone and not is_integer_timezone(runner.team.timezone):
        raise NonIntegerTimezone()

    if query.conversionGoal is not None:
        raise ConversionGoalUnsupported()

    if query.sampling is not None and getattr(query.sampling, "enabled", False):
        raise SamplingEnabled()

    # UUID session-id mode produces `uniqState(UUID)` from
    # `events.$session_id_uuid`, which fails to insert into the web overview
    # table's `uniq_sessions_state AggregateFunction(uniq, String)` column. The
    # web stats table has no session-uniq column (it stores `uniq, UUID` user
    # state only), so this gate is conservative there — kept shared for
    # simplicity until the web overview column is re-typed in a follow-up.
    if query.modifiers and query.modifiers.sessionsV2JoinMode == "uuid":
        raise SessionsV2UuidMode()

    # Unrestricted teams accept any filter shape — `user_filter_expr` translates
    # arbitrary filters via `property_to_expr`, and each distinct filter set
    # becomes a distinct cache key. Filters the INSERT can't express fail the
    # job and fall back to the live query automatically.
    if not unrestricted:
        properties = query.properties or []
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

    date_from = runner.query_date_range.date_from()  # type: ignore[attr-defined]
    date_to = runner.query_date_range.date_to()  # type: ignore[attr-defined]
    if date_from is None or date_to is None:
        raise MissingDateRange()

    days = (date_to - date_from).days
    if days > MAX_PRECOMPUTE_DAYS:
        raise DateRangeOverMax(days)


def user_filter_expr(runner: LazyPrecomputeRunner) -> ast.Expr:
    """Build the AST expression that gets substituted into the INSERT's WHERE clause.

    The substituted AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.
    """
    if not runner.query.properties:
        return ast.Constant(value=True)

    # Unrestricted teams may pass arbitrary filters — translate the whole list
    # via the general `property_to_expr`. Each distinct filter set becomes a
    # distinct cache key.
    if is_precompute_unrestricted_for_team(runner.team):
        return property_to_expr(runner.query.properties, team=runner.team)

    # Gate already enforces single EventPropertyFilter with $host exact + string value.
    host_filter = runner.query.properties[0]
    assert isinstance(host_filter, EventPropertyFilter)
    return ast.Call(
        name="equals",
        args=[
            ast.Field(chain=["events", "properties", host_filter.key]),
            ast.Constant(value=host_filter.value),
        ],
    )


def test_account_filter_expr(runner: LazyPrecomputeRunner) -> ast.Expr:
    """Test-account filters land in the placeholder set, so they also shape the cache key.

    `_test_account_filters` may be an empty list when filterTestAccounts is False
    or the project has none configured.
    """
    if not runner._test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(runner._test_account_filters, team=runner.team)


def events_session_id_expr(runner: LazyPrecomputeRunner) -> ast.Expr:
    return runner.events_session_property


def floor_utc_day(dt_utc: datetime) -> datetime:
    return datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=UTC)


def ceil_utc_day(dt_utc: datetime) -> datetime:
    floor = floor_utc_day(dt_utc)
    if floor == dt_utc:
        return floor
    return floor + timedelta(days=1)
