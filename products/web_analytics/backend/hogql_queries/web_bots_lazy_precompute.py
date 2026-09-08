import json
import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import structlog

from posthog.schema import HogQLQueryResponse, WebBotsBreakdown

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.dataclasses import frozen

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,
    LazyPrecomputeIneligible,
    ceil_utc_day,
    check_common_eligibility,
    floor_utc_day,
    handle_stale_served,
    log_eligibility_outcome,
    web_ensure_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_bots import WebBotsTableQueryRunner

logger = structlog.get_logger(__name__)
FAMILY = "web_bots"

INSERT_QUERY = """
SELECT
    toStartOfHour(timestamp) AS time_window_start,
    `$virt_bot_name` AS bot_name,
    `$virt_traffic_category` AS category,
    properties.$host AS host,
    properties.$pathname AS pathname,
    count() AS requests,
    max(timestamp) AS last_seen
FROM events AS bot_events
WHERE and(
    event IN ('$pageview', '$screen', '$http_log'),
    `$virt_is_bot` = true,
    `$virt_bot_name` != '',
    timestamp >= {time_window_min},
    timestamp < {time_window_max},
    {all_properties},
    notEmpty({classification_key})
)
GROUP BY time_window_start, bot_name, category, host, pathname
"""

REQUESTS_QUERY = """
SELECT bot_name, category, pathname, requests, last_seen
FROM posthog.web_bots_preaggregated
WHERE job_id IN {job_ids}
    AND time_window_start >= {full_start}
    AND time_window_start < {full_end}
UNION ALL
SELECT
    `$virt_bot_name` AS bot_name,
    `$virt_traffic_category` AS category,
    properties.$pathname AS pathname,
    count() AS requests,
    max(timestamp) AS last_seen
FROM events
WHERE and(
    event IN ('$pageview', '$screen', '$http_log'),
    `$virt_is_bot` = true,
    `$virt_bot_name` != '',
    {inside_timestamp_period},
    (timestamp < {full_start} OR timestamp >= {full_end}),
    {all_properties}
)
GROUP BY bot_name, category, pathname
"""

CRAWLERS_QUERY = """
SELECT bot_name AS "Crawler", category AS "Category", sum(requests) AS "Requests", max(last_seen) AS "Last seen"
FROM ({requests})
GROUP BY "Crawler", "Category"
ORDER BY "Requests" DESC
"""

PATHS_QUERY = """
SELECT pathname AS "Path", uniqExact(bot_name) AS "Crawlers", sum(requests) AS "Requests", max(last_seen) AS "Last seen"
FROM ({requests})
WHERE pathname IS NOT NULL
GROUP BY "Path"
ORDER BY "Requests" DESC
"""


@frozen
class BotsPrecomputeCoverage:
    """Which stored hours a read may trust, and whether they came from the stale grace.

    `covered_until` is the exclusive end of the hour span the jobs hold complete rows for.
    Everything outside `[covered_from, covered_until)` has to be read from events, so a read
    never zero-fills an hour the insert has not reached yet.
    """

    job_ids: list[UUID]
    covered_until: datetime
    stale: bool


def floor_utc_hour(dt_utc: datetime) -> datetime:
    return dt_utc.replace(minute=0, second=0, microsecond=0)


