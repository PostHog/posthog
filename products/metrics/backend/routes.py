from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.api import MetricsViewSet
from products.metrics.backend.presentation.views_api import MetricsViewViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"metrics", MetricsViewSet, "environment_metrics", ["team_id"])
    routers.projects.register(r"metrics/views", MetricsViewViewSet, "project_metrics_views", ["team_id"])
