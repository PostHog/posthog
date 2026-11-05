"""Ask the per-person workflow to render the DM setup card. Callers run inside Slack's 3-second limit
or a browser request, so they only check the stored state and send a signal."""

import asyncio

from django.conf import settings

import structlog

from products.slack_app.backend.feature_flags import is_slack_app_dm_setup_card_enabled
from products.slack_app.backend.services.slack_settings import resolve_dm_setup_card
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)


def request_dm_setup_card_render(integration: WorkspaceIntegration, slack_user_id: str, *, opened_dm: bool) -> None:
    """``opened_dm`` is True only for an open of the PostHog DM, the one event that may post a new card.
    A setting saved somewhere else only refreshes a card that is already there.

    Never raises: the caller already did its own work, and the card catches up on the next open of the DM.
    """
    try:
        state = resolve_dm_setup_card(integration.integration_id, slack_user_id)
        if state is not None and state.completed:
            return
        if state is None and (not opened_dm or not is_slack_app_dm_setup_card_enabled(integration)):
            return
        _signal_with_start(integration, slack_user_id)
    except Exception:
        logger.warning("slack_app_dm_setup_dispatch_failed", slack_user_id=slack_user_id, exc_info=True)


def _signal_with_start(integration: WorkspaceIntegration, slack_user_id: str) -> None:
    # Deferred so temporalio stays off the import path of the webhook and view modules.
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy  # noqa: PLC0415

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.slack_dm_setup import (  # noqa: PLC0415
        SlackDmSetupWorkflow,
        slack_dm_setup_workflow_id,
    )
    from products.slack_app.backend.temporal.types import SlackDmSetupInputs  # noqa: PLC0415

    slack_team_id = integration.integration_id
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            SlackDmSetupWorkflow.run,
            SlackDmSetupInputs(integration_id=integration.id, slack_team_id=slack_team_id, slack_user_id=slack_user_id),
            id=slack_dm_setup_workflow_id(slack_team_id, slack_user_id),
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal="refresh",
        )
    )
