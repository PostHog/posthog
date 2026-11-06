from typing import TYPE_CHECKING

import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import (
    ONBOARDING_DONE_PLAN,
    SlackAppOnboardingInputs,
    SlackAppOnboardingMessageInputs,
    SlackAppOnboardingPlan,
)

if TYPE_CHECKING:
    from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)


def _integration(inputs: SlackAppOnboardingInputs) -> "WorkspaceIntegration | None":
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        logger.info("slack_app_onboarding_integration_gone", integration_id=inputs.integration_id)
    return integration


@activity.defn
def plan_slack_app_onboarding_activity(inputs: SlackAppOnboardingInputs) -> SlackAppOnboardingPlan:
    from products.slack_app.backend.logic.onboarding.card import plan_onboarding

    integration = _integration(inputs)
    if integration is None:
        return ONBOARDING_DONE_PLAN
    return plan_onboarding(integration, inputs.slack_user_id)


@activity.defn
def post_slack_app_onboarding_message_activity(inputs: SlackAppOnboardingMessageInputs) -> None:
    from products.slack_app.backend.logic.onboarding.card import post_onboarding_message

    integration = _integration(inputs.setup)
    if integration is not None:
        post_onboarding_message(integration, inputs.setup.slack_user_id, inputs.message)


@activity.defn
def remind_slack_app_onboarding_activity(inputs: SlackAppOnboardingInputs) -> None:
    from products.slack_app.backend.logic.onboarding.card import remind_onboarding

    integration = _integration(inputs)
    if integration is not None:
        remind_onboarding(integration, inputs.slack_user_id)


@activity.defn
def edit_slack_app_onboarding_message_activity(inputs: SlackAppOnboardingMessageInputs) -> None:
    from products.slack_app.backend.logic.onboarding.card import edit_onboarding_message

    integration = _integration(inputs.setup)
    if integration is not None:
        edit_onboarding_message(integration, inputs.setup.slack_user_id, inputs.message)
