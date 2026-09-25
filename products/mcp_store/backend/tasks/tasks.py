import structlog
from celery import shared_task
from celery.schedules import crontab

from posthog.celery_queues import CeleryQueue
from posthog.redis import get_client
from posthog.scoping_audit import skip_team_scope_audit

from ..catalog_sync import sync_mcp_catalog
from ..models import MCPServerInstallation
from ..tools import ToolsFetchError, sync_installation_tools

logger = structlog.get_logger(__name__)

# Registered centrally in posthog/tasks/scheduled.py (crontabs are not auto-collected).
#
# The poll is deliberately more frequent than DCR_REPROBE_INTERVAL, which is what actually
# paces the probes. A once-a-day poll would alias against a 24-hour interval: a run that
# stamps last_probed_at a few seconds after the hour leaves the next day's run just under
# the interval, so every entry would skip a day and re-probe every 48 hours instead.
MCP_STORE_CATALOG_SYNC_CRONTAB = crontab(hour="*/6", minute="45")

# One probe makes several sequential requests at a 10 second timeout, and a whole catalog of
# slow vendors would otherwise hold a worker for far longer than the sync is worth. The
# limit sits well above a healthy run so it only binds when vendors are hanging.
_CATALOG_SYNC_SOFT_TIME_LIMIT = 60 * 10
_CATALOG_SYNC_HARD_TIME_LIMIT = _CATALOG_SYNC_SOFT_TIME_LIMIT + 60


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=_CATALOG_SYNC_SOFT_TIME_LIMIT,
    time_limit=_CATALOG_SYNC_HARD_TIME_LIMIT,
)
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


# A listing that fails here leaves the installation with no tool rows, and the
# gateway refuses every call to a tool that has no row.
@shared_task(
    ignore_result=True,
    autoretry_for=(ToolsFetchError,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
@skip_team_scope_audit
def sync_installation_tools_task(installation_id: str) -> None:
    try:
        installation = MCPServerInstallation.objects.get(id=installation_id)
    except MCPServerInstallation.DoesNotExist:
        logger.info("sync_installation_tools_task: installation gone", installation_id=installation_id)
        return
    sync_installation_tools(installation)
