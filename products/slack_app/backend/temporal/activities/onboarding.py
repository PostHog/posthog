import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import PostHogSlackInboxOnboardingInputs

logger = structlog.get_logger(__name__)


@activity.defn
def run_posthog_slack_inbox_onboarding_activity(inputs: PostHogSlackInboxOnboardingInputs) -> None:
    run_posthog_slack_inbox_onboarding(inputs.team_id, inputs.integration_id)


def run_posthog_slack_inbox_onboarding(team_id: int | None, integration_id: int) -> None:
    """Create #posthog-inbox and DM the installer for a fresh Slack install. Plain function so it's
    callable outside the Temporal worker (and unit-testable without an activity environment)."""
    from products.slack_app.backend.onboarding import run_install_onboarding
    from products.slack_app.backend.services.workspace_integrations import get_integration

    if team_id is None:
        # A workflow started before the payload carried the project. Nothing else in it names the project.
        logger.warning("slack_app_inbox_onboarding_missing_team", integration_id=integration_id)
        return
    integration = get_integration(team_id, integration_id)
    if integration is None:
        logger.info("slack_app_inbox_onboarding_integration_gone", team_id=team_id, integration_id=integration_id)
        return
    run_install_onboarding(integration)
