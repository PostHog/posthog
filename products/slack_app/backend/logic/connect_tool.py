"""Offers a connect link when a request names a tool the team turned on that the person has not connected.

The mention workflow waits for the connection, or for "Continue without it", before it starts the task. The task
mounts its MCP servers when its sandbox starts, so a tool connected during the wait is in the task.
"""

import re
import json
import asyncio
from typing import Any
from urllib.parse import urlencode

from django.core import signing

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration
from posthog.utils import absolute_uri

from products.mcp_store.backend.facade.api import team_tools_not_connected
from products.mcp_store.backend.facade.contracts import UnconnectedTeamTool
from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_connect_tool_from_chat_enabled
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)

CONNECT_TOOL_SKIP_ACTION_ID = "slack_app_connect_tool:skip"
CONNECTED_PATH = "/complete/slack-tool-connected/"
# Login-gated, because the MCP store API answers 401 to a browser without a PostHog session.
CONNECT_PATH = "/complete/slack-tool-connect/"
# pinned: analytics event name, renaming breaks dashboards
CONNECT_OFFERED_EVENT = "slack app connect tool offered"
_STATE_SALT = "slack_app_connect_tool"
# Longer than the mention workflow waits, so a slow OAuth screen still resumes a run that waits.
_STATE_MAX_AGE_SECONDS = 60 * 60


def tools_named_in(text: str, tools: list[UnconnectedTeamTool]) -> list[UnconnectedTeamTool]:
    return [tool for tool in tools if re.search(rf"\b{re.escape(tool.name)}\b", text, flags=re.IGNORECASE)]


def offer_tool_connections(
    integration: WorkspaceIntegration,
    *,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
    text: str,
    workflow_id: str,
) -> bool:
    """Returns whether the offer went out, so the workflow knows to wait."""
    if not is_slack_app_connect_tool_from_chat_enabled(integration):
        return False
    # One tool at a time: the first connection resumes the task, and its sandbox mounts its tools when it starts.
    tool = next(
        (
            tool
            for tool in tools_named_in(text, team_tools_not_connected(integration.team_id, user_id))
            if tool.connects_with_oauth
        ),
        None,
    )
    if tool is None:
        return False
    slack = SlackIntegration(integration)
    state = signing.dumps(
        {
            "workflow_id": workflow_id,
            "slack_team_id": integration.integration_id,
            "channel": channel,
            "return_url": _thread_link(slack, channel, thread_ts),
            "team_id": integration.team_id,
            "template_id": tool.template_id,
        },
        salt=_STATE_SALT,
    )
    buttons: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": f"Connect {tool.name}"[:75]},
            "url": absolute_uri(f"{CONNECT_PATH}?{urlencode({'state': state})}"),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Continue without it"},
            "action_id": CONNECT_TOOL_SKIP_ACTION_ID,
            "value": json.dumps({"integration_id": integration.id, "workflow_id": workflow_id}, separators=(",", ":")),
        },
    ]
    text_line = (
        f"This task can use {tool.name}, but you haven't connected it yet. "
        "Connect it and I start the task with it, or continue without it."
    )
    slack.client.chat_postEphemeral(
        channel=channel,
        user=slack_user_id,
        thread_ts=thread_ts,
        text=text_line,
        blocks=[section_block(text_line), {"type": "actions", "elements": buttons}],
    )
    capture_slack_event(integration, CONNECT_OFFERED_EVENT, slack_user_id=slack_user_id, tool_count=1)
    return True


def _thread_link(slack: SlackIntegration, channel: str, thread_ts: str) -> str | None:
    try:
        permalink = slack.client.chat_getPermalink(channel=channel, message_ts=thread_ts).get("permalink")
    except SlackApiError:
        return None
    return permalink if isinstance(permalink, str) and permalink.startswith("https://") else None


def read_connected_state(state: str) -> dict[str, Any] | None:
    try:
        payload = signing.loads(state, salt=_STATE_SALT, max_age=_STATE_MAX_AGE_SECONDS)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(key), str) for key in ("workflow_id", "slack_team_id", "channel")
    ):
        return None
    return payload


def authorize_url(state_token: str, state: dict[str, Any]) -> str | None:
    """The MCP store's OAuth start for the offered tool, which returns to the connected page with the same state."""
    team_id = state.get("team_id")
    template_id = state.get("template_id")
    if not isinstance(team_id, int) or not isinstance(template_id, str):
        return None
    return_path = f"{CONNECTED_PATH}?{urlencode({'state': state_token})}"
    query = urlencode({"template_id": template_id, "return_path": return_path})
    return f"/api/projects/{team_id}/mcp_server_installations/authorize/?{query}"


def return_to_slack_url(state: dict[str, Any]) -> str:
    return_url = state.get("return_url")
    if isinstance(return_url, str) and return_url.startswith("https://") and ".slack.com/" in return_url:
        return return_url
    return f"https://slack.com/app_redirect?{urlencode({'team': state['slack_team_id'], 'channel': state['channel']})}"


def resume_mention_workflow(workflow_id: str) -> None:
    """Never raises: the workflow continues on its own when its wait times out."""
    # Deferred so temporalio stays off the import path of the webhook and view modules.
    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.slack_app.backend.temporal.slack_app_mention_processing import (  # noqa: PLC0415
        SlackAppMentionProcessingWorkflow,
    )

    try:
        handle = sync_connect().get_workflow_handle(workflow_id)
        asyncio.run(handle.signal(SlackAppMentionProcessingWorkflow.tool_connection_resolved))
    except Exception:
        logger.warning("slack_app_connect_tool_resume_failed", workflow_id=workflow_id, exc_info=True)
