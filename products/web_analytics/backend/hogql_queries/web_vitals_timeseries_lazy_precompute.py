import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.schema import (
    ChartDisplayType,
    EventsNode,
    IntervalType,
    TrendsQuery,
    WebVitalsMetric,
    WebVitalsPathBreakdownQuery,
    WebVitalsPercentile,
    WebVitalsQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_vitals_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models.team import Team
from posthog.week_start_day import WeekStartDay

from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    ceil_utc_day,
    floor_utc_day,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import handle_stale_served
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner
from products.web_analytics.backend.hogql_queries.web_vitals_paths_lazy_precompute import (
    can_use_lazy_precompute as can_use_vitals_paths_lazy_precompute,
    ensure_web_vitals_paths_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_vitals_timeseries import WebVitalsQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_vitals_timeseries"

VITALS_TIMESERIES_FLAG_KEY = "web-analytics-vitals-precompute"

WEB_VITALS_TIMESERIES_LAZY_FAILED = Counter(
    "web_vitals_timeseries_lazy_precompute_failed_total",
    "Web vitals timeseries lazy precompute path failures, by error class",
    ["error_type"],
)

# The four metric tabs, in the series order the frontend builds them. Each
# series carries `math_property=$web_vitals_<METRIC>_value` and the read maps
# it onto the matching quantile-state column of the shared vitals buckets.
_METRIC_ORDER: list[WebVitalsMetric] = [
    WebVitalsMetric.INP,
    WebVitalsMetric.LCP,
    WebVitalsMetric.CLS,
    WebVitalsMetric.FCP,
]

_MATH_PROPERTY_TO_METRIC: dict[str, WebVitalsMetric] = {
    f"$web_vitals_{metric.value}_value": metric for metric in _METRIC_ORDER
}

_METRIC_STATE_COLUMN: dict[WebVitalsMetric, str] = {
    WebVitalsMetric.INP: "inp_quantiles_state",
    WebVitalsMetric.LCP: "lcp_quantiles_state",
    WebVitalsMetric.CLS: "cls_quantiles_state",
    WebVitalsMetric.FCP: "fcp_quantiles_state",
}

# 1-based `arrayElement` index into the stored `quantiles(0.75, 0.90, 0.99)`
# reservoir. p95 is not stored, so the gate rejects it.
_MATH_TO_PCT_INDEX: dict[str, int] = {"p75": 1, "p90": 2, "p99": 3}

_MATH_TO_PERCENTILE: dict[str, WebVitalsPercentile] = {
    "p75": WebVitalsPercentile.P75,
    "p90": WebVitalsPercentile.P90,
    "p99": WebVitalsPercentile.P99,
}

# Buckets are team-tz daily, so hour interval cannot be served. Week/month
# group the daily keys the same way the trends preagg read does.
_BUCKET_EXPRS: dict[str, str] = {
    "day": "toDateTime(toStartOfDay(toTimeZone(time_window_start, %(tz)s)))",
    "week": "toDateTime(toStartOfWeek(toTimeZone(time_window_start, %(tz)s), {week_mode}))",
    "month": "toDateTime(toStartOfMonth(toTimeZone(time_window_start, %(tz)s)))",
}

_READ_SETTINGS = {"max_execution_time": 30}


def is_vitals_precompute_enabled_for_team(team: Team) -> bool:
    """Evaluate the vitals-timeseries rollout flag locally. Must never raise —
    it runs in dispatch and in cache-key generation, where an exception would
    fail the request instead of falling back. Fails closed on any error,
    mirroring the trends precompute ramp."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                VITALS_TIMESERIES_FLAG_KEY,
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
    except Exception:
        logger.exception("web_vitals_precompute_flag_check_failed", team_id=team.pk)
        return False


def vitals_timeseries_percentile(query: WebVitalsQuery, source: Optional[TrendsQuery] = None) -> Optional[str]:
    """Return the shared percentile math ('p75'/'p90'/'p99') when the query is
    the canonical Web Vitals tab shape, or None when the shape can't be served
    from the daily vitals buckets (caller falls back to the live trends path).

    The canonical shape is what `webAnalyticsLogic` builds: a TrendsQuery
    source with one `$web_vitals` EventsNode per metric, all carrying the same
    percentile math over `$web_vitals_<METRIC>_value`.
    """
    if source is None:
        source = query.source if isinstance(query.source, TrendsQuery) else None
    if source is None:
        return None
    if query.conversionGoal is not None:
        return None
    if query.compareFilter is not None and query.compareFilter.compare:
        return None
    if source.compareFilter is not None and source.compareFilter.compare:
        return None
    if source.breakdownFilter is not None:
        return None
    if source.samplingFactor is not None:
        # The live path samples events before computing the percentile; the
        # buckets hold the full-population quantile state, so a sampled source
        # would drift (same reason the sibling web_trends gate rejects it).
        return None
    if source.dateRange is not None and source.dateRange.daysOfWeek:
        # Live trends filters events to the selected weekdays (and drops the
        # deselected day buckets for day intervals); the bucket read merges every
        # day in range and emits the full axis, so it can't reproduce that.
        return None
    tf = source.trendsFilter
    if tf is not None:
        # Only the canonical line graph is servable. Total-value displays
        # collapse the range to one row and cumulative displays running-sum each
        # bucket; the per-bucket bucket read reproduces neither (same gate the
        # sibling web_trends runner applies).
        if tf.display is not None and tf.display != ChartDisplayType.ACTIONS_LINE_GRAPH:
            return None
        if tf.formula or tf.formulas or tf.formulaNodes:
            return None

    interval = (source.interval or IntervalType.DAY).value
    if interval not in _BUCKET_EXPRS:
        return None

    if len(source.series) != len(_METRIC_ORDER):
        return None
    shared_math: Optional[str] = None
    for series, expected_metric in zip(source.series, _METRIC_ORDER):
        if not isinstance(series, EventsNode):
            return None
        if series.event != "$web_vitals":
            return None
        if series.fixedProperties or series.properties:
            return None
        # The live path multiplies the property before computing the percentile;
        # the buckets store raw quantile state, so a multiplier would be silently
        # ignored (same reason the sibling web_trends gate rejects it).
        if series.math_multiplier is not None:
            return None
        math = str(series.math) if series.math is not None else ""
        if math not in _MATH_TO_PCT_INDEX:
            return None
        if shared_math is None:
            shared_math = math
        elif math != shared_math:
            return None
        if _MATH_PROPERTY_TO_METRIC.get(series.math_property or "") != expected_metric:
            return None
    return shared_math


def _build_inner_path_breakdown_query(
    query: WebVitalsQuery, source: TrendsQuery, percentile: WebVitalsPercentile
) -> WebVitalsPathBreakdownQuery:
    """Build the sibling path-breakdown tile's query for the same filters, so
    the ensure hashes to the same bucket family and both vitals tiles share
    one set of precomputed jobs. `metric` and `thresholds` only shape the
    sibling's read, not the insert, so constants are safe here. Filters come
    from the runner's effective source: dashboard filters mutate that copy,
    and building from the pristine wrapper would serve unfiltered buckets."""
    return WebVitalsPathBreakdownQuery(
        dateRange=source.dateRange,
        properties=list(source.properties or []),
        filterTestAccounts=source.filterTestAccounts,
        doPathCleaning=query.doPathCleaning,
        metric=WebVitalsMetric.INP,
        percentile=percentile,
        thresholds=[0.0, 0.0],
    )


def _read_timeseries(
    *,
    team: Team,
    interval: str,
    pct_index: int,
    job_ids: list[str],
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> dict[WebVitalsMetric, dict[datetime, float]]:
    week_mode = WeekStartDay(team.week_start_day or 0).clickhouse_mode
    bucket_expr = _BUCKET_EXPRS[interval].format(week_mode=week_mode)
    metric_cols = ",\n    ".join(
        # An empty reservoir merges to NaN; the live percentile math emits 0
        # for buckets with no samples, so mirror that.
        f"ifNotFinite(arrayElement(quantilesMergeIf(0.75, 0.90, 0.99)("
        f"{_METRIC_STATE_COLUMN[metric]}, and(time_window_start >= %(range_start)s, time_window_start < %(range_end)s)"
        f"), %(pct_index)s), 0) AS {metric.value.lower()}_value"
        for metric in _METRIC_ORDER
    )
    sql = f"""
SELECT {bucket_expr} AS bucket,
    {metric_cols}
FROM {DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
GROUP BY bucket
"""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_vitals_timeseries_lazy_query")
    rows = sync_execute(
        sql,
        {
            "team_id": team.pk,
            "job_ids": tuple(job_ids),
            "tz": team.timezone,
            "pct_index": pct_index,
            "range_start": range_start_utc,
            "range_end": range_end_utc,
        },
        settings=_READ_SETTINGS,
        team_id=team.pk,
    )
    result: dict[WebVitalsMetric, dict[datetime, float]] = {metric: {} for metric in _METRIC_ORDER}
    for row in rows:
        bucket = row[0].replace(tzinfo=None)
        for offset, metric in enumerate(_METRIC_ORDER):
            result[metric][bucket] = float(row[1 + offset])
    return result


def _series_dict(
    runner: "WebVitalsQueryRunner",
    *,
    order: int,
    series: EventsNode,
    metric_values: dict[datetime, float],
) -> dict[str, Any]:
    date_range = runner.query_date_range
    buckets = date_range.all_values()
    interval_name = date_range.interval_name
    day_fmt = "%Y-%m-%d %H:%M:%S" if interval_name in ("hour", "minute") else "%Y-%m-%d"

    data = [metric_values.get(bucket.replace(tzinfo=None), 0.0) for bucket in buckets]
    series_label = runner.series_event(series)

    return {
        "data": data,
        "labels": [format_label_date(item, date_range, runner.team.week_start_day) for item in buckets],
        "days": [item.strftime(day_fmt) for item in buckets],
        "count": float(sum(data)),
        "label": "All events" if series_label is None else series_label,
        "filter": runner._query_to_filter(),
        "action": {
            "days": date_range.all_values(),
            "id": series_label,
            "type": "events",
            "order": order,
            "name": series_label or "All events",
            "custom_name": series.custom_name,
            "math": series.math,
            "math_property": series.math_property,
            "math_hogql": series.math_hogql,
            "math_group_type_index": series.math_group_type_index,
            "properties": {},
        },
        "order": order,
    }


def execute_lazy_precomputed_vitals_timeseries(runner: "WebVitalsQueryRunner") -> Optional[list[dict[str, Any]]]:
    """Serve the Web Vitals tab timeseries from the shared vitals-paths preagg
    buckets — the same buckets the path-breakdown tile on the same tab keeps
    warm. Quantile states merge across paths into per-bucket tab-level
    percentiles. Returns the formatted results list, or None on any
    ineligibility/miss (caller falls back to the live trends path)."""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team = runner.team
    overall_started = time.perf_counter()
    try:
        shared_math = vitals_timeseries_percentile(runner.vitals_query, runner.query)
        if shared_math is None:
            return None
        if not is_vitals_precompute_enabled_for_team(team):
            return None

        inner_query = _build_inner_path_breakdown_query(
            runner.vitals_query, runner.query, _MATH_TO_PERCENTILE[shared_math]
        )
        # The shared gate already rejects teams with property access rules, so no
        # user-scoped restriction can reach a bucket read; the user is threaded
        # through anyway so the inner runner is never more privileged than the
        # request that spawned it.
        inner_runner = WebVitalsPathBreakdownQueryRunner(
            query=inner_query, team=team, modifiers=runner.modifiers, user=runner.user
        )
        if not can_use_vitals_paths_lazy_precompute(inner_runner):
            return None

        cur_buckets = runner.query_date_range.all_values()
        cur_to = runner.query_date_range.date_to()
        if not cur_buckets or cur_to is None:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None
        cur_start_utc = cur_buckets[0].astimezone(UTC)
        cur_end_utc = cur_to.astimezone(UTC)
        time_range_start = floor_utc_day(cur_start_utc)
        time_range_end = ceil_utc_day(cur_end_utc)
        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None

        result = ensure_web_vitals_paths_precomputed(
            runner=inner_runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        if result.stale:
            handle_stale_served(runner=inner_runner, family="web_vitals_paths")
        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            return None

        metric_values = _read_timeseries(
            team=team,
            interval=(runner.query.interval or IntervalType.DAY).value,
            pct_index=_MATH_TO_PCT_INDEX[shared_math],
            job_ids=[str(jid) for jid in result.job_ids],
            range_start_utc=cur_start_utc,
            range_end_utc=cur_end_utc,
        )

        results = [
            _series_dict(runner, order=order, series=series, metric_values=metric_values[_METRIC_ORDER[order]])
            for order, series in enumerate(runner.query.series)
            if isinstance(series, EventsNode)
        ]
        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_vitals_timeseries_lazy_precompute_served",
            team_id=team.pk,
            job_count=len(result.job_ids),
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return results
    except Exception as exc:
        WEB_VITALS_TIMESERIES_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_vitals_timeseries_lazy_precompute_failed",
            team_id=team.pk,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
