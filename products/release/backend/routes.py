from posthog.api.routing import RouterRegistry

from products.release.backend.presentation.views import ReleaseViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"releases", ReleaseViewSet, "project_releases", ["project_id"])
