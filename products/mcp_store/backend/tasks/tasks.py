from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from ..models import MCPServerInstallation
from ..oauth import TokenRefreshError, is_token_expiring, refresh_installation_token_single_flight
from ..tools import ToolsFetchError, sync_installation_tools

logger = structlog.get_logger(__name__)

STALE_TOOL_SYNC_CUTOFF = timedelta(hours=24)


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


@shared_task(ignore_result=True)
@skip_team_scope_audit
def maintain_shared_installations() -> None:
    """Hourly upkeep for shared installations, which back gateway calls for the whole team:
    refresh expiring OAuth tokens ahead of demand and re-sync tool catalogs stale for >24h.
    Personal installations refresh lazily on use instead."""
    stale_cutoff = timezone.now() - STALE_TOOL_SYNC_CUTOFF
    installations = (
        MCPServerInstallation.objects.filter(scope="shared", is_enabled=True)
        .select_related("template")
        .annotate(latest_tool_seen_at=Max("tools__last_seen_at"))
    )
    for installation in installations:
        sensitive = installation.sensitive_configuration or {}
        if (
            installation.auth_type == "oauth"
            and not sensitive.get("needs_reauth")
            and sensitive.get("refresh_token")
            and is_token_expiring(sensitive)
        ):
            try:
                refresh_installation_token_single_flight(installation)
            except TokenRefreshError as exc:
                logger.info(
                    "maintain_shared_installations: token refresh failed",
                    installation_id=str(installation.id),
                    error=str(exc),
                )

        latest_tool_seen_at = installation.latest_tool_seen_at
        if latest_tool_seen_at is None or latest_tool_seen_at < stale_cutoff:
            try:
                sync_installation_tools(installation)
            except ToolsFetchError as exc:
                logger.info(
                    "maintain_shared_installations: tool sync failed",
                    installation_id=str(installation.id),
                    error=str(exc),
                )
