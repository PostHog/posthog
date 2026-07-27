from posthog.api.routing import RouterRegistry

from products.links.backend.api import LinkViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"links", LinkViewSet, "project_links", ["team_id"])
