"""Callers run inside Slack's 3-second limit, so they only check the stored state and send a signal."""

import asyncio

from django.conf import settings
from django.core.cache import cache

import structlog

from products.slack_app.backend.feature_flags import is_slack_app_onboarding_enabled
from products.slack_app.backend.services.slack_settings import resolve_onboarding, update_onboarding
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

# A bulk import of members sends many team_join events at once. Each onboarding posts two messages
# right away, so starts past this rate wait, and the app keeps room for its other Slack calls.
BURST_STARTS_PER_MINUTE = 20
BURST_WINDOW_SECONDS = 60 * 60


def request_onboarding(
    integration: WorkspaceIntegration,
    slack_user_id: str,
    *,
    may_start: bool,
    spread_burst: bool = False,
    start_only: bool = False,
) -> None:
    """Start the person's onboarding, or refresh the one in progress. Only a ``may_start`` trigger can start
    one, and only for a person with no onboarding state. A ``start_only`` trigger stops once the thread exists, so
    a busy path does not wait for Temporal on each call, but a start that failed is tried again. Never raises: the
    onboarding catches up on the next trigger."""
    try:
        slack_workspace_id = integration.integration_id
        state = resolve_onboarding(slack_workspace_id, slack_user_id)
        if state is not None and (state.completed or (start_only and state.root_ts is not None)):
            return
        start_delay_seconds = 0
        # The work focus stores its outcome in the same field, so only a start or a thread says the onboarding began.
        if state is None or (state.started_at is None and state.root_ts is None):
            if not may_start or not is_slack_app_onboarding_enabled(integration):
                return
            update_onboarding(slack_workspace_id, slack_user_id, start=True)
            if spread_burst:
                start_delay_seconds = _burst_delay_seconds(slack_workspace_id)
        _signal_with_start(integration, slack_user_id, start_delay_seconds=start_delay_seconds)
    except Exception:
        logger.warning("slack_app_onboarding_dispatch_failed", slack_user_id=slack_user_id, exc_info=True)


def _burst_delay_seconds(slack_workspace_id: str) -> int:
    key = f"slack_app:onboarding:burst_starts:{slack_workspace_id}"
    try:
        position = 1 if cache.add(key, 1, BURST_WINDOW_SECONDS) else cache.incr(key)
    except ValueError:
        # The counter expired between the add and the incr, so this start opens a new window.
        position = 1
    return ((position - 1) // BURST_STARTS_PER_MINUTE) * 60


def _signal_with_start(integration: WorkspaceIntegration, slack_user_id: str, *, start_delay_seconds: int) -> None:
    # Deferred so temporalio stays off the import path of the webhook and view modules.
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy  # noqa: PLC0415

    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.slack_app_onboarding import (  # noqa: PLC0415
        SlackAppOnboardingWorkflow,
        slack_app_onboarding_workflow_id,
    )
    from products.slack_app.backend.temporal.types import SlackAppOnboardingInputs  # noqa: PLC0415

    slack_team_id = integration.integration_id
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            SlackAppOnboardingWorkflow.run,
            SlackAppOnboardingInputs(
                integration_id=integration.id,
                slack_team_id=slack_team_id,
                slack_user_id=slack_user_id,
                start_delay_seconds=start_delay_seconds,
            ),
            id=slack_app_onboarding_workflow_id(slack_team_id, slack_user_id),
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal="refresh",
        )
    )
