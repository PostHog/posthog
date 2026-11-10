from typing import Any

from products.slack_app.backend.logic.onboarding.actions import CHANNEL_WELCOME_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.models import ChannelWelcomeMode
from products.slack_app.backend.services.slack_app_home import CHANNEL_WELCOME_MODE_LABELS
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_settings import has_chosen_channel_welcome_mode, set_channel_welcome_mode


class ChannelWelcomeStep(OnboardingStep):
    key = OnboardingStepKey.CHANNEL_WELCOME
    title = "Channel welcome"
    done_text = "Channel welcome set"

    def applies(self, ctx: OnboardingContext) -> bool:
        # The mode applies to the whole Slack workspace.
        return ctx.is_workspace_admin

    def is_done(self, ctx: OnboardingContext) -> bool:
        return has_chosen_channel_welcome_mode(ctx.integration.integration_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        buttons = [
            button(ctx, CHANNEL_WELCOME_MODE_LABELS[mode], f"{CHANNEL_WELCOME_ACTION_ID}:{mode}", mode=mode)
            for mode in (ChannelWelcomeMode.CHANNEL, ChannelWelcomeMode.INVITER, ChannelWelcomeMode.OFF)
        ]
        return [
            section_block(
                "*Channel welcome*\n"
                "When someone adds me to a channel, I can post a short welcome that says what I do. "
                "Where should it go? This applies to everyone in this Slack workspace."
            ),
            {"type": "actions", "elements": [*buttons, skip_button(ctx, self.key)]},
        ]

    def handles(self, action_id: str) -> bool:
        return action_id.startswith(f"{CHANNEL_WELCOME_ACTION_ID}:")

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        if not ctx.is_workspace_admin:
            return StepClick(
                message="Only Slack workspace admins or owners can change the channel welcome message.",
                refresh=False,
            )
        mode = value.get("mode")
        if mode not in ChannelWelcomeMode.values:
            return StepClick(refresh=False)
        set_channel_welcome_mode(ctx.integration.integration_id, ChannelWelcomeMode(mode))
        self.record_completed(ctx, choice=str(mode))
        return StepClick()
