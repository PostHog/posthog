from posthog.api.routing import RouterRegistry

from products.endpoints.backend.presentation.views.api import EndpointViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"endpoints", EndpointViewSet, "environment_endpoints", ["team_id"])
