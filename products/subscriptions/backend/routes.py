from posthog.api.routing import RouterRegistry

from products.subscriptions.backend.presentation.views import PulseResearchViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"subscriptions/pulse_research", PulseResearchViewSet, "project_subscription_pulse_research", ["team_id"]
    )
