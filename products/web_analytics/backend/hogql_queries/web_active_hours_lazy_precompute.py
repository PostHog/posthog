"""Lazy precompute path for the Web Analytics Active Hours tile.

Backs the calendar-heatmap view of `$pageview` activity by hour-of-day x
day-of-week. Two metrics share one storage table:

- **Unique users** (math=`dau`): session-attributed. The INSERT groups events
  by `$session_id`, picks each session's earliest event, and emits a row in the
  hourly UTC bucket where the session started. The read merges those buckets
  into the (day-of-week, hour-of-day) grid via `toTimeZone(time_window_start,
  team_tz)`. This mirrors web overview's session-start attribution so the
  Active Hours tile's visitor counts align with the rest of the dashboard.
- **Total pageviews** (math=`total`): event-attributed. The INSERT bins events
  directly into hourly UTC buckets via `sumState(1)`. No session aggregation.

Each metric runs as a separate `ensure_precomputed` invocation with its own
`query_hash`, so the cache entries are independent and a team can populate one
tab without paying for the other.

Scoped to web analytics via `CalendarHeatmapFilter.useWebAnalyticsPrecompute`.
Setting the flag elsewhere has no effect unless the team's org also has the
`web-analytics-precompute-toggle` feature flag enabled.
"""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    CalendarHeatmapQuery,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapStructuredResult,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_active_hours_preaggregated_sql import (
    DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    LazyPrecomputeIneligible,
    ceil_utc_day,
    check_common_eligibility,
    floor_utc_day,
    log_eligibility_outcome,
    test_account_filter_expr,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_active_hours"


WEB_ACTIVE_HOURS_LAZY_FAILED = Counter(
    "web_active_hours_lazy_precompute_failed_total",
    "Lazy precompute path (active-hours tile) failures, by error class",
    ["error_type"],
)

WEB_ACTIVE_HOURS_LAZY_FALLBACK = Counter(
    "web_active_hours_lazy_precompute_fallback_total",
    "Lazy precompute fall-throughs after the gate accepted, by reason.",
    ["reason"],
)

WEB_ACTIVE_HOURS_LAZY_SUCCESS = Counter(
    "web_active_hours_lazy_precompute_success_total",
    "Requests served from the lazy precompute path.",
)

WEB_ACTIVE_HOURS_LAZY_REJECTED = Counter(
    "web_active_hours_lazy_precompute_rejected_total",
    "Requests refused by the lazy precompute gate, by reason.",
    ["reason"],
)


class WrongDisplay(LazyPrecomputeIneligible):
    pass


class UnsupportedMath(LazyPrecomputeIneligible):
    def __init__(self, math: object):
        self.math = math
        super().__init__(f"math={math!r}")


class UnsupportedSeriesShape(LazyPrecomputeIneligible):
    pass


class UnsupportedEvent(LazyPrecomputeIneligible):
    def __init__(self, event: object):
        self.event = event
        super().__init__(f"event={event!r}")


# Maths we'll accept. Anything else falls through to the raw path.
_SUPPORTED_MATHS: set[str] = {"dau", "total"}


def can_use_lazy_precompute(runner: "CalendarHeatmapQueryRunner") -> bool:
    """Return True iff this calendar-heatmap query can be served from the
    precompute table. Logs the rejection reason so every fall-through is
    attributable."""
    try:
        _check_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        reason = type(exc).__name__
        WEB_ACTIVE_HOURS_LAZY_REJECTED.labels(reason=reason).inc()
        log_eligibility_outcome(log_prefix="web_active_hours_lazy_precompute", team_id=runner.team.pk, error=exc)
        return False
    log_eligibility_outcome(log_prefix="web_active_hours_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def _check_eligible(runner: "CalendarHeatmapQueryRunner") -> None:
    query = runner.query
    assert isinstance(query, CalendarHeatmapQuery), "_check_eligible called on non-CalendarHeatmap runner"

    # Active-hours-specific gates first. These are cheaper than the org flag
    # round-trip and let us reject obvious shape mismatches without touching
    # the flag service.
    if not query.series or len(query.series) != 1:
        raise UnsupportedSeriesShape()
    series = query.series[0]
    event = getattr(series, "event", None)
    if event != "$pageview":
        raise UnsupportedEvent(event)
    math = getattr(series, "math", None)
    if math not in _SUPPORTED_MATHS:
        raise UnsupportedMath(math)

    # `useWebAnalyticsPrecompute` is the per-query opt-in. The shared gate
    # below also enforces the org-level feature flag, so both bars have to be
    # met for the precompute to engage.
    use_web_analytics_precompute = bool(
        query.calendarHeatmapFilter and query.calendarHeatmapFilter.useWebAnalyticsPrecompute
    )

    check_common_eligibility(
        team=runner.team,
        use_web_analytics_precompute=use_web_analytics_precompute,
        conversion_goal=query.conversionGoal,
        sampling=None,  # CalendarHeatmapQuery has no top-level sampling field
        # `modifiers=None` skips the shared UUID-session-mode rejection. That
        # gate matters for web overview because its `uniq_sessions_state` column
        # is typed `AggregateFunction(uniq, String)` — UUID mode would break the
        # INSERT. Active hours has no such column: the only `uniqState` argument
        # is `events.person_id` (always UUID), and `$session_id` only appears as
        # a GROUP BY key where the column type doesn't matter. Passing the
        # runner's modifiers would needlessly reject every default-mode query
        # since `create_default_modifiers_for_team` sets the mode to UUID.
        modifiers=None,
        properties=query.properties or [],
        resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
    )


# HogQL INSERT template for the unique-users tab. Session-attributed: group
# events by `$session_id`, attribute each session to the hour its first event
# fired, emit one `uniqState(person_id)` row per hourly bucket. Same shape and
# rationale as `web_overview_lazy_precompute.py`'s INSERT (forward-pad to catch
# events spilling past a daily UTC boundary; HAVING gates by session start).
#
# Note: `sum_events_state` is omitted intentionally — the framework derives the
# INSERT column list from SELECT aliases, so missing columns fall back to the
# CH type's default (empty AggregateFunction state). Reads for this metric only
# touch `uniq_users_state`, so the empty `sum_events_state` is never consulted.
_INSERT_UNIQUE_USERS_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    uniqState(session_person_id) AS uniq_users_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        equals(event, '$pageview'),
        timestamp >= {time_window_min},
        timestamp < ({time_window_max} + toIntervalMinute({pad_minutes})),
        {user_filter},
        {test_account_filter}
    )
    GROUP BY session_id
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start
"""


# HogQL INSERT template for the total-pageviews tab. Event-attributed: bin
# events directly into hourly UTC buckets via `sumState(1)`. No session
# aggregation, no forward pad needed — each event independently contributes
# to its own hour. `uniq_users_state` omitted, same rationale as above.
_INSERT_TOTAL_EVENTS_TEMPLATE = """
SELECT
    toStartOfHour(timestamp) AS time_window_start,
    sumState(toInt64(1)) AS sum_events_state
FROM events
WHERE and(
    equals(event, '$pageview'),
    timestamp >= {time_window_min},
    timestamp < {time_window_max},
    {user_filter},
    {test_account_filter}
)
GROUP BY time_window_start
"""


def _events_session_id_expr(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # Mirror what web analytics runners pick: `events.$session_id` in normal
    # mode, `events.$session_id_uuid` would be the UUID variant — gated out
    # by `SessionsV2JoinMode == uuid` upstream.
    return ast.Field(chain=["events", "$session_id"])


def _user_filter_expr(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # `property_to_expr` handles every event/session/person filter type and
    # operator HogQL supports. Empty list returns `True` so the INSERT WHERE
    # remains valid.
    if not runner.query.properties:
        return ast.Constant(value=True)
    return property_to_expr(runner.query.properties, team=runner.team)


def _test_account_filter_for_runner(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # Convert the runner's resolved test-account filter list into an AST. Empty
    # list returns `True`.
    if not runner.query.filterTestAccounts:
        return ast.Constant(value=True)
    test_account_filters = runner.team.test_account_filters or []
    return test_account_filter_expr(test_account_filters=test_account_filters, team=runner.team)


def ensure_active_hours_precomputed(
    runner: "CalendarHeatmapQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
    math: str,
) -> LazyComputationResult:
    """Run the INSERT side. `math` picks the template; the resulting query_hash
    differs by template so unique-users and total-pageviews jobs are isolated."""
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "user_filter": _user_filter_expr(runner),
        "test_account_filter": _test_account_filter_for_runner(runner),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    if math == "dau":
        insert_query = _INSERT_UNIQUE_USERS_TEMPLATE
        query_type = "web_active_hours_lazy_insert_dau"
    else:
        insert_query = _INSERT_TOTAL_EVENTS_TEMPLATE
        query_type = "web_active_hours_lazy_insert_total"

    return ensure_precomputed(
        team=runner.team,
        insert_query=insert_query,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_ACTIVE_HOURS_PREAGGREGATED,
        placeholders=placeholders,
        query_type=query_type,
    )


# Read query that returns four aggregation shapes in one round-trip:
# - `cells` array: per (day-of-week, hour-of-day) value
# - `days` array: per day-of-week aggregate (across all hours)
# - `hours` array: per hour-of-day aggregate (across all days)
# - `total`: overall aggregate
#
# The `_metric_expr` placeholder is `uniqMerge(uniq_users_state)` for the
# unique-users tab and `sumMerge(sum_events_state)` for the total-pageviews
# tab. uniq cannot be derived from cell sums (HLL doesn't add up), so each
# aggregation shape gets its own `GROUP BY`.
#
# `toTimeZone(time_window_start, %(team_tz)s)` shifts the stored UTC hour to
# the team's local time before binning into (day-of-week, hour-of-day). Reads
# stay correct for any whole-hour-offset timezone; half-hour-offset teams are
# gated out upstream via `is_integer_timezone`.
def _build_read_sql(metric_expr: str) -> str:
    return f"""
SELECT
    -- Per (day-of-week, hour-of-day) cells.
    groupArray(tuple(day, hour, cell_value)) AS cells
FROM (
    SELECT
        toDayOfWeek(toTimeZone(time_window_start, %(team_tz)s)) AS day,
        toHour(toTimeZone(time_window_start, %(team_tz)s)) AS hour,
        {metric_expr} AS cell_value
    FROM {DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}
    WHERE team_id = %(team_id)s
      AND job_id IN %(job_ids)s
      AND time_window_start >= %(cur_start)s
      AND time_window_start < %(cur_end)s
    GROUP BY day, hour
)
"""


def _build_day_sql(metric_expr: str) -> str:
    return f"""
SELECT
    toDayOfWeek(toTimeZone(time_window_start, %(team_tz)s)) AS day,
    {metric_expr} AS day_value
FROM {DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s
  AND job_id IN %(job_ids)s
  AND time_window_start >= %(cur_start)s
  AND time_window_start < %(cur_end)s
GROUP BY day
"""


def _build_hour_sql(metric_expr: str) -> str:
    return f"""
SELECT
    toHour(toTimeZone(time_window_start, %(team_tz)s)) AS hour,
    {metric_expr} AS hour_value
FROM {DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s
  AND job_id IN %(job_ids)s
  AND time_window_start >= %(cur_start)s
  AND time_window_start < %(cur_end)s
GROUP BY hour
"""


def _build_total_sql(metric_expr: str) -> str:
    return f"""
SELECT
    {metric_expr} AS total
FROM {DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s
  AND job_id IN %(job_ids)s
  AND time_window_start >= %(cur_start)s
  AND time_window_start < %(cur_end)s
"""


_READ_SETTINGS = {
    # Approach E from `products/analytics_platform/backend/lazy_computation/CONSISTENCY.md`:
    # both INSERT (via `_get_insert_settings`) and SELECT use `in_order` so they
    # deterministically prefer the same replica. Combined with the global
    # `distributed_foreground_insert=1`, the SELECT sees data the INSERT just wrote.
    "load_balancing": "in_order",
    # Shard pruning: sharding key is `sipHash64(job_id)`; `job_id IN (...)` matches
    # exactly the shards we wrote to.
    "optimize_skip_unused_shards": 1,
}


def _execute_read_query(
    *,
    team_id: int,
    team_tz: str,
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    math: str,
) -> EventsHeatMapStructuredResult:
    """Run four reads (cells / per-day / per-hour / total) and assemble the
    response shape the frontend expects.

    Bypasses HogQL because four aggregation shapes against the same window
    are easier to express as four parameterized SELECTs than as one HogQL
    query with subselects and arrayMap gymnastics.
    """
    metric_expr = "uniqMerge(uniq_users_state)" if math == "dau" else "sumMerge(sum_events_state)"
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type=f"web_active_hours_lazy_query_{math}")

    params = {
        "team_id": team_id,
        "team_tz": team_tz,
        "job_ids": tuple(str(jid) for jid in job_ids),
        "cur_start": current_start_utc,
        "cur_end": current_end_utc,
    }

    cells_rows = sync_execute(_build_read_sql(metric_expr), params, settings=_READ_SETTINGS, team_id=team_id)
    day_rows = sync_execute(_build_day_sql(metric_expr), params, settings=_READ_SETTINGS, team_id=team_id)
    hour_rows = sync_execute(_build_hour_sql(metric_expr), params, settings=_READ_SETTINGS, team_id=team_id)
    total_rows = sync_execute(_build_total_sql(metric_expr), params, settings=_READ_SETTINGS, team_id=team_id)

    cells: list[EventsHeatMapDataResult] = []
    # `cells_rows` is a single row containing an array of (day, hour, value) tuples.
    if cells_rows and cells_rows[0] and cells_rows[0][0]:
        for day, hour, value in cells_rows[0][0]:
            cells.append(EventsHeatMapDataResult(row=int(day), column=int(hour), value=int(value)))

    day_aggs: list[EventsHeatMapRowAggregationResult] = [
        EventsHeatMapRowAggregationResult(row=int(day), value=int(value)) for day, value in day_rows
    ]
    hour_aggs: list[EventsHeatMapColumnAggregationResult] = [
        EventsHeatMapColumnAggregationResult(column=int(hour), value=int(value)) for hour, value in hour_rows
    ]
    overall = int(total_rows[0][0]) if total_rows and total_rows[0] else 0

    return EventsHeatMapStructuredResult(
        data=cells, rowAggregations=day_aggs, columnAggregations=hour_aggs, allAggregations=overall
    )


def execute_lazy_precomputed_read(
    runner: "CalendarHeatmapQueryRunner",
) -> Optional[EventsHeatMapStructuredResult]:
    """Orchestrate the lazy precompute + read. Returns the heatmap result, or
    None on any failure (caller falls through to the raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the
    # INSERT `sync_execute` inside `ensure_active_hours_precomputed` doesn't
    # trip DEBUG-mode `UntaggedQueryError`. The read query overrides
    # `query_type` later inside `_execute_read_query`.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()

    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local interpretation when escaping
        # the datetime constants in the filter.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request.
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="empty_range").inc()
            return None

        math = runner.query.series[0].math
        assert isinstance(math, str)

        logger.info(
            "web_active_hours_lazy_precompute_started",
            team_id=team_id,
            math=math,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_active_hours_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            math=math,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)

        if not result.job_ids:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="current_not_ready").inc()
            return None

        read_started = time.perf_counter()
        response = _execute_read_query(
            team_id=team_id,
            team_tz=runner.team.timezone,
            job_ids=[str(jid) for jid in result.job_ids],
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            math=math,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)

        WEB_ACTIVE_HOURS_LAZY_SUCCESS.inc()
        logger.info(
            "web_active_hours_lazy_precompute_completed",
            team_id=team_id,
            math=math,
            job_count=len(result.job_ids),
            cells_returned=len(response.data),
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return response
    except Exception as exc:
        WEB_ACTIVE_HOURS_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_active_hours_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
