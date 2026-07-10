"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

from django.db.models import Q

import structlog

from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo
from products.mcp_store.backend.models import MCPServerInstallation

logger = structlog.get_logger(__name__)


def _resolve_name(installation: MCPServerInstallation) -> str:
    if installation.display_name:
        return installation.display_name
    if installation.template and installation.template.name:
        return installation.template.name
    return installation.url


def _is_oauth_ready(installation: MCPServerInstallation) -> bool:
    if installation.auth_type != "oauth":
        return True
    sensitive = installation.sensitive_configuration or {}
    if sensitive.get("needs_reauth"):
        return False
    if not sensitive.get("access_token"):
        return False
    return True


def _to_info(installation: MCPServerInstallation, team_id: int) -> ActiveInstallationInfo:
    return ActiveInstallationInfo(
        id=str(installation.id),
        name=_resolve_name(installation),
        proxy_path=f"/api/environments/{team_id}/mcp_server_installations/{installation.id}/proxy/",
        scope=installation.scope,
    )


def get_active_installations(team_id: int, user_id: int) -> list[ActiveInstallationInfo]:
    """Return active, ready-to-use personal MCP installations for a user.

    Filters out disabled installations and OAuth installations that
    need reauthorization or are still pending token exchange.
    """
    try:
        # list() evaluates the lazy queryset here so DB errors hit this handler.
        installations = list(
            MCPServerInstallation.objects.filter(
                team_id=team_id, user_id=user_id, is_enabled=True, scope="personal"
            ).select_related("template")
        )
    except Exception as e:
        logger.warning("Error fetching MCP installations", error=str(e), team_id=team_id)
        return []

    results: list[ActiveInstallationInfo] = []
    for installation in installations:
        if not _is_oauth_ready(installation):
            logger.debug(
                "Skipping MCP installation not ready",
                installation_id=str(installation.id),
            )
            continue
        results.append(_to_info(installation, team_id))

    logger.debug("Found active MCP installations", count=len(results), team_id=team_id)
    return results


def get_installations_for_sandbox(
    team_id: int,
    *,
    user_id: int | None = None,
    include_personal: bool = False,
) -> list[ActiveInstallationInfo]:
    """Return MCP installations for sandbox agent use.

    Always includes shared (team-wide) installations. Optionally includes
    the user's personal installations when ``include_personal`` is True
    and a ``user_id`` is provided. When the user has a ready personal
    installation for the same URL as a shared one, only the personal one is
    returned — the user acts as themselves rather than through the shared
    credential.
    """
    try:
        scope_filter = Q(scope="shared")
        if include_personal and user_id is not None:
            scope_filter = scope_filter | Q(scope="personal", user_id=user_id)

        # list() evaluates the lazy queryset here so DB errors hit this handler.
        installations = list(
            MCPServerInstallation.objects.filter(team_id=team_id, is_enabled=True)
            .filter(scope_filter)
            .select_related("template")
        )
    except Exception as e:
        logger.warning("Error fetching MCP installations for sandbox", error=str(e), team_id=team_id)
        return []

    ready = [installation for installation in installations if _is_oauth_ready(installation)]
    if include_personal and user_id is not None:
        personal_urls = {installation.url for installation in ready if installation.scope == "personal"}
        ready = [
            installation
            for installation in ready
            if installation.scope == "personal" or installation.url not in personal_urls
        ]

    results = [_to_info(installation, team_id) for installation in ready]

    logger.debug(
        "Found MCP installations for sandbox",
        count=len(results),
        team_id=team_id,
        include_personal=include_personal,
    )
    return results
