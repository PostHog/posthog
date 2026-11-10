import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs

logger = structlog.get_logger(__name__)


@activity.defn
def find_slack_app_work_focus_activity(inputs: SlackAppWorkFocusInputs) -> str:
    from products.slack_app.backend.logic.onboarding.work_focus import find_and_send_work_focus
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        logger.info("slack_app_work_focus_integration_gone", integration_id=inputs.integration_id)
        return "integration_gone"
    return find_and_send_work_focus(integration, inputs.slack_user_id)
