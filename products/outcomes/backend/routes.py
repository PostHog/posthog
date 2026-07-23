from posthog.api.routing import RouterRegistry

from products.outcomes.backend.api import OutcomeViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"outcomes", OutcomeViewSet, "project_outcomes", ["team_id"])
