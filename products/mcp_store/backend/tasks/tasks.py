import structlog
from celery import shared_task

from posthog.redis import get_client
from posthog.scoping_audit import skip_team_scope_audit

from ..catalog_sync import sync_mcp_catalog
from ..models import MCPServerInstallation
from ..tools import ToolsFetchError, sync_installation_tools

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sync_mcp_server_templates_task() -> None:
    sync_mcp_catalog()


def queue_sync_mcp_server_templates() -> None:
    """Queue the catalog sync once per deploy window (Redis setnx lock so only one pod runs it)."""
    try:
        r = get_client()
        lock_key = "posthog_sync_mcp_server_templates_task_lock"
        if r.setnx(lock_key, 1):
            r.expire(lock_key, 60 * 60)
            logger.info("Queuing sync_mcp_server_templates celery task (redis lock)")
            sync_mcp_server_templates_task.delay()
        else:
            logger.info("Not queuing sync_mcp_server_templates task: lock already set")
    except Exception:
        logger.exception("Failed to queue sync_mcp_server_templates celery task")


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sync_installation_tools_task(installation_id: str) -> None:
    try:
        installation = MCPServerInstallation.objects.get(id=installation_id)
    except MCPServerInstallation.DoesNotExist:
        logger.info("sync_installation_tools_task: installation gone", installation_id=installation_id)
        return
    try:
        sync_installation_tools(installation)
    except ToolsFetchError as exc:
        logger.info(
            "sync_installation_tools_task: upstream fetch failed",
            installation_id=installation_id,
            error=str(exc),
        )
