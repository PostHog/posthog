import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from posthog.schema import (
    ActionsNode,
    ChartDisplayType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    IntervalType,
    PropertyGroupFilter,
    TrendsFilter,
)

from posthog.hogql import ast
from posthog.hogql.property import get_property_type, property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.series_values_preaggregated_sql import (
    DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import tags_context
from posthog.hogql_queries.utils.timestamp_utils import format_label_date

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ServedWindow,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.product_analytics.backend.facade.contracts import (
    PrecomputedSeriesValues,
    SeriesValuesBlocker as Blocker,
    SeriesValuesFeature as Feature,
    SeriesValuesUnavailable,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import (
    TrendsQueryRunner,
    resolve_series_custom_name,
)

logger = structlog.get_logger(__name__)

INSERT_QUERY_TEMPLATE = """
SELECT
    hour AS time_window_start,
    hour + toIntervalHour(1) AS time_window_end,
    '' AS series_key,
    toFloat(count()) AS value
FROM (
    SELECT toStartOfHour(timestamp) AS hour
    FROM events
    WHERE and(
        timestamp >= {time_window_min},
        timestamp < {time_window_max},
        {event_filter},
        {property_filter}
    )
)
GROUP BY hour
"""

# How long a stored window stays fresh. The key is the age of the window's start: under one day, under
# four days, then everything older. Late events still change recent days, so a recent window is rebuilt
# often and an old one is kept for weeks.
TTL_SECONDS: dict[str, int] = {
    "1d": 6 * 60 * 60,
    "4d": 24 * 60 * 60,
    "default": 35 * 24 * 60 * 60,
}
# One build job covers at most this many days. A long range then builds as several short INSERTs, and
# an expired or failed job rebuilds only its own days.
MAX_WINDOW_DAYS = 7
# A window that was built sooner than this after it ended is rebuilt once the time has passed, because
# events for it can still arrive.
LATE_EVENTS_SETTLING_SECONDS = 60 * 60
# A longer range is refused, so one query cannot start an unbounded number of build jobs. The limit is
# the days of a leap year.
MAX_RANGE_DAYS = 366

_BUCKET_EXPRS: dict[str, str] = {
    "hour": "toStartOfHour(toTimeZone(time_window_start, %(tz)s))",
    "day": "toDateTime(toStartOfDay(toTimeZone(time_window_start, %(tz)s)))",
}

_TIME_SERIES_DISPLAYS = {
    ChartDisplayType.ACTIONS_LINE_GRAPH,
    ChartDisplayType.ACTIONS_BAR,
    ChartDisplayType.ACTIONS_UNSTACKED_BAR,
    ChartDisplayType.ACTIONS_STACKED_BAR,
    ChartDisplayType.ACTIONS_AREA_GRAPH,
}

_READ_SETTINGS = {
    "load_balancing": "in_order",
    "optimize_skip_unused_shards": 1,
}


def _interval(runner: TrendsQueryRunner) -> str:
    return (runner.query.interval or IntervalType.DAY).value


def _properties(runner: TrendsQueryRunner, series: EventsNode) -> list[Any]:
    return [*(runner.query.properties or []), *(series.properties or [])]


def _trends_filter(runner: TrendsQueryRunner) -> TrendsFilter:
    return runner.query.trendsFilter or TrendsFilter()


def _counts_something_else(series: EventsNode) -> bool:
    extras = (series.math_property, series.math_hogql, series.math_multiplier, series.math_group_type_index)
    return series.math not in (None, "total") or any(value is not None for value in extras)


_Uses = Callable[[TrendsQueryRunner, EventsNode], bool]

# Features in shadow. A query that uses them still gets stored values, and its comparison is reported
# for each feature it used. A new feature starts here.
_SHADOW_FEATURES: dict[Feature, _Uses] = {
    Feature.EVENT_PROPERTY_FILTERS: lambda runner, series: bool(_properties(runner, series)),
}

# Features the stored path refuses. The first one a query uses is the reason it gets no stored values.
# The stored path counts the events of one series per hour, so it refuses what that count cannot reproduce.
_REFUSED_FEATURES: dict[Feature, _Uses] = {
    Feature.OTHER_MATH: lambda runner, series: _counts_something_else(series),
    Feature.FIXED_PROPERTIES: lambda runner, series: bool(series.fixedProperties),
    Feature.BREAKDOWN: lambda runner, series: runner.breakdown_enabled,
    Feature.COMPARE: lambda runner, series: bool(runner.query.compareFilter and runner.query.compareFilter.compare),
    Feature.SAMPLING: lambda runner, series: runner.query.samplingFactor not in (None, 1),
    Feature.QUERY_MODIFIERS: lambda runner, series: bool(
        runner.query.modifiers and runner.query.modifiers.model_dump(exclude_none=True)
    ),
    Feature.CONVERSION_GOAL: lambda runner, series: runner.query.conversionGoal is not None,
    Feature.MARKETING_COST_FALLBACK: lambda runner, series: runner.query.marketingAnalyticsCostFallback is not None,
    Feature.FORMULA: lambda runner, series: bool(
        _trends_filter(runner).formula or _trends_filter(runner).formulas or _trends_filter(runner).formulaNodes
    ),
    Feature.OTHER_DISPLAY: lambda runner, series: _trends_filter(runner).display not in (None, *_TIME_SERIES_DISPLAYS),
    Feature.SMOOTHING: lambda runner, series: (_trends_filter(runner).smoothingIntervals or 1) > 1,
    Feature.OTHER_INTERVAL: lambda runner, series: _interval(runner) not in _BUCKET_EXPRS,
    Feature.TEST_ACCOUNT_FILTERS: lambda runner, series: bool(runner.query.filterTestAccounts),
    Feature.EXPLICIT_DATE: lambda runner, series: bool(runner.query.dateRange and runner.query.dateRange.explicitDate),
    Feature.DAYS_OF_WEEK: lambda runner, series: bool(runner.query.dateRange and runner.query.dateRange.daysOfWeek),
    # Live Trends starts an all-time range at the first event of the series, not of the project.
    Feature.ALL_TIME_RANGE: lambda runner, series: bool(
        runner.query.dateRange and runner.query.dateRange.date_from == "all"
    ),
    Feature.PROPERTY_GROUP: lambda runner, series: isinstance(runner.query.properties, PropertyGroupFilter),
    Feature.OTHER_PROPERTY_TYPE: lambda runner, series: any(
        get_property_type(prop) != "event" for prop in _properties(runner, series)
    ),
}

_REFUSED_SERIES_KINDS: dict[type, Feature] = {
    ActionsNode: Feature.ACTION_SERIES,
    DataWarehouseNode: Feature.DATA_WAREHOUSE_SERIES,
}


def _counted_series(runner: TrendsQueryRunner) -> EventsNode | SeriesValuesUnavailable:
    if len(runner.query.series) != 1:
        return SeriesValuesUnavailable(reason=Feature.MULTIPLE_SERIES)
    series = runner.query.series[0]
    if not isinstance(series, EventsNode):
        return SeriesValuesUnavailable(reason=_REFUSED_SERIES_KINDS.get(type(series), Feature.OTHER_SERIES_KIND))
    return series


def _features_used(runner: TrendsQueryRunner, series: EventsNode) -> frozenset[Feature] | SeriesValuesUnavailable:
    for feature, uses in _REFUSED_FEATURES.items():
        if uses(runner, series):
            return SeriesValuesUnavailable(reason=feature)
    return frozenset(feature for feature, uses in _SHADOW_FEATURES.items() if uses(runner, series))


def _project_blocker(runner: TrendsQueryRunner) -> Blocker | None:
    if not is_integer_timezone(runner.team.timezone):
        return Blocker.TIMEZONE
    if team_has_property_access_rules(team_id=runner.team.pk):
        return Blocker.PROPERTY_ACCESS_RULES
    return None


def _crosses_dst(buckets: list[datetime]) -> bool:
    return len({bucket.utcoffset() for bucket in buckets}) > 1


def _first_or_last_bucket_is_partial(runner: TrendsQueryRunner, buckets: list[datetime], date_to: datetime) -> bool:
    # Stored rows are whole hours, so they cannot reproduce a bucket that the range cuts short.
    date_range = runner.query_date_range
    if not date_range.use_start_of_interval() and date_range.date_from() != buckets[0]:
        return True
    end = date_to + timedelta(microseconds=1)
    return (end.minute, end.second, end.microsecond) != (0, 0, 0)


def _range_blocker(runner: TrendsQueryRunner, buckets: list[datetime], date_to: datetime) -> Blocker | None:
    if _interval(runner) == "hour" and _crosses_dst(buckets):
        return Blocker.DST_TRANSITION
    if not buckets:
        return Blocker.NO_FINISHED_BUCKET
    if _first_or_last_bucket_is_partial(runner, buckets, date_to):
        return Blocker.PARTIAL_BUCKET
    return None


def _live_boundary(buckets: list[datetime], today_start_utc: datetime) -> datetime:
    boundary = buckets[0]
    for bucket in buckets:
        if bucket > today_start_utc:
            break
        boundary = bucket
    return boundary


def _covers(windows: tuple[ServedWindow, ...], start: datetime, end: datetime) -> bool:
    covered_until = start
    for window in sorted(windows, key=lambda window: window.start):
        if window.start > covered_until:
            return False
        covered_until = max(covered_until, window.end)
    return covered_until >= end


def _ensure(
    runner: TrendsQueryRunner,
    series: EventsNode,
    *,
    start: datetime,
    end: datetime,
    run_inserts: bool,
    wait_timeout_seconds: float | None = None,
    deadline: float | None = None,
) -> LazyComputationResult:
    properties = _properties(runner, series)
    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=start,
        time_range_end=end,
        ttl_seconds=parse_ttl_schedule(
            TTL_SECONDS,
            runner.team.timezone,
            max_window_days=MAX_WINDOW_DAYS,
            settling_period_seconds=LATE_EVENTS_SETTLING_SECONDS,
        ),
        table=LazyComputationTable.SERIES_VALUES_PREAGGREGATED,
        placeholders={
            "event_filter": (
                ast.Constant(value=True)
                if series.event is None
                else ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=series.event),
                )
            ),
            "property_filter": property_to_expr(properties, runner.team) if properties else ast.Constant(value=True),
        },
        query_type="series_values_insert",
        run_inserts=run_inserts,
        wait_timeout_seconds=wait_timeout_seconds,
        read_after_write=run_inserts,
        cache_key_context={"engine": "series_values_v1"},
        insert_deadline=deadline,
    )


