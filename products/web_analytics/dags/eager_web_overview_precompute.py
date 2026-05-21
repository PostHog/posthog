"""Eagerly pre-warm the web_overview_preaggregated table.

Runs on a 15-minute schedule and fans out over enabled teams × standard date
ranges so that read queries find READY jobs and bypass inline INSERTs entirely.
"""

from datetime import UTC, datetime, timedelta

import dagster
from dagster import Backoff, Jitter, RetryPolicy
from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.web_analytics.web_overview_lazy_precompute import (
    INSERT_QUERY_TEMPLATE,
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    _floor_utc_day,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

EAGER_PRECOMPUTE_JOBS_TRIGGERED = Counter(
    "web_overview_eager_precompute_jobs_triggered_total",
    "INSERT jobs triggered by the eager precompute Dagster job",
    ["team_id"],
)

EAGER_PRECOMPUTE_ERRORS = Counter(
    "web_overview_eager_precompute_errors_total",
    "Errors during eager precompute fan-out",
    ["team_id", "error_type"],
)

eager_precompute_retry_policy = RetryPolicy(
    max_retries=2,
    delay=10,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.FULL,
)


def _get_eager_precompute_team_ids() -> list[int]:
    value = get_instance_setting("WEB_ANALYTICS_EAGER_PRECOMPUTE_TEAM_IDS")
    return value if isinstance(value, list) else []


def _standard_date_ranges(now_utc: datetime) -> list[tuple[datetime, datetime]]:
    """Return the standard set of (start, end) UTC ranges to pre-warm.

    Mirrors the date ranges most common in the web analytics dashboard:
    today, yesterday, last 7 / 14 / 30 days.
    """
    today_start = _floor_utc_day(now_utc)
    today_end = today_start + timedelta(days=1)

    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start

    last_7d_start = _floor_utc_day(now_utc - timedelta(days=7))
    last_14d_start = _floor_utc_day(now_utc - timedelta(days=14))
    last_30d_start = _floor_utc_day(now_utc - timedelta(days=30))

    return [
        (today_start, today_end),
        (yesterday_start, yesterday_end),
        (last_7d_start, today_end),
        (last_14d_start, today_end),
        (last_30d_start, today_end),
    ]


def _top_host_values(team_id: int, days: int = 7, limit: int = 5) -> list[str]:
    """Mine metrics_query_log_mv for the most-queried $host values for this team."""
    try:
        results = sync_execute(
            """
            SELECT
                JSONExtractString(JSONExtractRaw(log_comment, 'query'), 'properties[0].value') AS host_value,
                COUNT(*) AS query_count
            FROM metrics_query_log_mv
            WHERE
                timestamp >= now() - INTERVAL %(days)s DAY
                AND team_id = %(team_id)s
                AND query_type IN ('web_overview_query', 'web_overview_preaggregated_query')
                AND exception_code = 0
                AND host_value != ''
            GROUP BY host_value
            ORDER BY query_count DESC
            LIMIT %(limit)s
            """,
            {"team_id": team_id, "days": days, "limit": limit},
        )
        return [row[0] for row in results if row[0]]
    except Exception:
        return []


def _build_dag_placeholders(
    team: Team,
    host_filter: str | None = None,
    test_account_filter: ast.Expr | None = None,
) -> dict[str, ast.Expr]:
    """Build placeholder dict matching the AST produced by web_overview_lazy_precompute._build_placeholders.

    The AST repr must be identical to what the query-path produces so the cache
    key hash matches and the DAG's pre-warmed jobs are found by read queries.
    """
    event_type_filter: ast.Expr = ast.Or(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$pageview"),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$screen"),
            ),
        ]
    )

    user_filter: ast.Expr
    if host_filter:
        user_filter = ast.Call(
            name="equals",
            args=[
                ast.Field(chain=["events", "properties", "$host"]),
                ast.Constant(value=host_filter),
            ],
        )
    else:
        user_filter = ast.Constant(value=True)

    # events_session_id must match WebAnalyticsQueryRunner.events_session_property
    # when sessionsV2JoinMode != "uuid" (uuid mode is gated out by can_use_eager_precompute).
    events_session_id = parse_expr("events.$session_id")

    return {
        "events_session_id": events_session_id,
        "event_type_filter": event_type_filter,
        "user_filter": user_filter,
        "test_account_filter": test_account_filter if test_account_filter is not None else ast.Constant(value=True),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }


