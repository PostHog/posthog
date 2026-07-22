"""Keeps the gateway registry (`MCPGatewayServer`) in sync with installations.

Every credential row registers its (team, url) with the gateway at the success
points of the install/share flows, so the gateway sees one server per URL no
matter how many members connected."""

import structlog

from posthog.models import User

from .models import MCPGatewayServer, MCPServerInstallation, MCPServerTemplate

logger = structlog.get_logger(__name__)


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
            "name": installation.display_name or (template.name if template else installation.url),
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
