import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from ..models import MCPServerInstallation
from ..tools import ToolsFetchError, sync_installation_tools

logger = structlog.get_logger(__name__)


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
