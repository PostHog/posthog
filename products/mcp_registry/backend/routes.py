from posthog.api.routing import RouterRegistry

import products.mcp_registry.backend.presentation.views as mcp_registry


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"mcp_registry/servers",
        mcp_registry.MCPRegistryServerViewSet,
        "project_mcp_registry_servers",
        ["team_id"],
    )
