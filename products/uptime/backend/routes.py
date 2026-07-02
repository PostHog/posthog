from posthog.api.routing import RouterRegistry

from products.uptime.backend.presentation.views import MonitorViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"uptime/monitors", MonitorViewSet, "project_uptime_monitors", ["team_id"])
