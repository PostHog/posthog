"""The modal behind "Fork to channel", where the clicker picks the destination channel."""

import json
from typing import Any

FORK_CHANNEL_MODAL_CALLBACK_ID = "slack_app_fork_channel_modal"
_CHANNEL_BLOCK_ID = "fork_channel"
_CHANNEL_ACTION_ID = "fork_channel_select"


def channel_picker_view(private_metadata: str) -> dict[str, Any]:
    return {
        "type": "modal",
        "callback_id": FORK_CHANNEL_MODAL_CALLBACK_ID,
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Fork to channel"},
        "submit": {"type": "plain_text", "text": "Fork"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": _CHANNEL_BLOCK_ID,
                "label": {"type": "plain_text", "text": "Channel"},
                "hint": {
                    "type": "plain_text",
                    "text": "PostHog starts a new thread there that links back to this one, and continues the work.",
                },
                "element": {
                    "type": "conversations_select",
                    "action_id": _CHANNEL_ACTION_ID,
                    "placeholder": {"type": "plain_text", "text": "Choose a public channel"},
                    # A private thread must not move into a wider audience, and a Slack Connect
                    # channel would show the forked work to people outside the workspace.
                    "filter": {
                        "include": ["public"],
                        "exclude_external_shared_channels": True,
                        "exclude_bot_users": True,
                    },
                },
            }
        ],
    }


def channel_picker_metadata(payload: dict) -> dict[str, Any]:
    """The source thread and integration the picker carries in ``private_metadata``, or empty for another view."""
    view = payload.get("view")
    if not isinstance(view, dict) or view.get("callback_id") != FORK_CHANNEL_MODAL_CALLBACK_ID:
        return {}
    try:
        metadata = json.loads(view.get("private_metadata") or "{}")
    except (TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def picked_channel(payload: dict) -> str | None:
    return (
        payload.get("view", {})
        .get("state", {})
        .get("values", {})
        .get(_CHANNEL_BLOCK_ID, {})
        .get(_CHANNEL_ACTION_ID, {})
        .get("selected_conversation")
    )
