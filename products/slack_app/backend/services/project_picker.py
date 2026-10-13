import json
import time
from typing import Any, Literal

from posthog.models.integration import Integration
from posthog.slack.formatting import escape_slack_mrkdwn

from products.slack_app.backend.services.integration_resolver import project_label

PROJECT_PICKER_CONTEXT_KIND = "project_picker"
PROJECT_PICKER_BLOCK_ID_PREFIX = "slack_app_project_picker"
PROJECT_PICKER_ACTION_PREFIX = "slack_app_project_picker_pick"

# Slack lays buttons out side by side, so a longer list goes in a dropdown.
MAX_PROJECT_BUTTONS = 5
# Slack rejects the whole message when a button or an option has longer text.
_CHOICE_TEXT_MAX_LENGTH = 75

PickRejection = Literal["not_the_mentioner", "not_a_candidate"]

PICKER_EXPIRED_MESSAGE = "This project picker expired. Mention me again to get a new one."
PICK_REJECTED_MESSAGE = "I couldn't use that project. Mention me again to pick another one."


def build_project_picker_context(
    *,
    event: dict[str, Any],
    event_id: str | None,
    probe: Integration,
    candidates: list[Integration],
    slack_user_id: str,
    is_ext_shared_channel: bool,
) -> dict[str, Any]:
    return {
        "kind": PROJECT_PICKER_CONTEXT_KIND,
        # The interactivity handler reads this key to decide that the click belongs to this region.
        "integration_id": probe.id,
        "candidate_integration_ids": [candidate.id for candidate in candidates],
        "slack_user_id": slack_user_id,
        "event": event,
        "event_id": event_id,
        "is_ext_shared_channel": is_ext_shared_channel,
        "created_at": int(time.time()),
    }


def _choice_text(integration: Integration) -> dict[str, Any]:
    label = project_label(integration)
    if len(label) > _CHOICE_TEXT_MAX_LENGTH:
        label = f"{label[: _CHOICE_TEXT_MAX_LENGTH - 1]}…"
    return {"type": "plain_text", "text": label}


def _choice_value(integration: Integration, slack_user_id: str) -> str:
    return json.dumps({"integration_id": integration.id, "mentioning_slack_user_id": slack_user_id})


def build_project_picker_blocks(
    candidates: list[Integration],
    *,
    context_token: str,
    slack_user_id: str,
    home_tab_url: str | None,
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]]
    if len(candidates) <= MAX_PROJECT_BUTTONS:
        elements = [
            {
                "type": "button",
                # Slack requires a unique action id for each element in a block.
                "action_id": f"{PROJECT_PICKER_ACTION_PREFIX}:{candidate.id}",
                "text": _choice_text(candidate),
                "value": _choice_value(candidate, slack_user_id),
            }
            for candidate in candidates
        ]
    else:
        elements = [
            {
                "type": "static_select",
                "action_id": f"{PROJECT_PICKER_ACTION_PREFIX}:select",
                "placeholder": {"type": "plain_text", "text": "Choose a project"},
                "options": [
                    {"text": _choice_text(candidate), "value": _choice_value(candidate, slack_user_id)}
                    for candidate in candidates
                ],
            }
        ]
    home_tab = f"<{home_tab_url}|Home tab>" if home_tab_url else "Home tab"
    return [
        {
            "type": "section",
            "block_id": f"{PROJECT_PICKER_BLOCK_ID_PREFIX}:{context_token}",
            "text": {
                "type": "mrkdwn",
                "text": "This Slack workspace is connected to more than one PostHog project. Which one should I use?",
            },
        },
        {
            "type": "actions",
            "block_id": f"{PROJECT_PICKER_BLOCK_ID_PREFIX}_actions:{context_token}",
            "elements": elements,
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "Only you can see this. I'll use your choice for your future mentions too. "
                        f"You can change it on the {home_tab}."
                    ),
                }
            ],
        },
    ]


def is_project_picker_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(f"{PROJECT_PICKER_ACTION_PREFIX}:")


def picked_integration_id(payload: dict[str, Any]) -> int | None:
    for action in payload.get("actions", []):
        if not is_project_picker_action(action.get("action_id")):
            continue
        raw_value = action.get("value") or (action.get("selected_option") or {}).get("value", "")
        try:
            integration_id = json.loads(raw_value).get("integration_id")
        except (json.JSONDecodeError, AttributeError, TypeError):
            return None
        return integration_id if isinstance(integration_id, int) else None
    return None


def pick_rejection(
    context: dict[str, Any], *, clicker_slack_user_id: str, integration_id: int | None
) -> PickRejection | None:
    # Slack shows the picker to the mentioner only, but the run starts as that person, so the
    # click must come from them.
    if clicker_slack_user_id != context.get("slack_user_id"):
        return "not_the_mentioner"
    if integration_id not in (context.get("candidate_integration_ids") or []):
        return "not_a_candidate"
    return None


def project_picked_message(integration: Integration, *, home_tab_url: str | None) -> str:
    home_tab = f"<{home_tab_url}|Home tab>" if home_tab_url else "Home tab"
    return (
        f"Using *{escape_slack_mrkdwn(project_label(integration))}* for this and your future mentions. "
        f"You can change it on the {home_tab}."
    )
