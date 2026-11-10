from posthog.api.routing import RouterRegistry

from .presentation.views import UICustomizationViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"ui_customization", UICustomizationViewSet, "project_ui_customization", ["team_id"])
