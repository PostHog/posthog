from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.api import MetricsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"metrics", MetricsViewSet, "environment_metrics", ["team_id"])
