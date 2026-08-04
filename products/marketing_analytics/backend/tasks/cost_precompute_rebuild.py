"""Background rebuild of the native cost precompute for an explicit date range.

The rebuild half of the invalidate/rebuild endpoint. Invalidation itself is a single indexed DELETE
and runs inline on the request, but the rebuild is `sources × grains × days` ClickHouse INSERTs —
minutes to tens of minutes on a cold range — so it cannot sit on a request thread.

Skipping the rebuild entirely would also work (the next read materializes what it needs, and the
warmer converges for teams on its allowlist), but then the user who asked for the rebuild pays the
full cold materialization inline on their next page load, which is the latency this whole precompute
layer exists to avoid.
"""

import time
from datetime import date

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.marketing_analytics.backend.services.cost_precompute_invalidation import rebuild_cost_precompute

logger = structlog.get_logger(__name__)

COST_REBUILD_RUN = Counter(
    "marketing_analytics_cost_precompute_rebuild_total",
    "Requested rebuilds of the marketing analytics cost precompute, by outcome.",
    labelnames=["outcome"],
)

# A rebuild drives one ensure per (source, grain, day), each with the framework's 180s wait budget.
# Generous because the point of the task is to absorb a cold range; the range cap on the endpoint is
# what actually bounds the work.
COST_REBUILD_SOFT_TIME_LIMIT = 1800
COST_REBUILD_TIME_LIMIT = COST_REBUILD_SOFT_TIME_LIMIT + 30

# Drop a rebuild that sat in the queue this long — by then the range has likely been re-requested,
# or the next read has materialized it anyway.
COST_REBUILD_EXPIRES_SECONDS = 30 * 60


@shared_task(
    ignore_result=True,
    # Same queue as insight cache warming, so this paces against ClickHouse with the other warmers.
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    expires=COST_REBUILD_EXPIRES_SECONDS,
    # No retries: the range is already invalidated, so the next read or warmer tick converges. A retry
    # would re-scan the whole range for the chunks that already landed.
    max_retries=0,
    soft_time_limit=COST_REBUILD_SOFT_TIME_LIMIT,
    time_limit=COST_REBUILD_TIME_LIMIT,
)
@skip_team_scope_audit
def rebuild_marketing_cost_precompute(team_id: int, date_from: str, date_to: str) -> None:
    """Dates are ISO strings because Celery arguments have to be JSON-serializable."""
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.warning("marketing_cost_precompute_rebuild_team_missing", team_id=team_id)
        COST_REBUILD_RUN.labels(outcome="failed").inc()
        return

    started = time.monotonic()
    logger.info("marketing_cost_precompute_rebuild_started", team_id=team_id, date_from=date_from, date_to=date_to)
    try:
        # Tag before the work so the ensures' ClickHouse queries are attributed to cache warming
        # rather than to a user-facing read. Celery resets tags on task_postrun.
        tag_queries(team_id=team_id, feature=Feature.CACHE_WARMUP, product=Product.MARKETING_ANALYTICS)
        done, failures = rebuild_cost_precompute(team, date.fromisoformat(date_from), date.fromisoformat(date_to))
    except Exception:
        logger.exception("marketing_cost_precompute_rebuild_failed", team_id=team_id)
        COST_REBUILD_RUN.labels(outcome="failed").inc()
        return

    COST_REBUILD_RUN.labels(outcome="partial" if failures else "succeeded").inc()
    logger.info(
        "marketing_cost_precompute_rebuild_finished",
        team_id=team_id,
        chunks_done=done,
        failures=failures,
        duration_seconds=round(time.monotonic() - started, 3),
    )
