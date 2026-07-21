import json
import statistics

from django.utils.dateparse import parse_datetime

import dagster
from dagster import Backoff, Jitter, RetryPolicy
from prometheus_client import Counter, Gauge

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dags.common import JobOwners
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting
from posthog.settings import CLICKHOUSE_CLUSTER

from products.analytics_platform.backend.lazy_computation.stale_policy import SHARED_BACKGROUND_WARMING_TRIGGERS
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import BACKGROUND_WARMING_TRIGGERS
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

WARMING_SHAPES_SELECTED_GAUGE = Gauge(
    "posthog_web_analytics_warming_shapes_selected",
    "Number of hot query shapes selected for web analytics warming in the last run",
)
WARMING_QUERIES_COUNTER = Counter(
    "posthog_web_analytics_warming_queries_total",
    "Web analytics warming outcomes per query shape",
    ["outcome"],  # warmed | skipped_fresh | failed | unsupported
)

cache_warming_retry_policy = RetryPolicy(
    max_retries=3,
    delay=2,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.FULL,
)


# Query kinds that carry the `useWebAnalyticsPrecompute` per-query toggle.
LAZY_PRECOMPUTE_QUERY_KINDS = frozenset(
    {"WebStatsTableQuery", "WebOverviewQuery", "WebGoalsQuery", "WebVitalsPathBreakdownQuery"}
)

# Per-team ceiling on selected shapes. Bounds how much hourly background compute a
# single tenant can claim by running many distinct shapes past the demand threshold
# (the queries replay outside the tenant's own request throttles).
MAX_SHAPES_PER_TEAM = 100

# Demand is selected by API query kind, not by query_type tag: the tag
# vocabulary is a growing zoo of strategy variants (no_join, session_id_set,
# lazy reads, per-breakdown inserts, …) and enumerating it would silently drop
# new variants from warming. Every kind in the web analytics family starts with
# "Web" (WebOverviewQuery, WebStatsTableQuery, WebVitalsQuery, …).
WARMABLE_QUERY_KIND_PREFIX = "Web"

# Web-family kinds with no get_query_runner branch (they execute through other
# paths). Excluded in the selection so they don't consume the capped slots or
# inflate dry-run counts; warm_queries_op's `unsupported` outcome remains the
# backstop for any future runnerless kind not yet listed here.
UNWARMABLE_QUERY_KINDS = ("WebVitalsQuery",)

# Internal helper rows of a single API call (bucket builds, id-set preflights);
# counting them would double-count demand for teams on those strategies.
INTERNAL_QUERY_TYPE_SUFFIXES = ("_lazy_insert", "_preflight")
_INTERNAL_QUERY_TYPE_FILTER = " OR ".join(f"endsWith(query_type, '{s}')" for s in INTERNAL_QUERY_TYPE_SUFFIXES)


def maybe_opt_into_lazy_precompute(query_json: dict) -> dict:
    """Opt a replayed query into the lazy precompute path.

    Replayed production shapes carry no per-query toggle (users only send one via
    the UI). Injecting an explicit `True` makes the warmer build precompute
    buckets regardless of the opt-in default in the runner's eligibility gate,
    while an explicit user `False` in the replayed shape is preserved. Whether a
    team may build buckets at all is decided by the runner's own gate — warming
    requests bypass the rollout flag there, so this injection needs no
    enablement check (flag evaluation is unreliable in Dagster anyway).
    """
    if query_json.get("kind") not in LAZY_PRECOMPUTE_QUERY_KINDS:
        return query_json
    if query_json.get("useWebAnalyticsPrecompute") is not None:
        return query_json
    return {**query_json, "useWebAnalyticsPrecompute": True}


