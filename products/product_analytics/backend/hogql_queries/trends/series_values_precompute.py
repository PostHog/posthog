from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from prometheus_client import Counter

from posthog.schema import (
    ActionsNode,
    ChartDisplayType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    IntervalType,
    PropertyGroupFilter,
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
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import (
    TrendsQueryRunner,
    resolve_series_custom_name,
)

logger = structlog.get_logger(__name__)

SERIES_VALUES_PRECOMPUTE_FAILED = Counter(
    "series_values_precompute_failed_total",
    "Trends series values precompute attempts that raised, by exception class",
    ["error_type"],
)
SERIES_VALUES_PRECOMPUTE_FALLBACK = Counter(
    "series_values_precompute_fallback_total",
    "Trends series values precompute attempts that fell back to the live query, by reason",
    ["reason"],
)
SERIES_VALUES_PRECOMPUTE_SUCCESS = Counter(
    "series_values_precompute_success_total",
    "Trends series values served from precompute",
)

INSERT_QUERY_TEMPLATE = """
SELECT
    hour AS time_window_start,
    '' AS series_key,
    [] AS breakdown_value,
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

TTL_SECONDS: dict[str, int] = {
    "1d": 6 * 60 * 60,
    "4d": 24 * 60 * 60,
    "default": 35 * 24 * 60 * 60,
}
MAX_WINDOW_DAYS = 7
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


def _properties(runner: TrendsQueryRunner) -> list[Any]:
    series = runner.query.series[0]
    assert isinstance(series, EventsNode)
    return [*(runner.query.properties or []), *(series.properties or [])]


def _shape_refusal(runner: TrendsQueryRunner) -> str | None:
    query = runner.query
    if len(query.series) != 1:
        return "series_count"
    series = query.series[0]
    if isinstance(series, ActionsNode):
        return "actions_node"
    if isinstance(series, DataWarehouseNode):
        return "data_warehouse_node"
    if not isinstance(series, EventsNode):
        return "unsupported_series_node"
    if series.math not in (None, "total") or any(
        value is not None
        for value in (series.math_property, series.math_hogql, series.math_multiplier, series.math_group_type_index)
    ):
        return "math"
    if series.fixedProperties:
        return "fixed_properties"
    if runner.breakdown_enabled:
        return "breakdown"
    if query.compareFilter is not None and query.compareFilter.compare:
        return "compare"
    if query.samplingFactor is not None and query.samplingFactor != 1:
        return "sampling"
    if query.conversionGoal is not None:
        return "conversion_goal"
    if query.marketingAnalyticsCostFallback is not None:
        return "marketing_cost_fallback"
    trends_filter = query.trendsFilter
    if trends_filter is not None:
        if trends_filter.formula or trends_filter.formulas or trends_filter.formulaNodes:
            return "formula"
        if trends_filter.display is not None and trends_filter.display not in _TIME_SERIES_DISPLAYS:
            return "display"
        if trends_filter.smoothingIntervals is not None and trends_filter.smoothingIntervals > 1:
            return "smoothing"
    if _interval(runner) not in _BUCKET_EXPRS:
        return "interval"
    if query.filterTestAccounts:
        return "test_account_filters"
    if query.dateRange is not None and query.dateRange.explicitDate:
        return "explicit_date"
    if query.dateRange is not None and query.dateRange.daysOfWeek:
        return "days_of_week"
    if isinstance(query.properties, PropertyGroupFilter):
        return "property_group"
    if any(get_property_type(prop) != "event" for prop in _properties(runner)):
        return "property_type"
    return None


def _team_refusal(runner: TrendsQueryRunner) -> str | None:
    if not is_integer_timezone(runner.team.timezone):
        return "timezone"
    if team_has_property_access_rules(team_id=runner.team.pk):
        return "property_access_rules"
    return None


def _crosses_dst(buckets: list[datetime]) -> bool:
    return len({bucket.utcoffset() for bucket in buckets}) > 1


def _range_unaligned(runner: TrendsQueryRunner, buckets: list[datetime], date_to: datetime) -> bool:
    date_range = runner.query_date_range
    if not date_range.use_start_of_interval() and date_range.date_from() != buckets[0]:
        return True
    end = date_to + timedelta(microseconds=1)
    return (end.minute, end.second, end.microsecond) != (0, 0, 0)


def _live_boundary(buckets: list[datetime], today_start_utc: datetime) -> datetime:
    boundary = buckets[0]
    for bucket in buckets:
        if bucket > today_start_utc:
            break
        boundary = bucket
    return boundary


def _ensure(runner: TrendsQueryRunner, *, start: datetime, end: datetime, run_inserts: bool) -> LazyComputationResult:
    series = runner.query.series[0]
    assert isinstance(series, EventsNode)
    properties = _properties(runner)
    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=start,
        time_range_end=end,
        ttl_seconds=parse_ttl_schedule(TTL_SECONDS, runner.team.timezone, max_window_days=MAX_WINDOW_DAYS),
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
        read_after_write=run_inserts,
        cache_key_context={"engine": "series_values_v1"},
    )


def _read_values(
    runner: TrendsQueryRunner, *, job_ids: list[str], start: datetime, end: datetime
) -> dict[datetime, int]:
    sql = f"""
SELECT {_BUCKET_EXPRS[_interval(runner)]} AS bucket, sum(value) AS value
FROM {DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
  AND time_window_start >= %(range_start)s AND time_window_start < %(range_end)s
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
            settings=_READ_SETTINGS,
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


def _fallback(reason: str) -> None:
    SERIES_VALUES_PRECOMPUTE_FALLBACK.labels(reason=reason).inc()


def execute_precomputed_trends(runner: TrendsQueryRunner, *, run_inserts: bool) -> list[dict[str, Any]] | None:
    try:
        reason = _shape_refusal(runner) or _team_refusal(runner)
        buckets = runner.query_date_range.all_values()
        date_to = runner.query_date_range.date_to()
        if reason is None and _interval(runner) == "hour" and _crosses_dst(buckets):
            reason = "dst_transition"
        if reason is None and (not buckets or date_to is None):
            reason = "nothing_closed"
        if reason is None and _range_unaligned(runner, buckets, date_to):
            reason = "unaligned_range"
        if reason is not None:
            _fallback(reason)
            return None
        assert date_to is not None

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
            _fallback("nothing_closed")
            return None

        range_start = read_start_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        range_end = read_end_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        if range_end < read_end_utc:
            range_end += timedelta(days=1)
        if (range_end - range_start).days > MAX_RANGE_DAYS:
            _fallback("date_range_too_long")
            return None

        result = _ensure(runner, start=range_start, end=range_end, run_inserts=run_inserts)
        if not result.ready or not result.job_ids:
            _fallback("not_ready")
            return None

        values = _read_values(
            runner, job_ids=[str(job_id) for job_id in result.job_ids], start=read_start_utc, end=read_end_utc
        )
        if live_from is not None:
            values.update(_live_tail_values(runner, live_from=live_from, date_to=date_to))

        SERIES_VALUES_PRECOMPUTE_SUCCESS.inc()
        return [_series_dict(runner, values)]
    except Exception as exc:
        SERIES_VALUES_PRECOMPUTE_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception("series_values_precompute_failed", team_id=runner.team.pk, error_type=type(exc).__name__)
        return None