def _test_account_filter_variants(team: Team) -> list[ast.Expr]:
    """Return the test_account_filter AST variants to pre-warm for this team.

    Always includes the unfiltered variant (True). If the team has test account
    filters configured, also includes the filtered variant so users with
    filterTestAccounts=True get cache hits too.
    """
    from posthog.hogql.property import property_to_expr

    variants: list[ast.Expr] = [ast.Constant(value=True)]

    if isinstance(team.test_account_filters, list) and team.test_account_filters:
        try:
            filtered_expr = property_to_expr(team.test_account_filters, team=team)
            variants.append(filtered_expr)
        except Exception:
            pass

    return variants


@dagster.op(retry_policy=eager_precompute_retry_policy)
def get_eager_precompute_teams_op(context: dagster.OpExecutionContext) -> list[int]:
    team_ids = _get_eager_precompute_team_ids()
    context.log.info(f"Eager precompute: {len(team_ids)} teams enabled")
    context.add_output_metadata({"team_count": len(team_ids), "team_ids": str(team_ids)})
    return team_ids


@dagster.op(retry_policy=eager_precompute_retry_policy)
def warm_eager_precompute_op(context: dagster.OpExecutionContext, team_ids: list[int]) -> None:
    now_utc = datetime.now(UTC)
    date_ranges = _standard_date_ranges(now_utc)

    for team_id in team_ids:
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found, skipping")
            continue

        host_variants: list[str | None] = [None]
        host_variants.extend(_top_host_values(team_id))
        ta_filter_variants = _test_account_filter_variants(team)

        context.log.info(
            f"Team {team_id}: warming {len(date_ranges)} date ranges × "
            f"{len(host_variants)} host variants × "
            f"{len(ta_filter_variants)} test-account-filter variants"
        )

        for date_range_start, date_range_end in date_ranges:
            for host_filter in host_variants:
                for ta_filter in ta_filter_variants:
                    try:
                        placeholders = _build_dag_placeholders(team, host_filter, ta_filter)
                        result = ensure_precomputed(
                            team=team,
                            insert_query=INSERT_QUERY_TEMPLATE,
                            time_range_start=date_range_start,
                            time_range_end=date_range_end,
                            ttl_seconds=LAZY_TTL_SECONDS,
                            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
                            placeholders=placeholders,
                            query_type="web_overview_eager_precompute",
                        )

                        if result.ready:
                            EAGER_PRECOMPUTE_JOBS_TRIGGERED.labels(team_id=str(team_id)).inc(len(result.job_ids))
                        else:
                            context.log.warning(
                                f"Team {team_id}: precompute not ready for range "
                                f"{date_range_start} - {date_range_end}, "
                                f"host={host_filter!r}"
                            )

                    except Exception as e:
                        EAGER_PRECOMPUTE_ERRORS.labels(team_id=str(team_id), error_type=type(e).__name__).inc()
                        context.log.exception(
                            f"Error pre-warming team {team_id} range "
                            f"{date_range_start} - {date_range_end}, host={host_filter!r}"
                        )
                        capture_exception(e)

    context.log.info("Eager precompute fan-out complete")


@dagster.job(
    description="Pre-warms web_overview_preaggregated table for eager-enabled teams",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_eager_precompute": "web_analytics_eager_precompute",
    },
)
def web_analytics_eager_precompute_job() -> None:
    team_ids = get_eager_precompute_teams_op()
    warm_eager_precompute_op(team_ids)


@dagster.schedule(
    cron_schedule="*/15 * * * *",
    job=web_analytics_eager_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_eager_precompute_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> dagster.RunRequest | dagster.SkipReason:
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    return dagster.RunRequest()
