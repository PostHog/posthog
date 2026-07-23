"""Agent-facing gateway surface, authenticated by service-account tokens.

Agents call this root-level API with `Authorization: Bearer mcp_gw_...`; the
token resolves the team, so there is no project in the URL. Deliberately
outside the OpenAPI spec (like the OAuth redirect): it is an external token
surface, not part of the app schema.

Each grant binds the credential its administrator delegated to the agent.
Every tools/call resolves through the same policy engine as members, under the
agent's own scope.
"""

from collections.abc import Iterable
from typing import Any, cast

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

from ..agents import resolve_gateway_agent_token
from ..gateway import installation_for_agent_access
from ..models import MCPServerInstallationTool, MCPServiceAccount, MCPServiceAccountServerAccess
from ..policy import GatewayCaller, PolicyContext
from ..proxy import proxy_mcp_request, validate_installation_auth
from .views import MCPProxyRenderer

logger = structlog.get_logger(__name__)


class GatewayAgentAuthentication(BaseAuthentication):
    """Resolves `Authorization: Bearer mcp_gw_...` to an active service account.

    Returns no user — the agent is the principal; downstream code reads it from
    `request.auth`."""

    def authenticate(self, request: Request) -> tuple[Any, MCPServiceAccount] | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header.split(" ", 1)[1].strip()
        account = resolve_gateway_agent_token(token)
        if account is None:
            raise AuthenticationFailed("Invalid gateway token.")
        if account.status != "active":
            raise AuthenticationFailed("This agent is paused.")
        return (None, account)

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class GatewayAgentPermission(BasePermission):
    message = "A valid gateway token is required."

    def has_permission(self, request: Request, view: Any) -> bool:
        return isinstance(request.auth, MCPServiceAccount)


class MCPGatewayAgentViewSet(viewsets.ViewSet):
    """What an agent can see and call through the gateway."""

    authentication_classes = [GatewayAgentAuthentication]
    permission_classes = [GatewayAgentPermission]

    def _accessible_server_access(self, account: MCPServiceAccount) -> list[MCPServiceAccountServerAccess]:
        return list(
            MCPServiceAccountServerAccess.objects.for_team(account.team_id)
            .filter(service_account=account)
            .select_related("gateway_server__template", "installation")
            .order_by("gateway_server__name")
        )

    def _touch(self, account: MCPServiceAccount) -> None:
        MCPServiceAccount.objects.unscoped().filter(pk=account.pk).update(last_active_at=timezone.now())

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The agent's server catalog: every enabled server it has access to,
        with each tool's effective policy state."""
        account = cast(MCPServiceAccount, request.auth)
        results = []
        for access in self._accessible_server_access(account):
            server = access.gateway_server
            installation = installation_for_agent_access(access)
            context = PolicyContext(
                team_id=account.team_id,
                caller=GatewayCaller(kind="agent", service_account_id=str(account.id)),
                gateway_server=server,
            )
            tools = []
            seen: set[str] = set()
            tool_rows: Iterable[tuple[str, str, dict[str, Any]]] = ()
            if installation is not None and installation.is_enabled:
                tool_rows = (
                    MCPServerInstallationTool.objects.filter(
                        installation=installation,
                        removed_at__isnull=True,
                    )
                    .order_by("tool_name", "-last_seen_at")
                    .values_list("tool_name", "description", "input_schema")
                )
            for tool_name, description, input_schema in tool_rows:
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                tools.append(
                    {
                        "name": tool_name,
                        "description": description or "",
                        "input_schema": input_schema or {},
                        "state": context.resolve(tool_name, description or "").state,
                    }
                )
            results.append(
                {
                    "id": str(server.id),
                    "name": server.name,
                    "url": server.url,
                    "description": server.description,
                    "proxy_path": f"/api/mcp_store/gateway/servers/{server.id}/proxy/",
                    "tools": tools,
                }
            )
        self._touch(account)
        return Response({"results": results})

    @action(detail=True, methods=["post"], url_path="proxy", renderer_classes=[MCPProxyRenderer])
    def proxy(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> HttpResponseBase:
        """Proxy one MCP request to the server as this agent."""
        account = cast(MCPServiceAccount, request.auth)
        if not pk:
            return HttpResponse('{"error": "Server not found"}', content_type="application/json", status=404)
        try:
            access = (
                MCPServiceAccountServerAccess.objects.for_team(account.team_id)
                .select_related("gateway_server", "installation")
                .get(service_account=account, gateway_server_id=pk)
            )
        except (MCPServiceAccountServerAccess.DoesNotExist, ValueError):
            return HttpResponse(
                '{"error": "Server not found or not shared with this agent"}',
                content_type="application/json",
                status=404,
            )
        server = access.gateway_server
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
        )
