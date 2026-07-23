from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.api import MetricsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"metrics", MetricsViewSet, "project_metrics", ["team_id"])
