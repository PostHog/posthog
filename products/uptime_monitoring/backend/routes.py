from posthog.api.routing import RouterRegistry

from products.uptime_monitoring.backend.presentation.views import UptimeMonitorViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"uptime_monitors", UptimeMonitorViewSet, "project_uptime_monitors", ["project_id"])
