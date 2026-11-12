from datetime import UTC, datetime

import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import SlackAppWorkFocusInputs

logger = structlog.get_logger(__name__)


@activity.defn
def find_slack_app_work_focus_activity(inputs: SlackAppWorkFocusInputs) -> str:
    from products.slack_app.backend.logic.daily_focus import stop_daily_focus_without_installation
    from products.slack_app.backend.logic.onboarding.work_focus import (
        find_and_send_daily_focus,
        find_and_send_work_focus,
    )
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None:
        logger.info("slack_app_work_focus_integration_gone", integration_id=inputs.integration_id)
        if inputs.since is not None:
            stop_daily_focus_without_installation(inputs.slack_team_id, inputs.slack_user_id, inputs.integration_id)
        return "integration_gone"
    if inputs.since is not None:
        # A daily run queued before runs carried their claimed time cannot bind its send claim, so it sends nothing.
        if inputs.run_at is None:
            return "superseded"
        return find_and_send_daily_focus(
            integration,
            inputs.slack_user_id,
            since=datetime.fromtimestamp(inputs.since, tz=UTC),
            run_at=datetime.fromtimestamp(inputs.run_at, tz=UTC),
        )
    return find_and_send_work_focus(integration, inputs.slack_user_id)


@activity.defn
def claim_due_slack_app_daily_focus_activity() -> list[SlackAppWorkFocusInputs]:
    from django.utils import timezone

    from products.slack_app.backend.logic.daily_focus import claim_due_daily_focus
    from products.slack_app.backend.logic.onboarding.work_focus import DAILY_RUN_SPACING_SECONDS

    return [
        SlackAppWorkFocusInputs(
            integration_id=due.integration_id,
            slack_team_id=due.slack_team_id,
            slack_user_id=due.slack_user_id,
            since=due.since,
            run_at=due.run_at,
            start_delay_seconds=due.start_delay_seconds,
        )
        for due in claim_due_daily_focus(timezone.now(), spacing_seconds=DAILY_RUN_SPACING_SECONDS)
    ]
