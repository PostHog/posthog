from posthog.api.routing import RouterRegistry

from products.subscriptions.backend.presentation.views import ProactiveConfigurationOptionsViewSet, PulseResearchViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"subscriptions/proactive_options",
        ProactiveConfigurationOptionsViewSet,
        "project_subscription_proactive_options",
        ["team_id"],
    )
    routers.projects.register(
        r"subscriptions/pulse_research", PulseResearchViewSet, "project_subscription_pulse_research", ["team_id"]
    )
