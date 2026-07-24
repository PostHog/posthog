from posthog.api.routing import RouterRegistry

from products.outcomes.backend.api import OutcomeDefinitionViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"outcomes", OutcomeDefinitionViewSet, "project_outcomes", ["team_id"])
