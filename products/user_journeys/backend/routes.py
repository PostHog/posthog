from posthog.api.routing import RouterRegistry

from products.user_journeys.backend.presentation.deploy_views import JourneyDeployViewSet
from products.user_journeys.backend.presentation.element_paths_views import ElementPathsViewSet
from products.user_journeys.backend.presentation.run_views import JourneyRunViewSet
from products.user_journeys.backend.presentation.views import JourneyViewSet


def register_routes(routers: RouterRegistry) -> None:
    # Register before the journeys viewset, whose detail route `user_journeys/<pk>/` would otherwise
    # take `element_paths` or `deploys` as a journey id and answer 404.
    routers.projects.register(
        r"user_journeys/element_paths", ElementPathsViewSet, "project_user_journeys_element_paths", ["project_id"]
    )
    routers.projects.register(
        r"user_journeys/deploys", JourneyDeployViewSet, "project_user_journeys_deploys", ["project_id"]
    )
    journeys = routers.projects.register(r"user_journeys", JourneyViewSet, "project_user_journeys", ["project_id"])
    journeys.register(r"runs", JourneyRunViewSet, "project_user_journeys_runs", ["project_id", "journey_id"])
