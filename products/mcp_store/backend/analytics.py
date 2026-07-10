"""Server-side `$mcp_tool_call` emission for MCP Store traffic.

Both the aggregated gateway (`$mcp_source: "gateway"`) and the per-installation
proxy (`$mcp_source: "store_proxy"`) report through here. Property naming is
aligned with the Hono MCP server's analytics (services/mcp/src/hono/analytics.ts)
so both surfaces land in the same MCP analytics dashboards.

Only metadata is ever captured — tool names, durations, error types. Tool
arguments, results, headers, and credentials must never flow through here.
"""

from urllib.parse import urlparse

from django.utils.text import slugify

import structlog

from posthog.event_usage import report_user_action
from posthog.models import Team, User

from .models import MCPServerInstallation

logger = structlog.get_logger(__name__)

# Keep in sync with MCP_TOOL_CALL_EVENT in products/mcp_analytics/backend/constants.py.
# Defined locally because mcp_store is isolated and must not import other products' internals.
MCP_TOOL_CALL_EVENT = "$mcp_tool_call"

# Consumers identify themselves with this header (same convention as the Hono MCP server).
MCP_CONSUMER_HEADER = "x-posthog-mcp-consumer"


def installation_display_name(installation: MCPServerInstallation) -> str:
    if installation.display_name:
        return installation.display_name
    if installation.template and installation.template.name:
        return installation.template.name
    return installation.url


def base_server_slug(installation: MCPServerInstallation) -> str:
    return slugify(installation_display_name(installation)) or "server"


def report_mcp_tool_call(
    user: User,
    team: Team,
    *,
    tool_name: str,
    source: str,
    server_slug: str,
    installation: MCPServerInstallation,
    duration_ms: int,
    is_error: bool,
    error_type: str | None = None,
    consumer: str | None = None,
) -> None:
    """Capture a `$mcp_tool_call` event. Never raises — analytics must not break the request."""
    try:
        properties: dict[str, str | int | bool | None] = {
            "$ai_product": "mcp",
            "$mcp_source": source,
            "$mcp_tool_name": tool_name,
            "$mcp_gateway_server": server_slug,
            "$mcp_gateway_installation_id": str(installation.id),
            "$mcp_upstream_host": urlparse(installation.url).hostname or "",
            "$mcp_duration_ms": duration_ms,
            "$mcp_is_error": is_error,
            "$mcp_error_type": error_type,
            "$mcp_consumer": consumer or None,
            "$mcp_scope": installation.scope,
            "$mcp_project_id": team.id,
            "team_id": team.id,
        }
        report_user_action(user, MCP_TOOL_CALL_EVENT, properties, team=team)
    except Exception:
        logger.warning("Failed to report $mcp_tool_call", installation_id=str(installation.id), exc_info=True)
