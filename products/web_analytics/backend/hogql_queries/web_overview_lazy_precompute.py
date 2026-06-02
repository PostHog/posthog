import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    check_common_eligible,
    events_session_id_expr,
    floor_utc_day,
    test_account_filter_expr,
    user_filter_expr,
)

_FAMILY = "web_overview"

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)


WEB_OVERVIEW_LAZY_FAILED = Counter(
    "web_overview_lazy_precompute_failed_total",
    "Lazy precompute path failures, by error class",
    ["error_type"],
)


def can_use_lazy_precompute(runner: "WebOverviewQueryRunner") -> bool:
    """Return True iff the lazy precompute path is eligible for this web
    overview query. Web overview has no checks beyond the shared gate."""
    return _can_use_lazy_precompute_shared(runner, log_prefix="web_overview")


# Re-exported so callers (and tests) can still reach the eligibility checker
# through this module.
_check_lazy_precompute_eligible = check_common_eligible


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min`/`time_window_max`),
# parses the result, and INSERTs into `web_overview_preaggregated`. The framework
# automatically prepends `team_id`, `job_id` and appends `expires_at` to the SELECT.
#
# The forward pad on the event-scan window (`SESSION_FORWARD_PAD_MINUTES`) lets a
# session that starts near the trailing edge of a daily UTC job still aggregate
# its events that spill past midnight — the HAVING clause attributes the session
# to its start hour, but the events scan needs the trailing events to compute
# correct `$session_duration` / `$pageview_count` / `$is_bounce`.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    uniqState(session_person_id) AS uniq_users_state,
    uniqState(session_id) AS uniq_sessions_state,
    sumState(assumeNotNull(toInt(filtered_pageview_count))) AS sum_pageviews_state,
    avgState(assumeNotNull(toFloat(session_duration))) AS avg_duration_state,
    avgState(assumeNotNull(toInt(is_bounce))) AS avg_bounce_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        any(session.$session_duration) AS session_duration,
        countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count,
        any(session.$is_bounce) AS is_bounce
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        {event_type_filter},
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


def ensure_web_overview_precomputed(
    runner: "WebOverviewQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": events_session_id_expr(runner),
        "event_type_filter": runner.event_type_expr,
        "user_filter": user_filter_expr(runner),
        "test_account_filter": test_account_filter_expr(runner),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_overview_lazy_insert",
    )


_READ_SQL = f"""
SELECT
    uniqMergeIf(uniq_users_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS unique_users,
    uniqMergeIf(uniq_users_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_unique_users,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS views,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_views,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS sessions,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_sessions,
    avgMergeIf(avg_duration_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS avg_duration,
    avgMergeIf(avg_duration_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_avg_duration,
    avgMergeIf(avg_bounce_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS bounce_rate,
    avgMergeIf(avg_bounce_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_bounce_rate
FROM {DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
"""


_READ_SETTINGS = {
    # Approach E from `products/analytics_platform/backend/lazy_computation/CONSISTENCY.md`:
    # both INSERT (via `_get_insert_settings`) and SELECT use `in_order` so they
    # deterministically prefer the same replica. Combined with the global
    # `distributed_foreground_insert=1`, the SELECT sees data the INSERT just wrote.
    #
    # `select_sequential_consistency=1` was tried here and is documented broken in
    # CONSISTENCY.md when combined with `insert_quorum_parallel=1` (the default).
    "load_balancing": "in_order",
    # Shard pruning: sharding key is `sipHash64(job_id)`; `job_id IN (...)` matches
    # exactly the shards we wrote to.
    "optimize_skip_unused_shards": 1,
}


def execute_read_query(
    *,
    team_id: int,
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> list:
    """Run the precompute-read SQL via `sync_execute`.

    Bypasses HogQL so we can set `select_sequential_consistency=1` on the SELECT —
    HogQLGlobalSettings forbids extra keys, and the read query shape is stable
    enough that string parameterization is appropriate.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the *MergeIf
    # aggregates return 0 / NaN for the "previous" columns without changing shape.
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_overview_lazy_query")
    return sync_execute(
        _READ_SQL,
        {
            "team_id": team_id,
            "job_ids": tuple(str(jid) for jid in job_ids),
            "cur_start": current_start_utc,
            "cur_end": current_end_utc,
            "prev_start": prev_start,
            "prev_end": prev_end,
        },
        settings=_READ_SETTINGS,
        team_id=team_id,
    )


def _empty_response_row() -> list:
    # 5 metric pairs (current, previous) — previous slots are None and discarded
    # downstream when compareFilter.compare is False. When compare is True, the
    # response gets fully populated from the read query, so this default is only
    # used for genuinely empty windows.
    return [0, None, 0, None, 0, None, 0, None, 0, None]


def execute_lazy_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Orchestrate the lazy precompute + read. Returns the response row, or None
    on any failure (caller falls through to the v2/raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the INSERT
    # `sync_execute` inside `ensure_web_overview_precomputed` doesn't trip
    # DEBUG-mode `UntaggedQueryError`. The read query overrides `query_type`
    # later via `tag_queries(...)` inside `execute_read_query`.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local timezone interpretation when
        # escaping the datetime constants in the filter.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request. Without this, the
        # 08:00 UTC start of "today PT" would fall outside the framework's UTC
        # day window and have no precomputed buckets to read.
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            logger.info(
                "web_overview_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_overview_lazy_precompute_started",
            team_id=team_id,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_web_overview_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)

        logger.info(
            "web_overview_lazy_precompute_ensure_done",
            team_id=team_id,
            job_count=len(result.job_ids),
            ensure_duration_ms=ensure_duration_ms,
        )

        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            return None

        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            logger.info(
                "web_overview_lazy_precompute_current_not_ready",
                team_id=team_id,
                job_count=len(result.job_ids),
            )
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            if prev_from is not None and prev_to is not None:
                previous_start_utc = prev_from.astimezone(UTC)
                previous_end_utc = prev_to.astimezone(UTC)

                # Precompute the previous period too — without this, the read
                # query's `WHERE job_id IN %(job_ids)s` filter has no rows
                # covering the previous window and every `*MergeIf(..., prev_*)`
                # returns 0/NaN, silently breaking compare-period metrics.
                prev_range_start = floor_utc_day(previous_start_utc)
                prev_range_end = ceil_utc_day(previous_end_utc)
                if prev_range_start < prev_range_end:
                    prev_ensure_started = time.perf_counter()
                    prev_result = ensure_web_overview_precomputed(
                        runner=runner,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                    )
                    ensure_duration_ms += int((time.perf_counter() - prev_ensure_started) * 1000)

                    if not prev_result.ready:
                        WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="previous_not_ready").inc()
                        logger.info(
                            "web_overview_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None

                    job_ids.extend(str(jid) for jid in prev_result.job_ids)

        read_started = time.perf_counter()
        rows = execute_read_query(
            team_id=team_id,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)
        total_duration_ms = int((time.perf_counter() - overall_started) * 1000)

        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_overview_lazy_precompute_completed",
            team_id=team_id,
            job_count=len(result.job_ids),
            rows_returned=len(rows) if rows else 0,
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        if not rows:
            return _empty_response_row()
        return list(rows[0])
    except Exception as exc:
        WEB_OVERVIEW_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_overview_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
