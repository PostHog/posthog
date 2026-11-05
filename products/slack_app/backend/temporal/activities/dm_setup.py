from typing import TYPE_CHECKING

import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import SlackDmSetupInputs, SlackDmSetupMessageInputs, SlackDmSetupPlan

if TYPE_CHECKING:
    from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

_GONE = SlackDmSetupPlan(edits=[], post=None, finished=True, plan_again=False)


def _integration(inputs: SlackDmSetupInputs) -> "WorkspaceIntegration | None":
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        logger.info("slack_app_dm_setup_integration_gone", integration_id=inputs.integration_id)
    return integration


@activity.defn
def plan_slack_dm_setup_activity(inputs: SlackDmSetupInputs) -> SlackDmSetupPlan:
    from products.slack_app.backend.logic.dm_setup.card import plan_dm_setup

    integration = _integration(inputs)
    if integration is None:
        return _GONE
    return plan_dm_setup(integration, inputs.slack_user_id)


@activity.defn
def post_slack_dm_setup_message_activity(inputs: SlackDmSetupMessageInputs) -> None:
    from products.slack_app.backend.logic.dm_setup.card import post_dm_setup_message

    integration = _integration(inputs.setup)
    if integration is not None:
        post_dm_setup_message(integration, inputs.setup.slack_user_id, inputs.message)


@activity.defn
def edit_slack_dm_setup_message_activity(inputs: SlackDmSetupMessageInputs) -> None:
    from products.slack_app.backend.logic.dm_setup.card import edit_dm_setup_message

    integration = _integration(inputs.setup)
    if integration is not None:
        edit_dm_setup_message(integration, inputs.setup.slack_user_id, inputs.message)
