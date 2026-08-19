"""Keeps the gateway registry (`MCPGatewayServer`) in sync with installations.

The registry is sparse: a row exists only once someone touched the server.
Every credential row registers its (team, url) with the gateway at the success
points of the install/share/OAuth-start flows, and admins materialize a row for
an untouched catalog template when they toggle it (the gateway API's
set_template_enabled action). Servers with no row follow the team's
`default_servers_enabled` posture."""

from django.db.models import Exists, OuterRef, Q

import structlog

from posthog.models import User

from .models import (
    MCPGatewayServer,
    MCPMemberServerRevocation,
    MCPServerInstallation,
    MCPServiceAccountServerAccess,
    TeamMCPGatewayConfig,
)

logger = structlog.get_logger(__name__)

_GATEWAY_SERVER_NAME_MAX_LENGTH = 200

# Query-string key naming whose credential a proxy call rides. Several members
# can team-share the same server with the same agent, so the gateway server id
# alone does not identify one grant.
AGENT_GRANT_CREDENTIAL_OWNER_PARAM = "credential_owner"


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


def reachable_agent_grants(team_id: int, credential_owner_id: int | None) -> Q:
    """The grants an agent run may use: the run's own credential owner's grants
    at any scope, plus every member's team-scoped grants.

    A run with no credential owner (an autonomous support reply, any scout
    run) reaches team-scoped grants only. Grant rows with no user resolve for
    nobody, so they are excluded from every lane.

    An admin's per-member revocation of the server applies here as well as on
    the member paths. Otherwise a member whose access an admin turned off would
    keep lending that credential to every agent run through a team-scoped grant.
    """
    revoked_for_grant_owner = MCPMemberServerRevocation.objects.for_team(team_id).filter(
        gateway_server_id=OuterRef("gateway_server_id"),
        user_id=OuterRef("user_id"),
    )
    reachable = Q(scope="team")
    if credential_owner_id is not None:
        reachable |= Q(user_id=credential_owner_id)
    return reachable & Q(user__isnull=False) & ~Q(Exists(revoked_for_grant_owner))


def agent_grant_owner_label(access: MCPServiceAccountServerAccess) -> str:
    """Whose connection a grant lends, for telling two members' shares of the
    same server apart. The label lands in sandbox configs, model prompts, and
    logs, so it carries the owner's numeric id — the same discriminator as the
    proxy path's credential_owner parameter — rather than an email or display
    name. Blank only for the user-less legacy rows, which no read path mounts.
    """
    return f"#{access.user_id}" if access.user_id is not None else ""


def agent_grant_proxy_path(access: MCPServiceAccountServerAccess) -> str:
    """Where an agent sends calls for one grant. The credential owner is named
    explicitly so that teammates' team shares of the same server stay
    addressable as separate servers."""
    return (
        f"/api/mcp_store/gateway/servers/{access.gateway_server_id}/proxy/"
        f"?{AGENT_GRANT_CREDENTIAL_OWNER_PARAM}={access.user_id}"
    )


def installation_for_agent_access(access: MCPServiceAccountServerAccess) -> MCPServerInstallation | None:
    """Resolve the exact credential bound to an access row, which must still be
    the granting person's own connection to that server."""
    installation = access.installation
    if installation is None:
        return None
    if (
        installation.team_id != access.team_id
        or installation.gateway_server_id != access.gateway_server_id
        or installation.user_id != access.user_id
    ):
        logger.warning(
            "Refusing mismatched agent MCP credential",
            access_id=str(access.id),
            installation_id=str(installation.id),
        )
        return None
    return installation
