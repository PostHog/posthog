from posthog.api.routing import RouterRegistry

from products.posthog_ai.backend.api import AIUsageViewSet, MCPToolsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"mcp_tools",
        MCPToolsViewSet,
        "project_mcp_tools",
        ["team_id"],
    )
    routers.projects.register(
        r"ai_usage",
        AIUsageViewSet,
        "project_ai_usage",
        ["team_id"],
    )
