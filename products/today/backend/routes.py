"""Route registration for today. Auto-discovered by posthog/api/__init__.py."""

from posthog.api.routing import RouterRegistry

from .presentation.views import TodayViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"today", TodayViewSet, "project_today", ["team_id"])
