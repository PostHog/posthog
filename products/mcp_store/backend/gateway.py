"""Keeps the gateway registry (`MCPGatewayServer`) in sync with installations.

Every credential row registers its (team, url) with the gateway at the success
points of the install/share flows, so the gateway sees one server per URL no
matter how many members connected."""

import structlog

from posthog.models import User

from .models import (
    MCPGatewayServer,
    MCPServerInstallation,
    MCPServerTemplate,
    MCPServiceAccountServerAccess,
    TeamMCPGatewayConfig,
)

logger = structlog.get_logger(__name__)

_GATEWAY_SERVER_NAME_MAX_LENGTH = 200


def members_can_manage_agent_access(team_id: int) -> bool:
    """Whether regular members may grant MCP access to agents and tune it."""
    config = TeamMCPGatewayConfig.objects.for_team(team_id).first()
    return config is None or config.allow_member_agent_access


def sync_catalog_templates_to_gateway(team_id: int) -> None:
    """Ensure every active catalog template is registered for the team."""
    templates = list(
        MCPServerTemplate.objects.filter(is_active=True).only("id", "name", "url", "description", "category")
    )
    if not templates:
        return

    existing_by_url = {
        server.url: server
        for server in MCPGatewayServer.objects.for_team(team_id)
        .filter(url__in=[template.url for template in templates])
        .only("id", "url", "template_id")
    }

    linked_servers: list[MCPGatewayServer] = []
    new_servers: list[MCPGatewayServer] = []
    for template in templates:
        existing = existing_by_url.get(template.url)
        if existing is not None:
            if existing.template_id is None:
                existing.template = template
                linked_servers.append(existing)
            continue
        new_servers.append(
            MCPGatewayServer(
                team_id=team_id,
                name=template.name,
                url=template.url,
                description=template.description,
                category=template.category,
                template=template,
                is_team_enabled=True,
            )
        )

    if linked_servers:
        MCPGatewayServer.objects.for_team(team_id).bulk_update(linked_servers, ["template"])
    if new_servers:
        MCPGatewayServer.objects.for_team(team_id).bulk_create(new_servers, ignore_conflicts=True)


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
            "auth_mode": "individual",
            "created_by": created_by,
        },
    )

    update_fields: list[str] = []
    # A shared credential turns the whole registration into shared-auth mode;
    # the reverse transition is explicit (see set_gateway_auth_mode).
    if installation.scope == "shared" and server.auth_mode != "shared":
        server.auth_mode = "shared"
        update_fields.append("auth_mode")
    if template is not None and server.template_id is None:
        server.template = template
        update_fields.append("template")
    if update_fields:
        server.save(update_fields=[*update_fields, "updated_at"])

    if installation.gateway_server_id != server.id:
        installation.gateway_server = server
        installation.save(update_fields=["gateway_server", "updated_at"])

    return server


def set_gateway_auth_mode(installation: MCPServerInstallation, mode: str) -> None:
    """Flip the registration's auth mode (e.g. back to individual on unshare)."""
    server = installation.gateway_server
    if server is None:
        return
    if server.auth_mode != mode:
        server.auth_mode = mode
        server.save(update_fields=["auth_mode", "updated_at"])


def installation_for_agent_grant(
    team_id: int, gateway_server: MCPGatewayServer, user_id: int
) -> MCPServerInstallation | None:
    """Choose the credential delegated by an agent-access action.

    A requesting user's personal connection is the natural meaning of "share
    access". If they do not have one, an existing team-shared credential is a
    valid fallback.
    """
    personal = (
        MCPServerInstallation.objects.filter(
            team_id=team_id,
            gateway_server=gateway_server,
            user_id=user_id,
            scope="personal",
        )
        .order_by("created_at")
        .first()
    )
    if personal is not None:
        return personal
    return (
        MCPServerInstallation.objects.filter(
            team_id=team_id,
            gateway_server=gateway_server,
            scope="shared",
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
