from posthog.api.routing import RouterRegistry

from products.user_journeys.backend.presentation.element_paths_views import ElementPathsViewSet
from products.user_journeys.backend.presentation.views import JourneyViewSet


def register_routes(routers: RouterRegistry) -> None:
    # Register before the journeys viewset, whose detail route `user_journeys/<pk>/` would otherwise
    # take `element_paths` as a journey id and answer 404.
    routers.projects.register(
        r"user_journeys/element_paths", ElementPathsViewSet, "project_user_journeys_element_paths", ["project_id"]
    )
    routers.projects.register(r"user_journeys", JourneyViewSet, "project_user_journeys", ["project_id"])
