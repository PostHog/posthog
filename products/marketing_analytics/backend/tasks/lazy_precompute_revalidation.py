"""Background revalidation for stale-served marketing analytics reads.

The revalidate half of stale-while-revalidate (RFC 5861). When a user-facing read is served from
expired-within-grace jobs, the read path enqueues this task (see
`marketing_lazy_precompute.enqueue_stale_revalidation`) to re-run the query in the background, so the
next fetch is fresh instead of waiting on the hourly Dagster warmer — which only covers the teams on its
allowlist, so for everyone else this task is the *only* refresh mechanism.

Building the query via `to_query()`, rather than driving each `ensure_precomputed` by hand, is
deliberate: it fires exactly the ensures the read fires (touchpoints, conversions, costs), so the two
cannot drift apart. We build but do NOT execute the query — see the warehouse-access note on the
`to_query()` call for why executing would be a data-access leak.

Duplicate tasks are tolerated rather than deduped: the framework's PENDING-job unique index collapses
concurrent recomputes to one insert, and once the first task has refreshed the windows the rest are cheap
warm reads on a queue that paces ClickHouse work anyway.
"""

import time

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import REVALIDATION_TRIGGER

logger = structlog.get_logger(__name__)

REVALIDATION_RUN = Counter(
    "marketing_analytics_precompute_revalidation_total",
    "Background stale-while-revalidate re-runs of marketing analytics queries.",
    labelnames=["outcome", "query_kind"],
)

# A cold rebuild drives touchpoints, per-goal conversions and per-source costs, each with the framework's
# 180s wait budget, plus the read itself. Mirrors the web analytics revalidation task's limits.
REVALIDATION_SOFT_TIME_LIMIT = 600
REVALIDATION_TIME_LIMIT = REVALIDATION_SOFT_TIME_LIMIT + 30

# Discard tasks that sat in the queue this long: by then a sibling task, the warmer, or a newer stale hit
# has already covered it. The queue's shedding valve against enqueue bursts on a hot shape.
REVALIDATION_EXPIRES_SECONDS = 15 * 60


@shared_task(
    ignore_result=True,
    # Same queue insight cache warming uses — keeps ClickHouse from being overwhelmed.
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    expires=REVALIDATION_EXPIRES_SECONDS,
    # No retries: the next stale hit re-enqueues, and the warmer converges regardless.
    max_retries=0,
    soft_time_limit=REVALIDATION_SOFT_TIME_LIMIT,
    time_limit=REVALIDATION_TIME_LIMIT,
)
@skip_team_scope_audit
def revalidate_marketing_analytics_precompute(team_id: int, query: dict) -> None:
    query_kind = str(query.get("kind"))
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.warning("marketing_analytics_swr_revalidation_team_missing", team_id=team_id, query_kind=query_kind)
        REVALIDATION_RUN.labels(outcome="failed", query_kind=query_kind).inc()
        return

    logger.info("marketing_analytics_swr_revalidation_started", team_id=team_id, query_kind=query_kind)
    started = time.monotonic()
    try:
        # Tag BEFORE building the runner: tags live in a contextvar that the runner's construction-time
        # I/O inherits. The trigger and the CACHE_WARMUP feature both classify this re-run as a
        # refresher, so its ensures get no serve-stale grace (it must not serve stale to itself, or the
        # data would never refresh) and keep the framework's full wait budget. Celery resets query tags
        # on task_postrun, so this never leaks across tasks.
        tag_queries(
            team_id=team_id,
            trigger=REVALIDATION_TRIGGER,
            feature=Feature.CACHE_WARMUP,
            product=Product.MARKETING_ANALYTICS,
        )
        runner = get_query_runner(query=query, team=team, limit_context=LimitContext.QUERY_ASYNC)
        # Build the query only — do NOT execute it. to_query() drives every read-path ensure (touchpoints,
        # conversions, costs), rebuilding the expired precompute windows, which is the whole job. We stop
        # short of executing because this runner is userless with warehouse access control bypassed (so it
        # can materialize every source's costs): a full run would write that all-sources aggregated
        # response into the per-team result cache, which a user without access to some of those warehouse
        # sources could then read. Leaving the result cache alone, the next user read recomputes the
        # response under its own access — now over hot precomputes — and caches it correctly.
        runner.to_query()
    except Exception:
        logger.exception("marketing_analytics_swr_revalidation_failed", team_id=team_id, query_kind=query_kind)
        REVALIDATION_RUN.labels(outcome="failed", query_kind=query_kind).inc()
        return

    REVALIDATION_RUN.labels(outcome="succeeded", query_kind=query_kind).inc()
    logger.info(
        "marketing_analytics_swr_revalidation_finished",
        team_id=team_id,
        query_kind=query_kind,
        duration_seconds=round(time.monotonic() - started, 3),
    )
