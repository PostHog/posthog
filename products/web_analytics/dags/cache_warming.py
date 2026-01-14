import json

from django.utils.dateparse import parse_datetime

import dagster
from dagster import Backoff, Jitter, RetryPolicy
from prometheus_client import Counter, Gauge

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import ClickhouseClusterResource, PostHogAnalyticsResource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_runner import get_query_runner
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


def increment_counter(team_id: int, normalized_query_hash: str, is_cached: bool):
    PRIORITY_WEB_QUERIES_COUNTER.labels(
        team_id=team_id,
        normalized_query_hash=normalized_query_hash,
        is_cached=is_cached,
    ).inc()


def get_teams_enabled_for_web_analytics_cache_warming() -> list[int]:
    return get_instance_setting("WEB_ANALYTICS_WARMING_TEAMS_TO_WARM")


def queries_to_keep_fresh(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseClusterResource,
    team_id: int,
    days: int = 7,
    minimum_query_count: int = 10,
) -> list[dict]:
    context.log.info(
        f"Searching the last {days} days for team {team_id}'s queries with at least {minimum_query_count} runs."
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
                query,
                exception_code
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
                AND query_json_raw != ''
                AND exception_code = 0
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
    context: dagster.OpExecutionContext, posthoganalytics: PostHogAnalyticsResource
) -> list[int]:
    team_ids = get_teams_enabled_for_web_analytics_cache_warming()

    context.log.info(f"Found {len(team_ids)} teams for cache warming")
    context.add_output_metadata({"team_count": len(team_ids), "team_ids": str(team_ids)})
    return team_ids


@dagster.op
def get_queries_for_teams_op(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseClusterResource,
    team_ids: list[int],
) -> dict:
    days = get_instance_setting("WEB_ANALYTICS_WARMING_DAYS")
    minimum_query_count = get_instance_setting("WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT")

    all_queries = {}
    query_count = 0
    for team_id in team_ids:
        queries = queries_to_keep_fresh(context, cluster, team_id, days=days, minimum_query_count=minimum_query_count)

        context.log.info(f"Loading {len(queries)} frequent web analytics queries for team {team_id}")

        STALE_WEB_QUERIES_GAUGE.labels(team_id=team_id).set(len(queries))
        all_queries[team_id] = queries
        query_count += len(queries)

    context.log.info(f"Found {query_count} total queries to warm")
    context.add_output_metadata({"query_count": query_count, "team_count": len(team_ids)})
    return all_queries


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_op(context: dagster.OpExecutionContext, queries: dict) -> None:
    queries_warmed = 0
    queries_skipped = 0

    for team_id, query_infos in queries.items():
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            context.log.warning(f"Team {team_id} not found, skipping")
            continue

        for query_info in query_infos:
            team_id = query_info["team_id"]
            query_json = query_info["query_json"]
            normalized_query_hash = query_info["normalized_query_hash"]

            runner = get_query_runner(
                query=query_json,
                team=team,
                limit_context=LimitContext.QUERY_ASYNC,
            )

            cache_manager = DjangoCacheQueryCacheManager(team_id=team.pk, cache_key=runner.get_cache_key())

            try:
                cached_data = cache_manager.get_cache_data()

                if cached_data is not None:
                    last_refresh = parse_datetime(cached_data["last_refresh"])
                    is_stale = runner._is_stale(last_refresh)

                    if not is_stale:
                        context.log.info(f"Query hash {normalized_query_hash} already cached, skipping warmup.")
                        increment_counter(team_id, normalized_query_hash, is_cached=True)
                        queries_skipped += 1
                        continue

                tag_queries(team_id=team_id, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

                # TODO: We shouldn't try to run a query if it failed last run
                runner.run()
                increment_counter(team_id, normalized_query_hash, is_cached=False)
                queries_warmed += 1

            except Exception as e:
                context.log.exception(f"Error warming query for team {team_id}")
                capture_exception(e)

    context.log.info(f"Warmed {queries_warmed} queries ({queries_skipped} were already cached)")
    context.add_output_metadata({"queries_warmed": queries_warmed, "queries_skipped": queries_skipped})


@dagster.job(
    description="Warms web analytics query cache for frequently-run queries",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_cache_warming": "web_analytics_cache_warming",
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
