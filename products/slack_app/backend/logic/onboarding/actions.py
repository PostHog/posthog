import json
from typing import Any

from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey

# pinned: Slack action ids on cards that people already have in their DMs
MODEL_ACTION_ID = "slack_onboarding:model"
AUTO_MODEL_ACTION_ID = "slack_onboarding:auto_model"
# Each reply mode button needs its own id inside one actions block, so the mode is a suffix.
REPLIES_ACTION_ID = "slack_onboarding:replies"
SKIP_ACTION_ID = "slack_onboarding:skip"
CONTINUE_ACTION_ID = "slack_onboarding:continue"
AI_CONSENT_ACTION_ID = "slack_onboarding:ai_consent"
INBOX_JOIN_ACTION_ID = "slack_onboarding:inbox_join"
# Checkbox options carry the source key as their value, so the integration id rides on the block id.
SOURCES_ACTION_ID = "slack_onboarding:sources"
SOURCES_BLOCK_PREFIX = "slack_onboarding_sources"
ONBOARDING_ACTION_PREFIX = "slack_onboarding:"


def is_onboarding_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(ONBOARDING_ACTION_PREFIX)


def action_value(ctx: OnboardingContext, **fields: str) -> str:
    # The integration id lets the interactivity webhook route the click to the region that owns the install.
    return json.dumps({"integration_id": ctx.integration.id, **fields}, separators=(",", ":"))


def read_action_value(action: dict[str, Any]) -> dict[str, Any] | None:
    raw = action.get("value") or (action.get("selected_option") or {}).get("value")
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def button(ctx: OnboardingContext, label: str, action_id: str, *, primary: bool = False, **fields: str) -> dict:
    element = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": action_value(ctx, **fields),
    }
    if primary:
        element["style"] = "primary"
    return element


def skip_button(ctx: OnboardingContext, step: OnboardingStepKey) -> dict:
    return button(ctx, "Skip", SKIP_ACTION_ID, step=step)
