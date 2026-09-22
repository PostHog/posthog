"""Agent-facing gateway surface, authenticated by service-account tokens.

Agents call this root-level API with `Authorization: Bearer mcp_gw_...`; the
token resolves the team, so there is no project in the URL. Deliberately
outside the OpenAPI spec (like the OAuth redirect): it is an external token
surface, not part of the app schema.

Grants are per person: the token names the person whose credentials the run may
use, and only that person's grants plus the team's team-scoped grants are
visible or callable. A token with no credential owner reaches team-scoped grants
alone. Every tools/call resolves through the same policy engine as members,
under the agent's own scope.
"""

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.http.response import HttpResponseBase
from django.utils import timezone

import structlog
from rest_framework import viewsets
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.rate_limit import MCPProxyBurstThrottle, MCPProxySustainedThrottle

from ..agents import GatewayAgentPrincipal, resolve_gateway_agent_token
from ..gateway import (
    AGENT_GRANT_CREDENTIAL_OWNER_PARAM,
    agent_grant_owner_label,
    agent_grant_proxy_path,
    installation_for_agent_access,
    reachable_agent_grants,
)
from ..models import MCPServerInstallationTool, MCPServiceAccount, MCPServiceAccountServerAccess
from ..policy import GatewayCaller, PolicyContext
from ..proxy import proxy_mcp_request, validate_installation_auth
from .views import MCPProxyRenderer

logger = structlog.get_logger(__name__)


class _MCPGatewayAgentThrottle(SimpleRateThrottle):
    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        principal = request.auth
        if not isinstance(principal, GatewayAgentPrincipal):
            return None
        # The rate is sized for one person's traffic, so the key includes the
        # credential owner: keyed on the shared agent account alone, one
        # member's burst would throttle every teammate using the same agent.
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{principal.account.id}:{principal.credential_owner_id}",
        }


class MCPGatewayAgentBurstThrottle(_MCPGatewayAgentThrottle):
    scope = "mcp_gateway_agent_burst"
    rate = MCPProxyBurstThrottle.rate


class MCPGatewayAgentSustainedThrottle(_MCPGatewayAgentThrottle):
    scope = "mcp_gateway_agent_sustained"
    rate = MCPProxySustainedThrottle.rate


class GatewayAgentAuthentication(BaseAuthentication):
    """Resolves `Authorization: Bearer mcp_gw_...` to an active service account.

    Returns no user — the agent is the principal; downstream code reads it from
    `request.auth`."""

    def authenticate(self, request: Request) -> tuple[Any, GatewayAgentPrincipal] | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header.split(" ", 1)[1].strip()
        principal = resolve_gateway_agent_token(token)
        if principal is None:
            raise AuthenticationFailed("Invalid gateway token.")
        if principal.account.status != "active":
            raise AuthenticationFailed("This agent is paused.")
        return (None, principal)

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class GatewayAgentPermission(BasePermission):
    message = "A valid gateway token is required."

    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(request.auth, GatewayAgentPrincipal)


