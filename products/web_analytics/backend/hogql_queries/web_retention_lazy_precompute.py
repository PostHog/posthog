import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.schema import (
    CompareFilter,
    DateRange,
    IntervalType,
    RetentionEntity,
    RetentionPeriod,
    RetentionQuery,
    WebOverviewQuery,
)

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_retention_preaggregated_sql import (
    DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.week_start_day import WeekStartDay

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    LAZY_TTL_SECONDS,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    floor_utc_day,
    test_account_filter_expr,
    user_filter_expr,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    handle_stale_served,
    web_ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_retention import WebRetentionQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_retention"

RETENTION_FLAG_KEY = "web-analytics-retention-precompute"

WEB_RETENTION_LAZY_FAILED = Counter(
    "web_retention_lazy_precompute_failed_total",
    "Web retention lazy precompute path failures, by error class",
    ["error_type"],
)

_READ_SETTINGS = {"max_execution_time": 30}


def is_retention_precompute_enabled_for_team(team: Team) -> bool:
    """Evaluate the retention rollout flag locally — fails closed on
    flag-service errors, mirroring the trends precompute ramp."""
    return bool(
        posthoganalytics.feature_enabled(
            RETENTION_FLAG_KEY,
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


def _entity_is_all_events(entity: Optional[RetentionEntity]) -> bool:
    if entity is None:
        return True
    if entity.type is not None and str(entity.type) not in ("events", "EntityType.EVENTS"):
        return False
    return entity.id is None


def retention_precompute_servable(query: RetentionQuery) -> bool:
    """Whether the query is the weekly first-occurrence any-event shape the
    web analytics retention tile sends — the only shape the buckets store.
    Everything else falls back to the live retention path."""

    def _enum_value(v: Any) -> Any:
        return getattr(v, "value", v)

    rf = query.retentionFilter
    if rf.period is not None and rf.period != RetentionPeriod.WEEK:
        return False
    if _enum_value(rf.retentionType) != "retention_first_time":
        return False
    if rf.retentionCustomBrackets:
        return False
    if rf.cumulative:
        return False
    if rf.meanRetentionCalculation is not None and _enum_value(rf.meanRetentionCalculation) != "none":
        return False
    # minimumOccurrences changes cohort membership; rolling windows change the
    # offset math — both are shapes the buckets don't store.
    if rf.minimumOccurrences is not None and rf.minimumOccurrences > 1:
        return False
    if rf.timeWindowMode is not None and _enum_value(rf.timeWindowMode) != "fixed":
        return False
    if rf.aggregationProperty is not None or rf.customAggregationTarget is not None:
        return False
    if rf.aggregationType is not None and _enum_value(rf.aggregationType) != "count":
        return False
    if not _entity_is_all_events(rf.targetEntity) or not _entity_is_all_events(rf.returningEntity):
        return False
    if query.breakdownFilter is not None:
        return False
    if query.samplingFactor is not None:
        return False
    if query.aggregation_group_type_index is not None:
        return False
    return True


# HogQL template for the precompute INSERT (see the vitals-paths family for the
# framework mechanics). One daily job window writes, per team-local activity
# day, the uniq state of active persons keyed by the team-local week of their
# first matching event over full history. The first-seen scan is restricted to
# the window's active persons but is otherwise unbounded below — the same
# full-history anchor the live first-time retention query computes.
INSERT_QUERY_TEMPLATE = """
SELECT
    active.activity_day AS time_window_start,
    firsts.cohort_week_start AS cohort_week_start,
    uniqState(active.person_id) AS retained_users_state
FROM (
    SELECT
        events.person_id AS person_id,
        toStartOfDay(events.timestamp, {team_tz}) AS activity_day
    FROM events
    WHERE and(
        events.timestamp >= {time_window_min},
        events.timestamp < {time_window_max},
        {user_filter},
        {test_account_filter}
    )
    GROUP BY person_id, activity_day
) AS active
INNER JOIN (
    SELECT
        events.person_id AS person_id,
        toDateTime(toStartOfWeek(toTimeZone(min(events.timestamp), {team_tz}), {week_mode}), {team_tz}) AS cohort_week_start
    FROM events
    WHERE and(
        events.person_id IN (
            SELECT DISTINCT events.person_id
            FROM events
            WHERE and(
                events.timestamp >= {time_window_min},
                events.timestamp < {time_window_max},
                {user_filter},
                {test_account_filter}
            )
        ),
        {user_filter},
        {test_account_filter}
    )
    GROUP BY person_id
) AS firsts ON active.person_id = firsts.person_id
GROUP BY time_window_start, cohort_week_start
"""


def _build_inner_overview_query(query: RetentionQuery) -> WebOverviewQuery:
    """Carrier for the shared eligibility gate and ensure plumbing: the same
    filters and range in web-analytics-runner shape. The retention family has
    its own insert template and job hash; only the gate context is borrowed."""
    return WebOverviewQuery(
        dateRange=query.dateRange or DateRange(),
        interval=IntervalType.DAY,
        properties=list(query.properties or []),
        filterTestAccounts=query.filterTestAccounts,
        compareFilter=CompareFilter(compare=False),
        useWebAnalyticsPrecompute=None,
    )


def ensure_web_retention_precomputed(
    runner: "WebRetentionQueryRunner",
    inner_runner: WebOverviewQueryRunner,
    week_mode: int,
    time_range_start: datetime,
    time_range_end: datetime,
):
    placeholders: dict[str, ast.Expr] = {
        "user_filter": user_filter_expr(inner_runner),
        "test_account_filter": test_account_filter_expr(inner_runner),
        # Team timezone and week mode go into the cache key — changing either
        # naturally invalidates existing jobs.
        "team_tz": ast.Constant(value=inner_runner.team.timezone),
        "week_mode": ast.Constant(value=week_mode),
    }
    # The RETENTION runner goes in as the ensure's runner: a check-only miss
    # enqueues `runner.query` for background revalidation, and replaying the
    # RetentionQuery (not the inner overview carrier) is what rebuilds THIS
    # family — the warming trigger routes it back through this module with
    # inline inserts.
    return web_ensure_precomputed(
        runner=runner,
        family=_FAMILY,
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_RETENTION_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_retention_lazy_insert",
        spill_to_disk=True,  # the first-seen arm groups by person over full history
    )


def _read_matrix(
    *,
    team: Team,
    week_mode: int,
    job_ids: list[str],
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> dict[tuple[datetime, datetime], int]:
    """(cohort_week_start, activity_week_start) → retained person count, both
    naive team-local week starts."""
    sql = f"""
SELECT
    cohort_week_start,
    toDateTime(toStartOfWeek(toTimeZone(time_window_start, %(tz)s), {week_mode}), %(tz)s) AS activity_week,
    uniqMerge(retained_users_state) AS cnt
FROM {DISTRIBUTED_WEB_RETENTION_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
  AND time_window_start >= %(range_start)s AND time_window_start < %(range_end)s
GROUP BY cohort_week_start, activity_week
"""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_retention_lazy_query")
    rows = sync_execute(
        sql,
        {
            "team_id": team.pk,
            "tz": team.timezone,
            "job_ids": tuple(job_ids),
            "range_start": range_start_utc,
            "range_end": range_end_utc,
        },
        settings=_READ_SETTINGS,
        team_id=team.pk,
    )
    result: dict[tuple[datetime, datetime], int] = {}
    for cohort_week, activity_week, count in rows:
        key = (cohort_week.replace(tzinfo=None), activity_week.replace(tzinfo=None))
        # Rows for the same (cohort, activity) pair can arrive from redundant
        # READY jobs covering the same days; keep the max rather than summing,
        # which would double-count persons present in both jobs' states.
        result[key] = max(result.get(key, 0), int(count))
    return result


def execute_lazy_precomputed_retention(runner: "WebRetentionQueryRunner") -> Optional[list[dict[str, Any]]]:
    """Serve the weekly first-occurrence retention matrix from the retention
    preagg buckets. Returns results in the live runner's format, or None on
    any ineligibility/miss (caller falls back to the live retention path)."""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team = runner.team
    overall_started = time.perf_counter()
    try:
        if not retention_precompute_servable(runner.query):
            return None
        if not is_retention_precompute_enabled_for_team(team):
            return None

        inner_query = _build_inner_overview_query(runner.query)
        inner_runner = WebOverviewQueryRunner(query=inner_query, team=team, modifiers=runner.modifiers)
        if not _can_use_lazy_precompute_shared(inner_runner, log_prefix=_FAMILY):
            return None

        # The live path counts persons; the buckets store person-id uniq
        # states, which cannot represent distinct-id aggregation.
        if team.aggregate_users_by_distinct_id:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="distinct_id_aggregation").inc()
            return None

        date_range = runner.query_date_range
        date_from = date_range.date_from()
        date_to = date_range.date_to()
        if date_from is None or date_to is None or date_from >= date_to:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None

        week_mode = int(WeekStartDay(team.week_start_day or 0).clickhouse_mode)
        cur_start_utc = date_from.astimezone(UTC)
        cur_end_utc = date_to.astimezone(UTC)
        time_range_start = floor_utc_day(cur_start_utc)
        time_range_end = ceil_utc_day(cur_end_utc)

        result = ensure_web_retention_precomputed(
            runner=runner,
            inner_runner=inner_runner,
            week_mode=week_mode,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        if result.stale:
            handle_stale_served(runner=runner, family=_FAMILY)
        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            return None

        matrix = _read_matrix(
            team=team,
            week_mode=week_mode,
            job_ids=[str(jid) for jid in result.job_ids],
            range_start_utc=cur_start_utc,
            range_end_utc=cur_end_utc,
        )

        intervals_between = date_range.intervals_between
        lookahead = runner.lookahead_period_count
        labels = runner.get_bracket_labels()
        cohort_weeks = [
            (date_from + date_range.determine_time_delta(i, "Week")).replace(tzinfo=None)
            for i in range(intervals_between)
        ]
        week_index = {week: i for i, week in enumerate(cohort_weeks)}

        counts: dict[tuple[int, int], int] = {}
        for (cohort_week, activity_week), count in matrix.items():
            start_interval = week_index.get(cohort_week)
            if start_interval is None:
                continue  # First occurrence before the queried range: not a range cohort.
            offset_index = week_index.get(activity_week)
            offset = (offset_index - start_interval) if offset_index is not None else None
            if offset is None or offset < 0 or offset >= lookahead:
                continue
            counts[(start_interval, offset)] = count

        results = [
            {
                "values": [
                    {"count": float(counts.get((start_interval, return_interval), 0)), "label": labels[return_interval]}
                    for return_interval in range(lookahead)
                ],
                "label": f"Week {start_interval}",
                "date": runner.get_date(start_interval),
                "breakdown_value": None,
            }
            for start_interval in range(intervals_between)
        ]
        logger.info(
            "web_retention_lazy_precompute_served",
            team_id=team.pk,
            job_count=len(result.job_ids),
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return results
    except Exception as exc:
        WEB_RETENTION_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_retention_lazy_precompute_failed",
            team_id=team.pk,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
