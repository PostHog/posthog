from posthog.api.routing import RouterRegistry

from products.mcp_events.backend.presentation.views import MCPEventSubscriptionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"mcp_event_subscriptions", MCPEventSubscriptionViewSet, "project_mcp_event_subscriptions", ["team_id"]
    )