class MCPGatewayAgentViewSet(viewsets.ViewSet):
    """What an agent can see and call through the gateway."""

    authentication_classes = [GatewayAgentAuthentication]
    permission_classes = [GatewayAgentPermission]
    throttle_classes = [MCPGatewayAgentBurstThrottle, MCPGatewayAgentSustainedThrottle]

    def _accessible_server_access(self, principal: GatewayAgentPrincipal) -> list[MCPServiceAccountServerAccess]:
        # The admin kill switch overrides grants: a server turned off for the
        # team disappears from the agent catalog like it does for members.
        account = principal.account
        return list(
            MCPServiceAccountServerAccess.objects.for_team(account.team_id)
            .filter(service_account=account, gateway_server__is_team_enabled=True)
            .filter(reachable_agent_grants(account.team_id, principal.credential_owner_id))
            .select_related("gateway_server__template", "installation", "user")
            .order_by("gateway_server__name", "created_at")
        )

    def _touch(self, account: MCPServiceAccount) -> None:
        now = timezone.now()
        if account.last_active_at is None or now - account.last_active_at > timedelta(hours=1):
            MCPServiceAccount.objects.for_team(account.team_id).filter(pk=account.pk).update(last_active_at=now)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The agent's server catalog: every enabled server it has access to,
        with each tool's effective policy state."""
        principal = cast(GatewayAgentPrincipal, request.auth)
        account = principal.account
        catalog_entries = [
            (access, installation_for_agent_access(access)) for access in self._accessible_server_access(principal)
        ]
        active_entries = [
            (access, installation)
            for access, installation in catalog_entries
            if installation is not None and installation.is_enabled
        ]
        policy_contexts = PolicyContext.for_agent_servers(
            team_id=account.team_id,
            service_account_id=str(account.id),
            gateway_servers=(access.gateway_server for access, _installation in active_entries),
        )
        tools_by_installation: dict[UUID, list[MCPServerInstallationTool]] = defaultdict(list)
        active_installation_ids = [installation.id for _access, installation in active_entries]
        for tool in (
            MCPServerInstallationTool.objects.filter(
                installation_id__in=active_installation_ids,
                removed_at__isnull=True,
            )
            .order_by("installation_id", "tool_name", "-last_seen_at", "-id")
            .only("installation_id", "tool_name", "description", "input_schema", "annotations")
        ):
            tools_by_installation[tool.installation_id].append(tool)

        grants_per_server = Counter(access.gateway_server_id for access, _installation in catalog_entries)
        results = []
        for access, installation in catalog_entries:
            server = access.gateway_server
            tools = []
            seen: set[str] = set()
            tool_rows: list[MCPServerInstallationTool] = []
            if installation is not None and installation.is_enabled:
                tool_rows = tools_by_installation.get(installation.id, [])
            for tool in tool_rows:
                if tool.tool_name in seen:
                    continue
                seen.add(tool.tool_name)
                tools.append(
                    {
                        "name": tool.tool_name,
                        "description": tool.description or "",
                        "input_schema": tool.input_schema or {},
                        "state": policy_contexts[server.id]
                        .resolve(
                            tool.tool_name,
                            tool.annotations,
                        )
                        .state,
                    }
                )
            # Teammates who team-shared the same server each contribute their own
            # credential, so the catalog carries one entry per grant and the name
            # says whose connection it is.
            name = (
                f"{server.name} ({agent_grant_owner_label(access)})"
                if grants_per_server[server.id] > 1
                else server.name
            )
            results.append(
                {
                    "id": str(server.id),
                    "name": name,
                    "url": server.url,
                    "description": server.description,
                    "credential_owner_id": access.user_id,
                    "proxy_path": agent_grant_proxy_path(access),
                    "tools": tools,
                }
            )
        self._touch(account)
        return Response({"results": results})

    def _grant_for_proxy(
        self, principal: GatewayAgentPrincipal, gateway_server_id: str, credential_owner_param: str | None
    ) -> MCPServiceAccountServerAccess | None:
        """Resolve which member's credential this call rides.

        `credential_owner` in the query string picks between several members'
        team shares of one server; it can only ever select a grant this
        principal already reaches, so it selects rather than escalates. Without
        it, the run's own credential owner wins and a team share is the
        fallback, matching how the sandbox mounts them.
        """
        account = principal.account
        candidates = (
            MCPServiceAccountServerAccess.objects.for_team(account.team_id)
            .filter(service_account=account, gateway_server_id=gateway_server_id)
            .filter(reachable_agent_grants(account.team_id, principal.credential_owner_id))
            .select_related("gateway_server", "installation")
            .order_by("created_at", "id")
        )
        if credential_owner_param:
            if not credential_owner_param.isdigit():
                return None
            return candidates.filter(user_id=int(credential_owner_param)).first()
        rows = list(candidates)
        own = [row for row in rows if row.user_id == principal.credential_owner_id]
        return next(iter(own or rows), None)

    @action(detail=True, methods=["post"], url_path="proxy", renderer_classes=[MCPProxyRenderer])
    def proxy(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """Proxy one MCP request to the server as this agent."""
        principal = cast(GatewayAgentPrincipal, request.auth)
        account = principal.account
        if not pk:
            return HttpResponse('{"error": "Server not found"}', content_type="application/json", status=404)
        try:
            access = self._grant_for_proxy(principal, pk, request.query_params.get(AGENT_GRANT_CREDENTIAL_OWNER_PARAM))
        except (DjangoValidationError, ValueError):
            access = None
        if access is None:
            return HttpResponse(
                '{"error": "Server not found or not shared with this agent"}',
                content_type="application/json",
                status=404,
            )
        server = access.gateway_server
        if not server.is_team_enabled:
            return HttpResponse(
                '{"error": "Server is disabled for this team"}',
                content_type="application/json",
                status=403,
            )
        installation = installation_for_agent_access(access)
        if installation is None:
            return HttpResponse(
                '{"error": "This server has no credential shared with this agent"}',
                content_type="application/json",
                status=409,
            )

        logger.info(
            "mcp_gateway agent proxy request",
            team_id=account.team_id,
            gateway_server_id=str(server.id),
            service_account_id=str(account.id),
            credential_owner_id=access.user_id,
            grant_scope=access.scope,
        )

        ok, error_response = validate_installation_auth(installation)
        if not ok and error_response is not None:
            return error_response

        self._touch(account)
        caller = GatewayCaller(kind="agent", service_account_id=str(account.id))
        return proxy_mcp_request(
            request,
            installation,
            caller=caller,
            gateway_server=server,
            actor_label=account.handle,
            credential_owner_id=access.user_id,
            grant_scope=access.scope,
        )
