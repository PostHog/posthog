"""The fork menu under a reply, and which destination a click on it picked."""

import json
from typing import Any

FORK_THREAD_ACTION_ID = "slack_app_fork_thread"
FORK_TARGET_DM = "dm"
FORK_TARGET_CHANNEL = "channel"


def fork_menu_actions_block(element: dict[str, Any]) -> dict[str, Any]:
    """The fork menu as a standalone block, for replies with no section to hang it on.

    A streamed answer arrives as markdown chunks and the chart delivery puts the answer
    in the card message, so neither has a `section` whose accessory the menu could be.
    Costs a line, which is why the plain-post path prefers the accessory.
    """
    return {"type": "actions", "elements": [element]}


def _fork_option(label: str, integration_id: int, target: str) -> dict[str, Any]:
    return {
        "text": {"type": "plain_text", "text": label, "emoji": True},
        "value": json.dumps({"integration_id": integration_id, "target": target}),
    }


def fork_menu_element(integration_id: int) -> dict[str, Any]:
    """The overflow menu the footer carries as its accessory.

    An overflow renders as a bare "…" with no label, which is as close to invisible as
    an interactive element gets, because the answer above it is what the reader came for.
    Each destination is one more option in the same menu, so it never grows a second control.

    Returned as a bare element rather than wrapped in an `actions` block so it can be a
    `section` accessory, which is what puts it on the footer's own line. Slack offers no
    inline interactive element, so an accessory — right-aligned beside the text — is as
    close to trailing the footer as Block Kit gets.

    The option value carries the integration so the cross-region interactivity router
    can tell whose click this is. Everything else the fork needs — the channel, and the
    thread the reply is sitting in — rides on the `block_actions` payload.
    """
    return {
        "type": "overflow",
        "action_id": FORK_THREAD_ACTION_ID,
        "options": [
            _fork_option("Fork to DM", integration_id, FORK_TARGET_DM),
            _fork_option("Fork to channel", integration_id, FORK_TARGET_CHANNEL),
        ],
    }


def selected_fork_target(payload: dict[str, Any]) -> str:
    """The destination a fork menu click picked.

    A menu posted before the channel option existed carries no target, and it only ever
    offered a DM.
    """
    for action in payload.get("actions", []) or ():
        if action.get("action_id") != FORK_THREAD_ACTION_ID:
            continue
        try:
            value = json.loads((action.get("selected_option") or {}).get("value") or "{}")
        except (TypeError, ValueError):
            break
        if isinstance(value, dict) and value.get("target") == FORK_TARGET_CHANNEL:
            return FORK_TARGET_CHANNEL
        break
    return FORK_TARGET_DM


def clicked_integration_id(payload: dict[str, Any]) -> int | None:
    """The integration a fork menu click names in its option value."""
    for action in payload.get("actions", []) or ():
        if action.get("action_id") != FORK_THREAD_ACTION_ID:
            continue
        try:
            value = json.loads((action.get("selected_option") or {}).get("value") or "{}")
        except (TypeError, ValueError):
            return None
        integration_id = value.get("integration_id") if isinstance(value, dict) else None
        return integration_id if isinstance(integration_id, int) else None
    return None
