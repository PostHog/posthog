from posthog.api.routing import RouterRegistry

from products.metrics.backend.presentation.alerts_api import MetricsAlertViewSet
from products.metrics.backend.presentation.api import MetricsViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"metrics", MetricsViewSet, "project_metrics", ["team_id"])
    routers.projects.register(r"metrics/alerts", MetricsAlertViewSet, "project_metrics_alerts", ["team_id"])
