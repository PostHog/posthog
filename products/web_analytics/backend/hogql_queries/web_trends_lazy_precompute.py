import time
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.schema import (
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsQuery,
    WebOverviewQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.query_runner import resolve_series_custom_name
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models.team import Team
from posthog.week_start_day import WeekStartDay

from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    floor_utc_day,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import handle_stale_served
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
    _READ_SETTINGS,
    ensure_web_overview_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_trends import WebTrendsQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_trends"

TRENDS_PRECOMPUTE_FLAG_KEY = "web-analytics-trends-precompute"

WEB_TRENDS_LAZY_FAILED = Counter(
    "web_trends_lazy_precompute_failed_total",
    "Web trends lazy precompute path failures, by error class",
    ["error_type"],
)


class WebTrendsMetric(Enum):
    UNIQUE_USERS = "unique_users"
    VIEWS = "views"
    UNIQUE_SESSIONS = "unique_sessions"
    AVG_DURATION = "avg_duration"
    BOUNCE_RATE = "bounce_rate"


# Merge expressions over web_overview_preaggregated states. Keyed by enum, never
# interpolated from user input. avg merges are NaN when a bucket group has no
# rows with a non-null state — coerce to 0 like the overview read consumers do.
_METRIC_EXPRS: dict[WebTrendsMetric, str] = {
    WebTrendsMetric.UNIQUE_USERS: "uniqMerge(uniq_users_state)",
    WebTrendsMetric.VIEWS: "sumMerge(sum_pageviews_state)",
    WebTrendsMetric.UNIQUE_SESSIONS: "uniqMerge(uniq_sessions_state)",
    WebTrendsMetric.AVG_DURATION: "ifNotFinite(avgMerge(avg_duration_state), 0)",
    WebTrendsMetric.BOUNCE_RATE: "ifNotFinite(avgMerge(avg_bounce_state), 0)",
}

# Interval → team-local bucket truncation over the hourly-UTC bucket key. The
# shared gate already restricts to whole-hour timezone offsets, so tz conversion
# followed by truncation is exact. Week mode comes from team.week_start_day and
# is formatted in (server-side constant, not user input). The toDateTime wraps
# keep the driver returning datetimes for week/month (toStartOfWeek/Month return
# Dates).
_BUCKET_EXPRS: dict[str, str] = {
    "hour": "toStartOfHour(toTimeZone(time_window_start, %(tz)s))",
    "day": "toDateTime(toStartOfDay(toTimeZone(time_window_start, %(tz)s)))",
    "week": "toDateTime(toStartOfWeek(toTimeZone(time_window_start, %(tz)s), {week_mode}))",
    "month": "toDateTime(toStartOfMonth(toTimeZone(time_window_start, %(tz)s)))",
}

_SUPPORTED_INTERVALS = set(_BUCKET_EXPRS.keys())

_SUPPORTED_EVENTS = ("$pageview", "$screen")


def is_trends_precompute_enabled_for_team(team: Team) -> bool:
    """Independent ramp for the trends path, on top of the shared precompute
    enrollment the inner gate still enforces. Must never raise — it runs in
    dispatch and in cache-key generation, where an exception would fail the
    request instead of falling back. Fails closed on any error."""
    try:
        if team.id in settings.WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS:
            return True
        return _flag_enabled(team)
    except Exception:
        logger.exception("web_trends_precompute_flag_check_failed", team_id=team.pk)
        return False


def _flag_enabled(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            TRENDS_PRECOMPUTE_FLAG_KEY,
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


def trends_precompute_metric(query: TrendsQuery) -> Optional[WebTrendsMetric]:
    """Map a TrendsQuery onto a servable preagg metric, or None when the shape
    can't be served from the overview buckets (caller falls back to the live
    trends path). The allowlist is deliberately narrow: it must only admit
    shapes whose semantics the session-start-attributed hourly buckets can
    reproduce."""
    if len(query.series) != 1:
        return None
    series = query.series[0]
    if not isinstance(series, EventsNode):
        return None
    if series.event not in _SUPPORTED_EVENTS:
        return None
    if series.fixedProperties:
        return None

    if query.breakdownFilter is not None:
        return None
    if query.conversionGoal is not None:
        return None
    if query.aggregation_group_type_index is not None:
        return None
    if query.samplingFactor is not None:
        return None

    tf = query.trendsFilter
    if tf is not None:
        if tf.display is not None and tf.display != ChartDisplayType.ACTIONS_LINE_GRAPH:
            return None
        if tf.formula or tf.formulas or tf.formulaNodes:
            return None
        if tf.smoothingIntervals is not None and tf.smoothingIntervals > 1:
            return None
        if tf.hideWeekends:
            return None

    interval = (query.interval or IntervalType.DAY).value
    if interval not in _SUPPORTED_INTERVALS:
        return None

    if query.properties is not None and not isinstance(query.properties, list):
        return None

    if query.dateRange is not None and (query.dateRange.explicitDate or query.dateRange.daysOfWeek):
        return None

    math = series.math
    math_property = series.math_property
    if math == "dau":
        return WebTrendsMetric.UNIQUE_USERS
    if math == "total" or math is None:
        return WebTrendsMetric.VIEWS
    if math == "unique_session":
        return WebTrendsMetric.UNIQUE_SESSIONS
    # The live path multiplies the property before averaging; the buckets
    # store the raw aggregate state, so a multiplier would be silently ignored.
    if getattr(series, "math_multiplier", None) is not None:
        return None
    # Session-property averages only: an avg over an event-property with the
    # same name aggregates per event, not per deduped session, and the live
    # path treats those differently — the buckets can't reproduce that.
    if math == "avg" and getattr(series, "math_property_type", None) == "session_properties":
        if math_property == "$session_duration":
            return WebTrendsMetric.AVG_DURATION
        if math_property == "$is_bounce":
            return WebTrendsMetric.BOUNCE_RATE
    return None


def effective_properties(query: TrendsQuery) -> list[Any]:
    """Query-level properties plus series-level ones (some WA tiles attach the
    dashboard filters to the series node)."""
    props: list[Any] = list(query.properties or [])
    series = query.series[0]
    if isinstance(series, EventsNode) and series.properties:
        props.extend(series.properties)
    return props


def build_inner_overview_query(query: TrendsQuery, properties: list[Any]) -> WebOverviewQuery:
    return WebOverviewQuery(
        dateRange=query.dateRange or DateRange(),
        interval=query.interval,
        properties=properties,
        filterTestAccounts=query.filterTestAccounts,
        compareFilter=query.compareFilter or CompareFilter(compare=False),
        # TrendsQuery carries no useWebAnalyticsPrecompute field (the core
        # trends schema stays untouched by design), so the per-query "Allow
        # precompute" opt-out cannot reach this path — the rollout flag baked
        # into the runner's cache key is the kill switch for trend tiles.
        useWebAnalyticsPrecompute=None,
    )


def can_use_web_trends_precompute(trends_runner: "WebTrendsQueryRunner", inner_runner: WebOverviewQueryRunner) -> bool:
    if not is_trends_precompute_enabled_for_team(trends_runner.team):
        return False
    if trends_precompute_metric(trends_runner.query) is None:
        return False
    return _can_use_lazy_precompute_shared(inner_runner, log_prefix=_FAMILY)


def _tz_offset_changes(date_range: Any) -> bool:
    start = date_range.date_from()
    end = date_range.date_to()
    if start is None or end is None:
        return False
    return start.utcoffset() != end.utcoffset()


def _read_series(
    *,
    team: Team,
    metric: WebTrendsMetric,
    interval: str,
    job_ids: list[str],
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> dict[datetime, float]:
    week_mode = WeekStartDay(team.week_start_day or 0).clickhouse_mode
    bucket_expr = _BUCKET_EXPRS[interval].format(week_mode=week_mode)
    sql = f"""
SELECT {bucket_expr} AS bucket, {_METRIC_EXPRS[metric]} AS value
FROM {DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
  AND time_window_start >= %(range_start)s AND time_window_start < %(range_end)s
GROUP BY bucket
"""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_trends_lazy_query")
    rows = sync_execute(
        sql,
        {
            "team_id": team.pk,
            "job_ids": tuple(job_ids),
            "tz": team.timezone,
            "range_start": range_start_utc,
            "range_end": range_end_utc,
        },
        settings=_READ_SETTINGS,
        team_id=team.pk,
    )
    result: dict[datetime, float] = {}
    for bucket, value in rows:
        # The driver returns tz-aware datetimes in the cast timezone; series
        # bucket datetimes from QueryDateRange are team-local too. Compare on
        # naive wall-clock to sidestep tzinfo-object identity mismatches.
        result[bucket.replace(tzinfo=None)] = float(value)
    return result


def _series_dict(
    runner: "WebTrendsQueryRunner",
    *,
    metric_values: dict[datetime, float],
    date_range: Any,
    is_previous: bool,
) -> dict[str, Any]:
    query = runner.query
    series = query.series[0]
    series_label = runner.series_event(series)

    buckets = date_range.all_values()
    interval_name = date_range.interval_name
    day_fmt = "%Y-%m-%d %H:%M:%S" if interval_name in ("hour", "minute") else "%Y-%m-%d"

    data = [metric_values.get(bucket.replace(tzinfo=None), 0.0) for bucket in buckets]

    series_object: dict[str, Any] = {
        "data": data,
        # Labels are formatted in the CURRENT range's context and action.days is
        # always the current range, even for the previous compare series — the
        # live runner does both (build_series_response passes
        # self.query_date_range regardless of series period).
        "labels": [format_label_date(item, runner.query_date_range, runner.team.week_start_day) for item in buckets],
        "days": [item.strftime(day_fmt) for item in buckets],
        "count": float(sum(data)),
        "label": "All events" if series_label is None else series_label,
        "filter": runner._query_to_filter(),
        "action": {
            "days": runner.query_date_range.all_values(),
            "id": series_label,
            "type": "events",
            "order": 0,
            "name": series_label or "All events",
            "custom_name": resolve_series_custom_name(series, series_label),
            "math": series.math,
            "math_property": series.math_property,
            "math_hogql": series.math_hogql,
            "math_group_type_index": series.math_group_type_index,
            "properties": {},
        },
        "order": 0,
    }
    if query.compareFilter is not None and query.compareFilter.compare:
        series_object["compare"] = True
        series_object["compare_label"] = "previous" if is_previous else "current"
    return series_object


def execute_lazy_precomputed_trends(runner: "WebTrendsQueryRunner") -> Optional[list[dict[str, Any]]]:
    """Serve the trends series from the shared web_overview preagg buckets.
    Returns the formatted results list, or None on any ineligibility/miss (the
    caller falls back to the live trends path)."""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team = runner.team
    overall_started = time.perf_counter()
    try:
        metric = trends_precompute_metric(runner.query)
        if metric is None:
            return None

        props = effective_properties(runner.query)
        inner_query = build_inner_overview_query(runner.query, props)
        inner_runner = WebOverviewQueryRunner(query=inner_query, team=team, modifiers=runner.modifiers)

        if not can_use_web_trends_precompute(runner, inner_runner):
            return None

        # Vanilla trends counts distinct_ids for these teams; the buckets store
        # person-id uniq states — the counts genuinely differ, so fall back.
        if runner.team.aggregate_users_by_distinct_id:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="distinct_id_aggregation").inc()
            return None

        interval = (runner.query.interval or IntervalType.DAY).value

        # A DST transition inside an hour-interval range makes two local
        # wall-clock hours collide on one bucket key (fall-back) or produces a
        # nonexistent one (spring-forward); the live path emits 25/23 points
        # there. Applies to the compare range too, which can cross a transition
        # the current range doesn't. Fall back rather than serve a silently
        # different axis.
        has_compare_for_dst = runner.query.compareFilter is not None and bool(runner.query.compareFilter.compare)
        if interval == "hour" and (
            _tz_offset_changes(runner.query_date_range)
            or (has_compare_for_dst and _tz_offset_changes(runner.query_previous_date_range))
        ):
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="dst_transition").inc()
            return None

        cur_buckets = runner.query_date_range.all_values()
        cur_to = runner.query_date_range.date_to()
        if not cur_buckets or cur_to is None:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None
        # The live trends path truncates date_from to the start of the interval
        # (a mid-month absolute date_from with month interval still counts the
        # whole first month) — read and precompute from the first aligned
        # bucket, not the raw date_from.
        cur_start_utc = cur_buckets[0].astimezone(UTC)
        cur_end_utc = cur_to.astimezone(UTC)

        time_range_start = floor_utc_day(cur_start_utc)
        time_range_end = ceil_utc_day(cur_end_utc)
        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None

        result = ensure_web_overview_precomputed(
            runner=inner_runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        if result.stale:
            # Family web_overview on purpose: one debounced overview re-run
            # rebuilds the buckets both tiles read.
            handle_stale_served(runner=inner_runner, family="web_overview")
        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            return None
        job_ids = [str(jid) for jid in result.job_ids]

        has_compare = runner.query.compareFilter is not None and bool(runner.query.compareFilter.compare)

        # Both ensures run before any read: if the previous period turns out
        # not ready the whole path falls back, and a current-period read done
        # first would be wasted work mis-tagged as a served lazy query.
        prev_job_ids: list[str] = []
        prev_start_utc = prev_end_utc = None
        prev_buckets: list = []
        if has_compare:
            prev_buckets = runner.query_previous_date_range.all_values()
            prev_to = runner.query_previous_date_range.date_to()
            if not prev_buckets or prev_to is None:
                WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="previous_range_missing").inc()
                return None
            prev_start_utc = prev_buckets[0].astimezone(UTC)
            prev_end_utc = prev_to.astimezone(UTC)
            prev_range_start = floor_utc_day(prev_start_utc)
            prev_range_end = ceil_utc_day(prev_end_utc)
            if prev_range_start < prev_range_end:
                prev_result = ensure_web_overview_precomputed(
                    runner=inner_runner,
                    time_range_start=prev_range_start,
                    time_range_end=prev_range_end,
                )
                if prev_result.stale:
                    handle_stale_served(runner=inner_runner, family="web_overview")
                if not prev_result.ready:
                    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="previous_not_ready").inc()
                    return None
                # The previous window is fully covered by its own ensure's jobs.
                # Unioning in the current period's jobs would double-count any
                # overlap day (overlapping compare_to windows) if a redundant
                # READY job for the same window exists under both ids.
                prev_job_ids = [str(jid) for jid in prev_result.job_ids]
            else:
                prev_job_ids = list(job_ids)

        results: list[dict[str, Any]] = []
        current_values = _read_series(
            team=team,
            metric=metric,
            interval=interval,
            job_ids=job_ids,
            range_start_utc=cur_start_utc,
            range_end_utc=cur_end_utc,
        )
        results.append(
            _series_dict(runner, metric_values=current_values, date_range=runner.query_date_range, is_previous=False)
        )

        if has_compare:
            assert prev_start_utc is not None and prev_end_utc is not None
            previous_values = _read_series(
                team=team,
                metric=metric,
                interval=interval,
                job_ids=prev_job_ids,
                range_start_utc=prev_start_utc,
                range_end_utc=prev_end_utc,
            )
            # Current first, previous second — mirrors the live runner's series
            # ordering, which the frontend relies on for compare pairing.
            results.append(
                _series_dict(
                    runner,
                    metric_values=previous_values,
                    date_range=runner.query_previous_date_range,
                    is_previous=True,
                )
            )

        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_trends_lazy_precompute_completed",
            team_id=team.pk,
            metric=metric.value,
            interval=interval,
            job_count=len(job_ids),
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return results
    except Exception as exc:
        WEB_TRENDS_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_trends_lazy_precompute_failed",
            team_id=team.pk,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
