import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import SlackDmSetupInputs

logger = structlog.get_logger(__name__)


@activity.defn
def render_slack_dm_setup_card_activity(inputs: SlackDmSetupInputs) -> bool:
    """Returns True when the card needs no more renders, so the workflow can stop."""
    from products.slack_app.backend.logic.dm_setup.card import render_dm_setup_card
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        logger.info("slack_app_dm_setup_integration_gone", integration_id=inputs.integration_id)
        return True
    return render_dm_setup_card(integration, inputs.slack_user_id)
