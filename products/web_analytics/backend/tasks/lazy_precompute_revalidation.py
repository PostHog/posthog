"""Background revalidation for stale-served lazy precompute reads.

The revalidate half of the stale-while-revalidate semantics (RFC 5861): when a
user-facing read is served from expired-within-grace jobs, the read path
enqueues this task (see `web_lazy_precompute_common.enqueue_stale_revalidation`)
to re-run the query in the background so the next fetch is fresh instead of
waiting for the hourly eager warmer — which only covers warmed query shapes.

Duplicate tasks for the same query shape are tolerated rather than deduped: the
framework's PENDING-job unique index collapses concurrent recomputes to one
insert, and once the first task refreshes the jobs the rest are cheap warm
reads on a queue that paces ClickHouse work anyway.
"""

import time

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import REVALIDATION_TRIGGER

logger = structlog.get_logger(__name__)

REVALIDATION_RUN = Counter(
    "web_analytics_lazy_precompute_revalidation_total",
    "Background stale-while-revalidate re-runs of web analytics queries.",
    labelnames=["outcome", "query_kind"],
)

# Worst case is two ensure phases (current + compare period) at the framework's
# 180s wait budget each, plus the read itself; mirror the heatmap task's limits.
REVALIDATION_SOFT_TIME_LIMIT = 600
REVALIDATION_TIME_LIMIT = REVALIDATION_SOFT_TIME_LIMIT + 30

# Discard tasks that sat in the queue this long: by then either a sibling task
# already refreshed the jobs, the warmer did, or a newer stale hit re-enqueued.
# This is the queue's shedding valve against enqueue bursts on a hot stale shape.
REVALIDATION_EXPIRES_SECONDS = 15 * 60


@shared_task(
    ignore_result=True,
    # Same queue insight cache warming uses — prevents ClickHouse from being overwhelmed.
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    expires=REVALIDATION_EXPIRES_SECONDS,
    # No retries: the next stale hit re-enqueues, and the hourly warmer converges
    # regardless.
    max_retries=0,
    soft_time_limit=REVALIDATION_SOFT_TIME_LIMIT,
    time_limit=REVALIDATION_TIME_LIMIT,
)
@skip_team_scope_audit
def revalidate_web_analytics_precompute(team_id: int, query: dict) -> None:
    query_kind = str(query.get("kind"))
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.warning("web_analytics_swr_revalidation_team_missing", team_id=team_id, query_kind=query_kind)
        REVALIDATION_RUN.labels(outcome="failed", query_kind=query_kind).inc()
        return

    logger.info("web_analytics_swr_revalidation_started", team_id=team_id, query_kind=query_kind)
    started = time.monotonic()
    try:
        # Tag BEFORE constructing the runner (tags live in a contextvar the runner's
        # construction-time I/O inherits). The trigger puts this re-run in
        # BACKGROUND_WARMING_TRIGGERS, so the ensure gets no stale-while-revalidate
        # grace (it cannot serve stale to itself) and the full framework wait budget.
        # Celery resets query tags on task_postrun, so this never leaks across tasks.
        tag_queries(
            team_id=team_id,
            trigger=REVALIDATION_TRIGGER,
            feature=Feature.CACHE_WARMUP,
            product=Product.WEB_ANALYTICS,
        )
        runner = get_query_runner(query=query, team=team, limit_context=LimitContext.QUERY_ASYNC)
        # Force-refresh: recomputes the expired precompute windows and replaces the
        # HogQL result cache entry, so the next user fetch is fresh on both layers.
        runner.run(
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            analytics_props={"source": EventSource.CACHE_WARMING},
        )
    except Exception:
        logger.exception("web_analytics_swr_revalidation_failed", team_id=team_id, query_kind=query_kind)
        REVALIDATION_RUN.labels(outcome="failed", query_kind=query_kind).inc()
        return

    REVALIDATION_RUN.labels(outcome="completed", query_kind=query_kind).inc()
    logger.info(
        "web_analytics_swr_revalidation_completed",
        team_id=team_id,
        query_kind=query_kind,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
