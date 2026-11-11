from posthog.api.routing import RouterRegistry

from products.webmcp.backend.presentation.views import WebMCPViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"webmcp", WebMCPViewSet, "project_webmcp", ["project_id"])
