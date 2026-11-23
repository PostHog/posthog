from posthog.api.routing import RouterRegistry

from products.stacks.backend.presentation.views import StackViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"stacks", StackViewSet, "project_stacks", ["project_id"])
