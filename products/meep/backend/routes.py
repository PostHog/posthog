from posthog.api.routing import RouterRegistry

from products.meep.backend.presentation.replica import ReplicaViewSet
from products.meep.backend.presentation.views import TopicViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"meep/v1", ReplicaViewSet, "project_meep_replica", ["team_id"])
    routers.projects.register(r"meep/topics", TopicViewSet, "project_meep_topics", ["team_id"])
