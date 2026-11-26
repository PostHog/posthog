from datetime import UTC, datetime

import structlog
from temporalio import activity

from products.slack_app.backend.temporal.types import SlackAppDailySummaryIndexInputs, SlackAppWorkFocusInputs

logger = structlog.get_logger(__name__)


@activity.defn
def find_slack_app_work_focus_activity(inputs: SlackAppWorkFocusInputs) -> str:
    from products.slack_app.backend.logic.daily_focus import (
        report_daily_focus_run,
        stop_daily_focus_without_installation,
    )
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
            outcome = "superseded"
        else:
            outcome = find_and_send_daily_focus(
                integration,
                inputs.slack_user_id,
                since=datetime.fromtimestamp(inputs.since, tz=UTC),
                run_at=datetime.fromtimestamp(inputs.run_at, tz=UTC),
            )
        report_daily_focus_run(integration, inputs.slack_user_id, outcome)
        return outcome
    return find_and_send_work_focus(integration, inputs.slack_user_id)


@activity.defn
def index_slack_app_daily_summary_activity(inputs: SlackAppDailySummaryIndexInputs) -> int:
    """Reads and scores the workspace's channel roots once, before the daily runs of its people start, so no run
    reads the channels itself. Skipped unless the organization approved AI data processing and has credits, and one
    of the people gets the daily summary and can open the project, so it spends nothing on runs that send nothing."""
    from products.slack_app.backend.logic.onboarding.checks import has_ai_approval, out_of_ai_credits
    from products.slack_app.backend.logic.onboarding.daily_summary import build_workspace_index, wants_summary
    from products.slack_app.backend.logic.onboarding.step import OnboardingContext
    from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

    integration = get_workspace_integration(inputs.integration_id, inputs.slack_team_id)
    if integration is None or not has_ai_approval(integration.team_id) or out_of_ai_credits(integration.team_id):
        return 0
    recipients = [user for user in inputs.slack_user_ids if wants_summary(integration, user)]
    # The index reads the channels and spends credits under the project, so someone who can open it must be waiting.
    if not any(
        OnboardingContext(integration=integration, slack_user_id=user).has_project_access for user in recipients
    ):
        return 0
    return build_workspace_index(integration)


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
