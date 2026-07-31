"""Keeps the gateway registry (`MCPGatewayServer`) in sync with installations.

The registry is sparse: a row exists only once someone touched the server.
Every credential row registers its (team, url) with the gateway at the success
points of the install/share/OAuth-start flows, and admins materialize a row for
an untouched catalog template when they toggle it (the gateway API's
set_template_enabled action). Servers with no row follow the team's
`default_servers_enabled` posture."""

import structlog

from posthog.models import User

from .models import MCPGatewayServer, MCPServerInstallation, MCPServiceAccountServerAccess, TeamMCPGatewayConfig

logger = structlog.get_logger(__name__)

_GATEWAY_SERVER_NAME_MAX_LENGTH = 200


def members_can_manage_agent_access(team_id: int) -> bool:
    """Whether regular members may grant MCP access to agents and tune it."""
    config = TeamMCPGatewayConfig.objects.for_team(team_id).first()
    return config is None or config.allow_member_agent_access


def server_disabled_reason(team_id: int, url: str) -> str | None:
    """Resolve enablement for one server URL: an explicit registration wins;
    otherwise the team's default posture applies (enabled when never set).
    Returns None when enabled, else the layer that disabled it
    ("row_disabled" or "default_disabled")."""
    server = MCPGatewayServer.objects.for_team(team_id).filter(url=url).only("id", "is_team_enabled").first()
    if server is not None:
        return None if server.is_team_enabled else "row_disabled"
    config = TeamMCPGatewayConfig.objects.for_team(team_id).only("id", "default_servers_enabled").first()
    if config is None or config.default_servers_enabled:
        return None
    return "default_disabled"


def link_installation_to_gateway(installation: MCPServerInstallation, created_by: User | None) -> MCPGatewayServer:
    """Ensure a gateway registration exists for the installation's (team, url)
    and point the installation at it. Idempotent."""
    template = installation.template
    server, _ = MCPGatewayServer.objects.for_team(installation.team_id).get_or_create(
        url=installation.url,
        defaults={
            "team_id": installation.team_id,
            "name": (installation.display_name or (template.name if template else installation.url))[
                :_GATEWAY_SERVER_NAME_MAX_LENGTH
            ],
            "description": installation.description,
            "template": template,
            "category": template.category if template else "dev",
            "created_by": created_by,
        },
    )

    update_fields: list[str] = []
    if template is not None and server.template_id is None:
        server.template = template
        update_fields.append("template")
    if update_fields:
        server.save(update_fields=[*update_fields, "updated_at"])

    if installation.gateway_server_id != server.id:
        installation.gateway_server = server
        installation.save(update_fields=["gateway_server", "updated_at"])

    return server


def installation_for_agent_grant(
    team_id: int, gateway_server: MCPGatewayServer, user_id: int
) -> MCPServerInstallation | None:
    """Choose the credential delegated by an agent-access action: the
    requesting user's own connection to the server. An agent never rides a
    credential its granter didn't connect themselves.
    """
    return (
        MCPServerInstallation.objects.filter(
            team_id=team_id,
            gateway_server=gateway_server,
            user_id=user_id,
            scope="personal",
        )
        .order_by("created_at")
        .first()
    )


def installation_for_agent_access(access: MCPServiceAccountServerAccess) -> MCPServerInstallation | None:
    """Resolve the exact credential bound to an access row."""
    installation = access.installation
    if installation is None:
        return None
    if installation.team_id != access.team_id or installation.gateway_server_id != access.gateway_server_id:
        logger.warning(
            "Refusing mismatched agent MCP credential",
            access_id=str(access.id),
            installation_id=str(installation.id),
        )
        return None
    return installation
