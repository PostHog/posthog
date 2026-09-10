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
    """Queue the catalog sync once per deploy window (Redis lock so only one pod runs it)."""
    lock_key = "posthog_sync_mcp_server_templates_task_lock"
    try:
        r = get_client()
        # nx+ex in one call — a crash between a separate setnx and expire would leave
        # a TTL-less key that permanently skips the sync.
        if not r.set(lock_key, 1, nx=True, ex=60 * 60):
            logger.info("Not queuing sync_mcp_server_templates task: lock already set")
            return
    except Exception:
        logger.exception("Failed to acquire sync_mcp_server_templates lock")
        return
    try:
        logger.info("Queuing sync_mcp_server_templates celery task (redis lock)")
        sync_mcp_server_templates_task.delay()
    except Exception:
        logger.exception("Failed to queue sync_mcp_server_templates celery task")
        try:
            # Give the lock back so the next pod startup retries the enqueue instead
            # of the sync silently dropping for the whole lock window.
            r.delete(lock_key)
        except Exception:
            logger.exception("Failed to release sync_mcp_server_templates lock")


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
