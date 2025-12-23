import json

import dagster
import posthoganalytics
from dagster import Backoff, Jitter, RetryPolicy
from prometheus_client import Counter, Gauge

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import PostHogAnalayticsResource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting

from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

STALE_WEB_QUERIES_GAUGE = Gauge(
    "posthog_cache_warming_stale_web_query_gauge",
    "Number of stale web queries present",
    ["team_id"],
)
PRIORITY_WEB_QUERIES_COUNTER = Counter(
    "posthog_cache_warming_priority_web_queries",
    "Number of priority web queries warmed",
    ["team_id", "normalized_query_hash", "is_cached"],
)

cache_warming_retry_policy = RetryPolicy(
    max_retries=3,
    delay=2,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.FULL,
)


def teams_enabled_for_web_analytics_cache_warming() -> list[int]:
    enabled_team_ids = []

    for team_id, organization_id, uuid in Team.objects.values_list(
        "id",
        "organization_id",
        "uuid",
    ).iterator(chunk_size=1000):
        enabled = posthoganalytics.feature_enabled(
            "web-analytics-cache-warming",
            str(uuid),
            groups={
                "organization": str(organization_id),
                "project": str(team_id),
            },
            group_properties={
                "organization": {
                    "id": str(organization_id),
                },
                "project": {
                    "id": str(team_id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

        if enabled:
            enabled_team_ids.append(team_id)

    return enabled_team_ids


def queries_to_keep_fresh(
    context: dagster.OpExecutionContext, team_id: int, days: int = 7, minimum_query_count: int = 10
) -> list[dict]:
    context.log.info(
        f"Searching the last {days} for team {team_id}'s queries with at least {minimum_query_count} runs."
    )

    results = sync_execute(
        """
        SELECT
            team_id,
            query_json_raw,
            COUNT(*) AS query_count,
            normalizedQueryHash(query) as normalized_query_hash
        FROM (
            SELECT
                team_id,
                JSONExtractRaw(log_comment, 'query') AS query_json_raw,
                query
            FROM metrics_query_log_mv
            WHERE
                timestamp >= now() - INTERVAL %(days)s DAY
                AND team_id = %(team_id)s
                AND query_type IN (
                    'stats_table_query',
                    'web_goals_query',
                    'web_overview_preaggregated_query',
                    'web_overview_query',
                    'web_vitals_path_breakdown_query'
                )
        ) AS sub
        GROUP BY
            team_id,
            query_json_raw,
            normalized_query_hash
        HAVING query_count >= %(minimum_query_count)s
        ORDER BY
            query_count DESC
        """,
        {"team_id": team_id, "days": days, "minimum_query_count": minimum_query_count},
    )

    return [
        {
            "team_id": result[0],
            "query_json": json.loads(result[1]),
            "query_count": result[2],
            "normalized_query_hash": result[3],
        }
        for result in results
    ]


@dagster.op()
def get_teams_for_warming_op(
    context: dagster.OpExecutionContext, posthoganalytics: PostHogAnalayticsResource
) -> list[int]:
    team_ids = teams_enabled_for_web_analytics_cache_warming()

    context.log.info(f"Found {len(team_ids)} teams for cache warming")
    context.add_output_metadata({"team_count": len(team_ids), "team_ids": str(team_ids)})
    return team_ids


@dagster.op
def get_queries_for_teams_op(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
) -> list[dict]:
    days = get_instance_setting("WEB_ANALYTICS_WARMING_DAYS")
    minimum_query_count = get_instance_setting("WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT")

    all_queries = []
    for team_id in team_ids:
        queries = queries_to_keep_fresh(context, team_id, days=days, minimum_query_count=minimum_query_count)

        context.log.info(f"Loading {len(queries)} frequent web analytics queries for team {team_id}")

        STALE_WEB_QUERIES_GAUGE.labels(team_id=team_id).set(len(queries))
        all_queries.extend(queries)

    context.log.info(f"Found {len(all_queries)} total queries to warm")
    context.add_output_metadata({"query_count": len(all_queries), "team_count": len(team_ids)})
    return all_queries


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_op(context: dagster.OpExecutionContext, queries: list[dict]) -> None:
    warmed_count = 0
    cached_count = 0

    for query_info in queries:
        team_id = query_info["team_id"]
        query_json = query_info["query_json"]
        normalized_query_hash = query_info["normalized_query_hash"]

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found, skipping")
            continue

        tag_queries(team_id=team_id, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

        try:
            results = process_query_dict(
                team,
                query_json,
                limit_context=LimitContext.QUERY_ASYNC,
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            )

            is_cached = getattr(results, "is_cached", False)
            if is_cached:
                cached_count += 1

            PRIORITY_WEB_QUERIES_COUNTER.labels(
                team_id=team_id,
                normalized_query_hash=normalized_query_hash,
                is_cached=is_cached,
            ).inc()

            warmed_count += 1

        except Exception as e:
            context.log.exception(f"Error warming query for team {team_id}")
            capture_exception(e)

    context.log.info(f"Warmed {warmed_count} queries ({cached_count} were already cached)")
    context.add_output_metadata(
        {
            "warmed_count": warmed_count,
            "cached_count": cached_count,
            "skipped_count": len(queries) - warmed_count,
        }
    )


@dagster.job(
    description="Warms web analytics query cache for frequently-run queries",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/concurrency_key": "web_analytics_cache_warming",
    },
)
def web_analytics_cache_warming_job():
    team_ids = get_teams_for_warming_op()
    queries = get_queries_for_teams_op(team_ids)
    warm_queries_op(queries)


@dagster.schedule(
    cron_schedule="0 * * * *",
    job=web_analytics_cache_warming_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_cache_warming_schedule(context: dagster.ScheduleEvaluationContext):
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    return dagster.RunRequest()
