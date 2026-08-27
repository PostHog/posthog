from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.api import MetricsViewSet
from products.metrics.backend.presentation.pipelines_api import MetricsPipelineViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"metrics", MetricsViewSet, "project_metrics", ["team_id"])
    routers.projects.register(r"metrics_pipelines", MetricsPipelineViewSet, "project_metrics_pipelines", ["team_id"])
