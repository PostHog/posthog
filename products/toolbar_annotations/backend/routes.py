from posthog.api.routing import RouterRegistry

from products.toolbar_annotations.backend.api import ToolbarAnnotationViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"toolbar_annotations", ToolbarAnnotationViewSet, "environment_toolbar_annotations", ["team_id"]
    )
