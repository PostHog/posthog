from posthog.api.routing import RouterRegistry

from .presentation.views import HogViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"hogs", HogViewSet, "project_hogs", ["team_id"])
