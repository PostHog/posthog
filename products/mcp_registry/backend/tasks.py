from typing import Any

import structlog
import posthoganalytics
from celery import shared_task
from celery.schedules import crontab

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.mcp_registry.backend.aggregation import aggregate_measured_servers
from products.mcp_registry.backend.constants import MCP_REGISTRY_FEATURE_FLAG, MCP_REGISTRY_PIPELINE_DISTINCT_ID
from products.mcp_registry.backend.crawl import crawl_official_registry
from products.mcp_registry.backend.probe import probe_stalest_servers
from products.mcp_registry.backend.ranking import RANKING_VERSIONS, compute_ranking_run

logger = structlog.get_logger(__name__)

# Registered centrally in posthog/tasks/scheduled.py (crontabs are not auto-collected).
MCP_REGISTRY_SYNC_CRONTAB = crontab(hour="5", minute="45")


def is_pipeline_enabled() -> bool:
    """Deployment-level kill switch, evaluated with a constant distinct_id. Fails closed."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                MCP_REGISTRY_FEATURE_FLAG,
                MCP_REGISTRY_PIPELINE_DISTINCT_ID,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("mcp_registry.pipeline_flag_check_failed")
        return False


def run_sync_pipeline(skip_crawl: bool = False, skip_probe: bool = False) -> dict[str, Any]:
    """Crawl -> aggregate -> probe -> rank, each stage isolated so one failure
    doesn't starve the rest (yesterday's crawl still deserves today's ranking)."""
    outcome: dict[str, Any] = {}
    if not skip_crawl:
        try:
            created, updated = crawl_official_registry()
            outcome["crawl"] = {"created": created, "updated": updated}
        except Exception:
            logger.exception("mcp_registry.sync.crawl_failed")
            outcome["crawl"] = "failed"
    try:
        outcome["measured_sources"] = aggregate_measured_servers()
    except Exception:
        logger.exception("mcp_registry.sync.aggregate_failed")
        outcome["measured_sources"] = "failed"
    if not skip_probe:
        try:
            outcome["probed"] = probe_stalest_servers()
        except Exception:
            logger.exception("mcp_registry.sync.probe_failed")
            outcome["probed"] = "failed"
    outcome["ranking_runs"] = {}
    for version in sorted(RANKING_VERSIONS):
        try:
            run = compute_ranking_run(version)
            outcome["ranking_runs"][version] = run.server_count
        except Exception:
            logger.exception("mcp_registry.sync.ranking_failed", version=version)
            outcome["ranking_runs"][version] = "failed"
    logger.info("mcp_registry.sync.done", **{k: v for k, v in outcome.items() if k != "ranking_runs"})
    return outcome


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def run_mcp_registry_sync() -> None:
    if not is_pipeline_enabled():
        return
    run_sync_pipeline()