def queries_to_keep_fresh(
    context: dagster.OpExecutionContext, days: int = 2, minimum_query_count: int = 10, max_shapes: int = 20000
) -> list[dict]:
    """Fleet-wide demand selection: every (team, query shape) with at least
    `minimum_query_count` runs in the window, hottest first, capped at
    `max_shapes`.

    The audience is implicit — any team with a hot shape is active on web
    analytics and benefits from warming. One batched query replaces the previous
    per-team loop, which could not scale past a handful of teams.
    """
    context.log.info(
        f"Selecting fleet-wide web analytics queries with >= {minimum_query_count} runs "
        f"in the last {days} days (cap {max_shapes} shapes)."
    )

    # Selection reads system.query_log across the whole cluster: Dagster connects
    # to offline nodes, while the user traffic we want to replay lands on other
    # replicas. (metrics_query_log_mv only looks usable — its DDL in
    # posthog/models/query_metrics/sql.py was never migrated, the table does not
    # exist in production.) Grouping by the query JSON alone (hash only kept for
    # logging) collapses strategy variants of one shape into one replay, and
    # demand is counted as distinct query_ids so duplicated log rows for one
    # request can't inflate it. The
    # trigger/feature exclusions keep the warmer's own replays — and every other
    # background warmer — out of the demand counts, otherwise a once-warmed shape
    # would keep itself hot forever. LIKE literals are %%-escaped because
    # clickhouse_driver %-formats the query when params are passed.
    # nosemgrep: clickhouse-fstring-param-audit (interpolations are module-level constants from hardcoded tuples, not user input; everything dynamic is parameterized)
    results = sync_execute(
        f"""
        SELECT
            team_id,
            query_json_raw,
            uniqExact(query_id) AS query_count,
            any(normalized_query_hash) AS normalized_query_hash
        FROM (
            SELECT
                JSONExtractInt(log_comment, 'team_id') AS team_id,
                JSONExtractString(log_comment, 'query', 'kind') AS query_kind,
                JSONExtractString(log_comment, 'query_type') AS query_type,
                JSONExtractString(log_comment, 'trigger') AS trigger,
                JSONExtractString(log_comment, 'feature') AS feature,
                JSONExtractRaw(log_comment, 'query') AS query_json_raw,
                normalizedQueryHash(query) AS normalized_query_hash,
                query_id
            FROM clusterAllReplicas(%(cluster)s, system.query_log)
            WHERE
                event_date >= toDate(now() - INTERVAL %(days)s DAY)
                AND event_time >= now() - INTERVAL %(days)s DAY
                AND type = 'QueryFinish'
                AND is_initial_query
                -- cheap substring prefilter before any JSON extraction; a
                -- superset of the kind filter below, false positives re-checked
                AND log_comment LIKE '%%{WARMABLE_QUERY_KIND_PREFIX}%%'
        ) AS sub
        WHERE
            team_id != 0
            AND query_json_raw != ''
            AND startsWith(query_kind, %(kind_prefix)s)
            AND query_kind NOT IN %(unwarmable_kinds)s
            AND NOT ({_INTERNAL_QUERY_TYPE_FILTER})
            AND trigger NOT IN %(background_triggers)s
            AND feature != %(cache_warmup_feature)s
        GROUP BY
            team_id,
            query_json_raw
        HAVING query_count >= %(minimum_query_count)s
        ORDER BY
            query_count DESC
        LIMIT %(max_shapes_per_team)s BY team_id
        LIMIT %(max_shapes)s
        """,
        {
            "cluster": CLICKHOUSE_CLUSTER,
            "days": days,
            "minimum_query_count": minimum_query_count,
            "max_shapes": max_shapes,
            "max_shapes_per_team": MAX_SHAPES_PER_TEAM,
            "kind_prefix": WARMABLE_QUERY_KIND_PREFIX,
            "unwarmable_kinds": UNWARMABLE_QUERY_KINDS,
            "background_triggers": tuple(BACKGROUND_WARMING_TRIGGERS | SHARED_BACKGROUND_WARMING_TRIGGERS),
            "cache_warmup_feature": Feature.CACHE_WARMUP.value,
        },
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


@dagster.op
def get_warmable_queries_op(context: dagster.OpExecutionContext) -> list[dict]:
    days = get_instance_setting("WEB_ANALYTICS_WARMING_DAYS")
    minimum_query_count = get_instance_setting("WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT")
    max_shapes = get_instance_setting("WEB_ANALYTICS_WARMING_MAX_SHAPES")

    queries = queries_to_keep_fresh(context, days=days, minimum_query_count=minimum_query_count, max_shapes=max_shapes)
    team_count = len({q["team_id"] for q in queries})

    WARMING_SHAPES_SELECTED_GAUGE.set(len(queries))
    context.log.info(f"Selected {len(queries)} hot query shapes across {team_count} teams")
    context.add_output_metadata(
        {
            "query_count": len(queries),
            "team_count": team_count,
            "cap_reached": len(queries) >= max_shapes,
        }
    )
    return queries


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_op(context: dagster.OpExecutionContext, queries: list[dict]) -> None:
    queries_warmed = 0
    queries_skipped = 0
    queries_failed = 0
    queries_unsupported = 0

    teams: dict[int, Team | None] = {}

    for query_info in queries:
        team_id = query_info["team_id"]
        query_json = query_info["query_json"]
        normalized_query_hash = query_info["normalized_query_hash"]

        if team_id not in teams:
            try:
                teams[team_id] = Team.objects.get(pk=team_id)
            except Team.DoesNotExist:
                context.log.warning(f"Team {team_id} not found, skipping")
                teams[team_id] = None
        team = teams[team_id]
        if team is None:
            continue

        try:
            # Tag before any runner work so the whole request — including the lazy
            # precompute gate, which lets warming traffic through regardless of the
            # rollout flag — is classified as background warming.
            tag_queries(team_id=team_id, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

            query_json = maybe_opt_into_lazy_precompute(query_json)

            # None only for kinds without a get_query_runner branch — the backstop
            # for runnerless kinds the selection doesn't know to exclude yet.
            # Validation errors on supported kinds still raise into the failure path.
            runner = get_query_runner_or_none(
                query=query_json,
                team=team,
                limit_context=LimitContext.QUERY_ASYNC,
            )
            if runner is None:
                WARMING_QUERIES_COUNTER.labels(outcome="unsupported").inc()
                queries_unsupported += 1
                continue

            cache_manager = DjangoCacheQueryCacheManager(team_id=team.pk, cache_key=runner.get_cache_key())
            cached_data = cache_manager.get_cache_data()

            if cached_data is not None:
                last_refresh = parse_datetime(cached_data["last_refresh"])
                is_stale = runner._is_stale(last_refresh)

                if not is_stale:
                    WARMING_QUERIES_COUNTER.labels(outcome="skipped_fresh").inc()
                    queries_skipped += 1
                    continue

            # TODO: We shouldn't try to run a query if it failed last run
            runner.run(analytics_props={"source": EventSource.CACHE_WARMING})
            WARMING_QUERIES_COUNTER.labels(outcome="warmed").inc()
            queries_warmed += 1

        except Exception as e:
            context.log.exception(f"Error warming query {normalized_query_hash} for team {team_id}")
            capture_exception(e)
            WARMING_QUERIES_COUNTER.labels(outcome="failed").inc()
            queries_failed += 1

    context.log.info(
        f"Warmed {queries_warmed} queries ({queries_skipped} already fresh, "
        f"{queries_failed} failed, {queries_unsupported} unsupported kinds)"
    )
    context.add_output_metadata(
        {
            "queries_warmed": queries_warmed,
            "queries_skipped": queries_skipped,
            "queries_failed": queries_failed,
            "queries_unsupported": queries_unsupported,
        }
    )


@dagster.op
def report_warming_plan_op(context: dagster.OpExecutionContext, queries: list[dict]) -> None:
    """Dry-run reporter: summarize what the warmer WOULD warm — team count, total
    query shapes, and the per-team distribution — without running (or
    precomputing) anything.

    Reuses the real selection op, so the counts reflect exactly what a live run
    at the current settings would touch.
    """
    shapes_per_team: dict[int, int] = {}
    for q in queries:
        shapes_per_team[q["team_id"]] = shapes_per_team.get(q["team_id"], 0) + 1
    per_team = sorted(shapes_per_team.items(), key=lambda x: -x[1])
    shape_counts = [c for _, c in per_team]
    total_underlying_requests = sum(q["query_count"] for q in queries)
    median_shapes = statistics.median(shape_counts) if shape_counts else 0

    context.log.info(
        f"DRY RUN — would warm {len(queries)} query shapes across {len(per_team)} teams "
        f"(~{total_underlying_requests} underlying requests over the warming window). "
        f"Per-team shapes: max={shape_counts[0] if shape_counts else 0}, median={median_shapes}. "
        f"Top teams by shape count: {per_team[:10]}"
    )
    context.add_output_metadata(
        {
            "dry_run": True,
            "team_count": len(per_team),
            "total_query_shapes_to_warm": len(queries),
            "total_underlying_requests": total_underlying_requests,
            "max_shapes_per_team": shape_counts[0] if shape_counts else 0,
            "median_shapes_per_team": median_shapes,
            "top_10_teams_by_shape_count": str(per_team[:10]),
        }
    )


@dagster.job(
    description="Warms web analytics query cache and precompute buckets for frequently-run queries fleet-wide",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_cache_warming": "web_analytics_cache_warming",
    },
)
def web_analytics_cache_warming_job():
    queries = get_warmable_queries_op()
    warm_queries_op(queries)


@dagster.job(
    description="Dry run: report how many web analytics query shapes cache warming would warm, without warming",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_cache_warming": "web_analytics_cache_warming_dry_run",
    },
)
def web_analytics_cache_warming_dry_run_job():
    queries = get_warmable_queries_op()
    report_warming_plan_op(queries)


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
