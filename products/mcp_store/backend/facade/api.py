"""
Facade API for mcp_store.

This is the ONLY module other apps are allowed to import.
"""

from typing import Any

import structlog

from posthog.models import Team, User

from products.mcp_store.backend.analytics import installation_display_name
from products.mcp_store.backend.facade.contracts import ActiveInstallationInfo, GatewayCallResult, GatewayToolInfo
from products.mcp_store.backend.gateway import (
    call_gateway_tool as _call_gateway_tool,
    is_credential_ready,
    list_gateway_tools as _list_gateway_tools,
    resolve_active_installations,
)
from products.mcp_store.backend.models import MCPServerInstallation

logger = structlog.get_logger(__name__)


def _to_info(installation: MCPServerInstallation, team_id: int) -> ActiveInstallationInfo:
    return ActiveInstallationInfo(
        id=str(installation.id),
        name=installation_display_name(installation),
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
        if not is_credential_ready(installation):
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
        ready = resolve_active_installations(team_id, user_id=user_id, include_personal=include_personal)
    except Exception as e:
        logger.warning("Error fetching MCP installations for sandbox", error=str(e), team_id=team_id)
        return []

    results = [_to_info(installation, team_id) for installation in ready]

    logger.debug(
        "Found MCP installations for sandbox",
        count=len(results),
        team_id=team_id,
        include_personal=include_personal,
    )
    return results


def list_gateway_tools(
    team_id: int,
    user_id: int,
    query: str | None = None,
    name: str | None = None,
) -> list[GatewayToolInfo]:
    """List the namespaced tools available to a user through the aggregated MCP gateway.

    ``query`` is a substring search over tool name and description;
    ``name`` filters to an exact namespaced tool name.
    """
    return _list_gateway_tools(team_id, user_id, search=query, name=name)


def call_gateway_tool(
    team_id: int,
    user_id: int,
    tool: str,
    arguments: dict[str, Any],
    consumer: str | None = None,
) -> GatewayCallResult:
    """Execute a namespaced gateway tool (``{server_slug}/{tool_name}``) as a user.

    Raises the ``Gateway*Error`` types from ``facade.contracts`` on failure.
    """
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    return _call_gateway_tool(team=team, user=user, tool=tool, arguments=arguments, consumer=consumer)
