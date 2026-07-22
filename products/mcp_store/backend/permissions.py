from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.scopes import MCP_BUILT_IN_AGENT_SCOPE


def is_mcp_built_in_agent_oauth_request(request: Request) -> bool:
    authenticator = request.successful_authenticator
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return False
    return MCP_BUILT_IN_AGENT_SCOPE in authenticator.access_token.scope.split()


class DenyMCPBuiltInAgentOAuth(BasePermission):
    message = "Built-in agents must use their explicitly granted MCP gateway connections."

    def has_permission(self, request: Request, view: Any) -> bool:
        return not is_mcp_built_in_agent_oauth_request(request)
