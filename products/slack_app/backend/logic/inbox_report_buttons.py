"""The "I'm on it" and "Copy prompt" buttons of an inbox report notification.

The facade imports this module, so it must not import the signals product or the click handlers.
"""

from __future__ import annotations

import json
from typing import Any

REPORT_CLAIM_ACTION_ID = "slack_app_claim_report"
REPORT_COPY_PROMPT_ACTION_ID = "slack_app_copy_report_prompt"
_ACTION_IDS = (REPORT_CLAIM_ACTION_ID, REPORT_COPY_PROMPT_ACTION_ID)


def _button(action_id: str, label: str, integration_id: int) -> dict[str, Any]:
    return {
        "type": "button",
        "action_id": action_id,
        "text": {"type": "plain_text", "text": label, "emoji": True},
        "value": json.dumps({"integration_id": integration_id}),
    }


def report_claim_button(integration_id: int) -> dict[str, Any]:
    return _button(REPORT_CLAIM_ACTION_ID, "I'm on it", integration_id)


def report_copy_prompt_button(integration_id: int) -> dict[str, Any]:
    return _button(REPORT_COPY_PROMPT_ACTION_ID, "Copy prompt", integration_id)


def report_action_integration_hint(payload: dict) -> int | None:
    """Integration id that a clicked button carries, used for region-ownership routing."""
    for action in payload.get("actions", []):
        if action.get("action_id") not in _ACTION_IDS:
            continue
        try:
            value = json.loads(action.get("value") or "{}")
        except json.JSONDecodeError:
            continue
        integration_id = value.get("integration_id") if isinstance(value, dict) else None
        if isinstance(integration_id, int):
            return integration_id
    return None
