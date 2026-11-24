import json

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
# The mode is a suffix for the same reason as the reply modes.
CHANNEL_WELCOME_ACTION_ID = "slack_onboarding:channel_welcome"
SOURCES_ACTION_ID = "slack_onboarding:sources"
SOURCES_BLOCK_PREFIX = "slack_onboarding_sources"
# A button on the work focus DM. The api module handles it, because it starts a task.
WORK_FOCUS_TASK_ACTION_ID = "slack_onboarding:work_focus_task"
# The Start button under the request that "Do it" opens. The task only runs once the person saw the request.
WORK_FOCUS_START_ACTION_ID = "slack_onboarding:work_focus_start"
ONBOARDING_ACTION_PREFIX = "slack_onboarding:"


def is_onboarding_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(ONBOARDING_ACTION_PREFIX)


def action_value(ctx: OnboardingContext, **fields: str) -> str:
    # The integration id lets the interactivity webhook route the click to the region that owns the install.
    return json.dumps({"integration_id": ctx.integration.id, **fields}, separators=(",", ":"))


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
