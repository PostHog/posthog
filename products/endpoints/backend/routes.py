from posthog.api.routing import RouterRegistry

from products.endpoints.backend.presentation.views.api import EndpointViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"endpoints", EndpointViewSet, "project_endpoints", ["team_id"])