def can_use_lazy_precompute(runner: "WebBotsTableQueryRunner") -> bool:
    try:
        check_common_eligibility(
            team=runner.team,
            use_web_analytics_precompute=runner.query.useWebAnalyticsPrecompute,
            conversion_goal=runner.query.conversionGoal,
            sampling=runner.query.sampling,
            modifiers=runner.query.modifiers,
            properties=runner.query.properties + runner._test_account_filters,
            resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
        )
        if runner.query_compare_to_date_range is not None:
            raise LazyPrecomputeIneligible("Comparison ranges use the live query.")
    except LazyPrecomputeIneligible as error:
        log_eligibility_outcome(log_prefix="web_bots_lazy_precompute", team_id=runner.team.pk, error=error)
        return False
    log_eligibility_outcome(log_prefix="web_bots_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def classification_key(runner: "WebBotsTableQueryRunner") -> str:
    """Hash of the compiled bot classification, carried into the insert so job identity tracks it.

    The printed SQL and its bound values hold every input that decides whether a request is a
    bot and which crawler and category it is: the built-in definitions, the IP ranges, and the
    project's custom bot rules. A change to any of them mints new jobs, so stored rows can never
    outlive the classification that produced them. Hashing the whole modifier payload instead
    would also split jobs on modifiers that never reach this expression.
    """
    context = HogQLContext(
        team_id=runner.team.pk, team=runner.team, modifiers=runner.modifiers, enable_select_queries=True
    )
    query = parse_select("SELECT `$virt_bot_name`, `$virt_traffic_category`, `$virt_is_bot` FROM events")
    sql, _ = prepare_and_print_ast(query, context=context, dialect="clickhouse")
    encoded = json.dumps([sql, context.values], sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def ensure_web_bots_precomputed(
    *, runner: "WebBotsTableQueryRunner", full_start: datetime, full_end: datetime
) -> Optional[BotsPrecomputeCoverage]:
    """Build (on background triggers) or check the bot buckets covering `[full_start, full_end)`.

    Every bot tile routes its ensure through here with the same insert query and placeholders,
    so the two tables and the four trend breakdowns share one set of jobs. Returns None when
    no covering jobs are ready, or when they cover no whole hour — the caller then serves live.
    """
    result = web_ensure_precomputed(
        runner=runner,
        family=FAMILY,
        team=runner.team,
        insert_query=INSERT_QUERY,
        time_range_start=floor_utc_day(full_start),
        time_range_end=ceil_utc_day(full_end),
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_BOTS_PREAGGREGATED,
        placeholders={
            "all_properties": runner._all_properties(),
            "classification_key": ast.Constant(value=classification_key(runner)),
        },
        modifiers=runner.modifiers,
        query_type="web_bots_lazy_insert",
    )
    if not result.ready or not result.job_ids:
        return None

    covered_until = _covered_until(result.job_ids, full_end)
    if covered_until is None or covered_until <= full_start:
        return None
    return BotsPrecomputeCoverage(job_ids=result.job_ids, covered_until=covered_until, stale=result.stale)


def _covered_until(job_ids: list[UUID], full_end: datetime) -> Optional[datetime]:
    """Exclusive hour boundary the jobs hold complete rows up to.

    A job for a window that has not elapsed yet — today's — runs before its window ends, so it
    holds no rows for the hours after it ran. Reading those hours from the table reports them as
    zero, which on a chart draws as a flat recent tail. The insert scans `timestamp < window end`,
    so a job's rows are complete only up to its own `computed_at`, and the hour `computed_at`
    falls inside is itself partial. Take the earliest such truncation across the covering jobs
    and floor it to the hour.
    """
    boundary = full_end
    for time_range_end, computed_at in PreaggregationJob.objects.filter(id__in=job_ids).values_list(
        "time_range_end", "computed_at"
    ):
        if computed_at is None:
            return None
        if computed_at < time_range_end:
            boundary = min(boundary, computed_at)
    return floor_utc_hour(boundary)


def execute_lazy_precomputed_query(runner: "WebBotsTableQueryRunner") -> HogQLQueryResponse | None:
    try:
        if not can_use_lazy_precompute(runner):
            return None

        date_from = runner.query_date_range.date_from().astimezone(UTC)
        date_to = runner.query_date_range.date_to().astimezone(UTC)
        full_start = floor_utc_hour(date_from)
        if full_start < date_from:
            full_start += timedelta(hours=1)
        full_end = floor_utc_hour(date_to)
        if full_start >= full_end:
            return None

        coverage = ensure_web_bots_precomputed(runner=runner, full_start=full_start, full_end=full_end)
        if coverage is None:
            return None
        if coverage.stale:
            handle_stale_served(runner=runner, family=FAMILY)

        query = build_read_query(runner, coverage.job_ids, full_start, coverage.covered_until)
        response = runner.paginator.execute_hogql_query(
            query=query,
            query_type="web_bots_lazy_query",
            team=runner.team,
            user=runner.user,
            timings=runner.timings,
            modifiers=runner.modifiers,
            settings=HogQLGlobalSettings(load_balancing="in_order", optimize_skip_unused_shards=True),
        )
        logger.info("web_bots_lazy_precompute_served", team_id=runner.team.pk, stale=coverage.stale)
        return response
    except Exception:
        logger.exception("web_bots_lazy_precompute_failed", team_id=runner.team.pk)
        return None


def build_read_query(
    runner: "WebBotsTableQueryRunner", job_ids: list[UUID], full_start: datetime, full_end: datetime
) -> ast.SelectQuery:
    requests = parse_select(
        REQUESTS_QUERY,
        placeholders={
            "job_ids": ast.Tuple(exprs=[ast.Constant(value=str(job_id)) for job_id in job_ids]),
            "full_start": ast.Constant(value=full_start),
            "full_end": ast.Constant(value=full_end),
            "inside_timestamp_period": runner._periods_expression("timestamp"),
            "all_properties": runner._all_properties(),
        },
    )
    query = parse_select(
        PATHS_QUERY if runner.query.breakdownBy == WebBotsBreakdown.PATH else CRAWLERS_QUERY,
        placeholders={"requests": requests},
    )
    assert isinstance(query, ast.SelectQuery)
    return query
