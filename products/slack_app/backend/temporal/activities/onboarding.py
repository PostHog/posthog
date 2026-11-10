import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import PostHogSlackInboxOnboardingInputs

logger = structlog.get_logger(__name__)


@activity.defn
def run_posthog_slack_inbox_onboarding_activity(inputs: PostHogSlackInboxOnboardingInputs) -> None:
    run_posthog_slack_inbox_onboarding(inputs.integration_id)


def run_posthog_slack_inbox_onboarding(integration_id: int) -> None:
    """Create #posthog-inbox and DM the installer for a fresh Slack install. Plain function so it's
    callable outside the Temporal worker (and unit-testable without an activity environment)."""
    from products.slack_app.backend.onboarding import run_install_onboarding
    from products.slack_app.backend.services.workspace_integrations import get_integration_by_id

    integration = get_integration_by_id(integration_id)
    if integration is None:
        logger.info("slack_app_inbox_onboarding_integration_gone", integration_id=integration_id)
        return
    run_install_onboarding(integration)
