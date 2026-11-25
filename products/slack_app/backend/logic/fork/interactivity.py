"""The webhook side of the fork menu under a reply.

Slack gives an interactivity request three seconds, so nothing here reads a thread or
posts a message. "Fork to DM" hands the click to Temporal at once. "Fork to channel"
first opens a channel picker, because a ``trigger_id`` expires within those three
seconds too, and the picker's submission is then handed to Temporal the same way.

Kept out of ``api.py`` so that module stays the interactivity/event router: it imports
the hint extractor for region ownership and the handler entrypoints.
"""

import json
import asyncio

from django.conf import settings
from django.http import HttpResponse

import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.integration import SlackIntegration
from posthog.temporal.common.client import sync_connect

from products.slack_app.backend.logic.fork.channel_picker import (
    channel_picker_metadata,
    channel_picker_view,
    picked_channel,
)
from products.slack_app.backend.logic.fork.menu import FORK_TARGET_CHANNEL, clicked_integration_id, selected_fork_target
from products.slack_app.backend.services.slack_messages import SLACK_WEBHOOK_TIMEOUT_SECONDS
from products.slack_app.backend.services.workspace_integrations import get_workspace_integration
from products.slack_app.backend.temporal.slack_app_fork import SlackAppForkThreadWorkflow
from products.slack_app.backend.temporal.types import SlackAppForkThreadInputs

logger = structlog.get_logger(__name__)


def handle_fork_menu_click(payload: dict) -> HttpResponse:
    if selected_fork_target(payload) == FORK_TARGET_CHANNEL:
        _open_channel_picker(payload)
        return HttpResponse(status=200)
    _dispatch_fork(payload, target_channel=None)
    return HttpResponse(status=200)


def handle_fork_channel_modal_submit(payload: dict) -> HttpResponse:
    """Fork into the picked channel. The empty response closes the modal.

    The picker only lists public channels that are not Slack Connect channels, so the
    destination is checked by Slack. The fork activity checks the source thread, because
    that check needs a ``conversations.info`` call.
    """
    metadata = channel_picker_metadata(payload)
    target_channel = picked_channel(payload)
    if not metadata or not target_channel:
        logger.warning("slack_app_fork_channel_submit_incomplete", has_target=bool(target_channel))
        return HttpResponse(status=200)
    # Rebuilt in the shape of the menu click, so the activity reads one payload shape for both destinations.
    fork_payload = {
        "user": payload.get("user", {}),
        "team": payload.get("team", {}),
        "channel": {"id": metadata.get("channel")},
        "message": {"ts": metadata.get("message_ts"), "thread_ts": metadata.get("thread_ts")},
        "response_url": metadata.get("response_url"),
    }
    _dispatch_fork(fork_payload, target_channel=target_channel)
    return HttpResponse(status=200)


def fork_channel_modal_integration_hint(payload: dict) -> int | None:
    """The integration id the channel picker carries, for region-ownership routing.

    A view submission carries no action, so the id rides in ``private_metadata``.
    """
    integration_id = channel_picker_metadata(payload).get("integration_id")
    return integration_id if isinstance(integration_id, int) else None


def _open_channel_picker(payload: dict) -> None:
    trigger_id = payload.get("trigger_id")
    slack_team_id = payload.get("team", {}).get("id", "")
    integration = get_workspace_integration(clicked_integration_id(payload), slack_team_id)
    message = payload.get("message", {}) or {}
    source_channel = payload.get("channel", {}).get("id")
    if not (trigger_id and integration and source_channel and message.get("ts")):
        logger.warning("slack_app_fork_channel_picker_missing_fields", has_integration=bool(integration))
        return
    private_metadata = json.dumps(
        {
            "integration_id": integration.id,
            "channel": source_channel,
            "thread_ts": message.get("thread_ts") or message.get("ts"),
            "message_ts": message.get("ts"),
            "response_url": payload.get("response_url"),
        }
    )
    try:
        client = SlackIntegration(integration).client
        client.timeout = SLACK_WEBHOOK_TIMEOUT_SECONDS
        client.views_open(trigger_id=trigger_id, view=channel_picker_view(private_metadata))
    except Exception:
        logger.warning("slack_app_fork_channel_picker_open_failed", exc_info=True)


def _dispatch_fork(payload: dict, *, target_channel: str | None) -> None:
    """Start the fork workflow.

    The id is keyed on the thread being forked, not the reply the menu hangs off, so
    forking twice from the same discussion to the same place reuses the running fork
    instead of starting a second task about it.
    """
    message = payload.get("message", {}) or {}
    team_id = payload.get("team", {}).get("id", "")
    user_id = payload.get("user", {}).get("id", "")
    source_ts = message.get("thread_ts") or message.get("ts", "")
    workflow_id = f"slack-app-fork-thread:{team_id}:{user_id}:{source_ts}"
    if target_channel:
        workflow_id = f"{workflow_id}:{target_channel}"
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SlackAppForkThreadWorkflow.run,
                SlackAppForkThreadInputs(payload=payload, target_channel=target_channel),
                id=workflow_id,
                task_queue=settings.TASKS_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception as e:
        logger.warning("slack_app_fork_submit_start_failed", workflow_id=workflow_id, error=str(e))
