from posthog.api.routing import RouterRegistry

import products.mcp_store.backend.presentation.views as mcp_store


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"mcp_store/oauth_redirect", mcp_store.MCPOAuthRedirectViewSet, "mcp_oauth_redirect")
    routers.register_legacy_dual_route(r"mcp_servers", mcp_store.MCPServerViewSet, "project_mcp_servers", ["team_id"])
    routers.register_legacy_dual_route(
        r"mcp_server_installations",
        mcp_store.MCPServerInstallationViewSet,
        "project_mcp_server_installations",
        ["team_id"],
    )
