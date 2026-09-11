from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.api import MetricsViewSet
from products.metrics.backend.presentation.prometheus_api import PrometheusMetricsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"metrics", MetricsViewSet, "project_metrics", ["team_id"])
    routers.projects.register(
        r"metrics/prometheus", PrometheusMetricsViewSet, "project_metrics_prometheus", ["team_id"]
    )
