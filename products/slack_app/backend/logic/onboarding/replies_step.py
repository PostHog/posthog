from typing import Any

from products.slack_app.backend.logic.onboarding.actions import REPLIES_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.slack_app_home import UNTAGGED_FOLLOWUP_MODE_LABELS
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_settings import (
    has_chosen_untagged_followup_mode,
    set_untagged_followup_mode,
)


class RepliesInThreadsStep(OnboardingStep):
    key = OnboardingStepKey.REPLIES_IN_THREADS
    title = "Replies in threads"
    done_text = "Replies in threads set"

    def is_done(self, ctx: OnboardingContext) -> bool:
        return has_chosen_untagged_followup_mode(ctx.integration.integration_id, ctx.slack_user_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        buttons = [
            button(ctx, UNTAGGED_FOLLOWUP_MODE_LABELS[mode], f"{REPLIES_ACTION_ID}:{mode}", mode=mode)
            for mode in (UntaggedFollowupMode.AUTO, UntaggedFollowupMode.ASK, UntaggedFollowupMode.NEVER)
        ]
        return [
            section_block(
                "*Replies in threads you start*\n"
                "When someone replies in a thread you started and doesn't tag @PostHog, what should PostHog do? "
                "This applies to your own replies too."
            ),
            {"type": "actions", "elements": [*buttons, skip_button(ctx, self.key)]},
        ]

    def handles(self, action_id: str) -> bool:
        return action_id.startswith(f"{REPLIES_ACTION_ID}:")

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        mode = value.get("mode")
        if mode not in UntaggedFollowupMode.values:
            return StepClick(refresh=False)
        set_untagged_followup_mode(ctx.integration.integration_id, ctx.slack_user_id, UntaggedFollowupMode(mode))
        self.record_completed(ctx, choice=str(mode))
        return StepClick()
