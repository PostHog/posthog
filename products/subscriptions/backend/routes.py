from posthog.api.routing import RouterRegistry

from products.subscriptions.backend.presentation.views import (
    PulseConfigurationOptionsViewSet,
    PulseExperimentDraftViewSet,
    PulseHistoryViewSet,
    PulseOutcomeReplayViewSet,
    PulsePublicResearchViewSet,
    PulseRunActionViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"subscriptions/pulse/configuration-options",
        PulseConfigurationOptionsViewSet,
        "project_subscription_pulse_configuration_options",
        ["team_id"],
    )
    routers.projects.register(
        r"subscriptions/pulse/history", PulseHistoryViewSet, "project_subscription_pulse_history", ["team_id"]
    )
    routers.projects.register(
        r"subscriptions/pulse/actions", PulseRunActionViewSet, "project_subscription_pulse_actions", ["team_id"]
    )
    routers.projects.register(
        r"subscriptions/pulse/experiment-drafts",
        PulseExperimentDraftViewSet,
        "project_subscription_pulse_experiment_drafts",
        ["team_id"],
    )
    routers.projects.register(
        r"subscriptions/pulse/public-research",
        PulsePublicResearchViewSet,
        "project_subscription_pulse_public_research",
        ["team_id"],
    )
    routers.projects.register(
        r"subscriptions/pulse/outcome-replays",
        PulseOutcomeReplayViewSet,
        "project_subscription_pulse_outcome_replays",
        ["team_id"],
    )
