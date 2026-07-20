from posthog.api.routing import RouterRegistry

import products.mcp_store.backend.presentation.views as mcp_store
import products.mcp_store.backend.presentation.agent_views as mcp_agent
import products.mcp_store.backend.presentation.gateway_views as mcp_gateway


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"mcp_store/oauth_redirect", mcp_store.MCPOAuthRedirectViewSet, "mcp_oauth_redirect")
    # Agent-facing surface: service accounts authenticate with their gateway
    # token, so this is root-level (the token resolves the team).
    routers.root.register(r"mcp_store/gateway/servers", mcp_agent.MCPGatewayAgentViewSet, "mcp_gateway_agent_servers")
    routers.projects.register(r"mcp_servers", mcp_store.MCPServerViewSet, "project_mcp_servers", ["team_id"])
    routers.projects.register(
        r"mcp_server_installations",
        mcp_store.MCPServerInstallationViewSet,
        "project_mcp_server_installations",
        ["team_id"],
    )
    routers.projects.register(
        r"mcp_gateway/servers", mcp_gateway.MCPGatewayServerViewSet, "project_mcp_gateway_servers", ["team_id"]
    )
    routers.projects.register(
        r"mcp_gateway/service_accounts",
        mcp_gateway.MCPServiceAccountViewSet,
        "project_mcp_gateway_service_accounts",
        ["team_id"],
    )
    routers.projects.register(
        r"mcp_gateway/rules", mcp_gateway.MCPOrgRuleViewSet, "project_mcp_gateway_rules", ["team_id"]
    )
    routers.projects.register(
        r"mcp_gateway/audit", mcp_gateway.MCPAuditEventViewSet, "project_mcp_gateway_audit", ["team_id"]
    )
    routers.projects.register(
        r"mcp_gateway/config", mcp_gateway.MCPGatewayConfigViewSet, "project_mcp_gateway_config", ["team_id"]
    )
    routers.projects.register(
        r"mcp_gateway/members", mcp_gateway.MCPGatewayMemberViewSet, "project_mcp_gateway_members", ["team_id"]
    )
