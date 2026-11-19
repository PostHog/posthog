from posthog.api.routing import RouterRegistry

from .presentation.views import InvestigationViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"investigations", InvestigationViewSet, "project_investigations", ["team_id"])