def _read_values(
    runner: TrendsQueryRunner, *, job_ids: list[str], start: datetime, end: datetime, max_seconds: float | None
) -> dict[datetime, int]:
    sql = f"""
SELECT {_BUCKET_EXPRS[_interval(runner)]} AS bucket, sum(value) AS value
FROM {DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
  AND time_window_start >= %(range_start)s AND time_window_end <= %(range_end)s
  AND time_window_end > time_window_start
GROUP BY bucket
"""
    with tags_context(query_type="series_values_read"):
        rows = sync_execute(
            sql,
            {
                "team_id": runner.team.pk,
                "job_ids": tuple(job_ids),
                "tz": runner.team.timezone,
                "range_start": start,
                "range_end": end,
            },
            settings=_READ_SETTINGS
            if max_seconds is None
            else {**_READ_SETTINGS, "max_execution_time": max(1, math.ceil(max_seconds))},
            workload=runner.workload,
            team_id=runner.team.pk,
        )
    return {bucket.replace(tzinfo=None): int(value) for bucket, value in rows}


def _live_tail_values(runner: TrendsQueryRunner, *, live_from: datetime, date_to: datetime) -> dict[datetime, int]:
    live_query = runner.query.model_copy(deep=True)
    live_query.dateRange = DateRange(date_from=live_from.isoformat(), date_to=date_to.isoformat(), explicitDate=True)
    live_runner = TrendsQueryRunner(
        query=live_query,
        team=runner.team,
        modifiers=runner.modifiers,
        limit_context=runner.limit_context,
        user=runner.user,
        workload=runner.workload,
        ch_user=runner.ch_user,
        hogql_settings=runner.hogql_settings,
    )
    results = live_runner.calculate().results
    if not results:
        return {}
    buckets = live_runner.query_date_range.all_values()
    return {bucket.replace(tzinfo=None): value for bucket, value in zip(buckets, results[0]["data"])}


