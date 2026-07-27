from posthog.api.routing import RouterRegistry

from products.foundry.backend.presentation.views import BetViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"bets", BetViewSet, "project_bets", ["team_id"])
