"""Block Kit pieces for the setup card buttons, and the values the interactivity handler reads back."""

import json
from typing import Any

from products.slack_app.backend.logic.dm_setup.step import DmSetupContext, DmSetupStepKey

# pinned: Slack action ids on cards that people already have in their DMs
MODEL_ACTION_ID = "slack_dm_setup:model"
AUTO_MODEL_ACTION_ID = "slack_dm_setup:auto_model"
REPLIES_ACTION_ID = "slack_dm_setup:replies"
SKIP_ACTION_ID = "slack_dm_setup:skip"
# Each reply mode button needs its own id inside one actions block, so the mode is a suffix.
DM_SETUP_ACTION_PREFIX = "slack_dm_setup:"


def is_dm_setup_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(DM_SETUP_ACTION_PREFIX)


def action_value(ctx: DmSetupContext, **fields: str) -> str:
    # The integration id lets the interactivity webhook route the click to the region that owns the install.
    return json.dumps({"integration_id": ctx.integration.id, **fields}, separators=(",", ":"))


def read_action_value(action: dict[str, Any]) -> dict[str, Any] | None:
    raw = action.get("value") or (action.get("selected_option") or {}).get("value")
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def skip_button(ctx: DmSetupContext, step: DmSetupStepKey) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Skip"},
        "action_id": SKIP_ACTION_ID,
        "value": action_value(ctx, step=step),
    }