def _series_dict(runner: TrendsQueryRunner, values: dict[datetime, int]) -> dict[str, Any]:
    series = runner.query.series[0]
    series_label = runner.series_event(series)
    buckets = runner.query_date_range.all_values()
    day_format = "%Y-%m-%d %H:%M:%S" if runner.query_date_range.interval_name in ("hour", "minute") else "%Y-%m-%d"
    data = [values.get(bucket.replace(tzinfo=None), 0) for bucket in buckets]
    return {
        "data": data,
        "labels": [format_label_date(item, runner.query_date_range, runner.team.week_start_day) for item in buckets],
        "days": [item.strftime(day_format) for item in buckets],
        "count": float(sum(data)),
        "label": "All events" if series_label is None else series_label,
        "order": 0,
        "custom_name": resolve_series_custom_name(series, series_label),
    }


def precomputed_series_values(
    runner: TrendsQueryRunner, *, run_inserts: bool, wait_timeout_seconds: float | None = None
) -> PrecomputedSeriesValues | SeriesValuesUnavailable:
    # One deadline for the build and the read, so the call cannot outlast the caller's budget.
    deadline = None if wait_timeout_seconds is None else time.monotonic() + wait_timeout_seconds
    series = _counted_series(runner)
    if isinstance(series, SeriesValuesUnavailable):
        return series
    features = _features_used(runner, series)
    if isinstance(features, SeriesValuesUnavailable):
        return features
    buckets = runner.query_date_range.all_values()
    date_to = runner.query_date_range.date_to()
    blocker = _project_blocker(runner) or _range_blocker(runner, buckets, date_to)
    if blocker is not None:
        return SeriesValuesUnavailable(reason=blocker)

    now_utc = datetime.now(UTC)
    today_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    if date_to < today_start_utc:
        live_from = None
        read_end_utc = date_to.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        live_from = _live_boundary(buckets, today_start_utc)
        read_end_utc = live_from.astimezone(UTC)
    read_start_utc = buckets[0].astimezone(UTC)
    if read_start_utc >= read_end_utc:
        return SeriesValuesUnavailable(reason=Blocker.NO_FINISHED_BUCKET)

    range_start = read_start_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    range_end = read_end_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_end < read_end_utc:
        range_end += timedelta(days=1)
    if (range_end - range_start).days > MAX_RANGE_DAYS:
        return SeriesValuesUnavailable(reason=Blocker.DATE_RANGE_TOO_LONG)

    result = _ensure(
        runner,
        series,
        start=range_start,
        end=range_end,
        run_inserts=run_inserts,
        wait_timeout_seconds=wait_timeout_seconds,
        deadline=deadline,
    )
    # A job can expire while the executor collects its result. A day that no returned job covers would
    # read as zero.
    if not result.ready or not result.job_ids or not _covers(result.served_windows, range_start, range_end):
        return SeriesValuesUnavailable(reason=Blocker.NOT_READY)

    seconds_left = None if deadline is None else deadline - time.monotonic()
    if seconds_left is not None and seconds_left <= 0:
        return SeriesValuesUnavailable(reason=Blocker.NOT_READY)
    stored = _read_values(
        runner,
        job_ids=[str(job_id) for job_id in result.job_ids],
        start=read_start_utc,
        end=read_end_utc,
        max_seconds=seconds_left,
    )
    finished_buckets = [bucket.replace(tzinfo=None) for bucket in buckets if live_from is None or bucket < live_from]
    return PrecomputedSeriesValues(
        values={bucket: stored.get(bucket, 0) for bucket in finished_buckets},
        live_from=live_from,
        freshly_built=result.freshly_built,
        features=features,
    )


def execute_precomputed_trends(runner: TrendsQueryRunner, *, run_inserts: bool) -> list[dict[str, Any]] | None:
    try:
        precomputed = precomputed_series_values(runner, run_inserts=run_inserts)
        if isinstance(precomputed, SeriesValuesUnavailable):
            return None

        values = dict(precomputed.values)
        if precomputed.live_from is not None:
            date_to = runner.query_date_range.date_to()
            values.update(_live_tail_values(runner, live_from=precomputed.live_from, date_to=date_to))

        return [_series_dict(runner, values)]
    except Exception as exc:
        logger.exception("series_values_precompute_failed", team_id=runner.team.pk, error_type=type(exc).__name__)
        return None
