from typing import Any

from products.slack_app.backend.inbox_channel import (
    ensure_inbox_channel,
    has_inbox_scopes,
    invite_user_to_inbox,
    is_in_team_inbox_channel,
)
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.state import record_feature_used
from products.slack_app.backend.logic.onboarding.actions import INBOX_JOIN_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.services.slack_messages import section_block


class InboxChannelStep(OnboardingStep):
    key = OnboardingStepKey.INBOX_CHANNEL
    title = "#posthog-inbox"
    done_text = "You're in #posthog-inbox"
    action_ids = frozenset({INBOX_JOIN_ACTION_ID})

    def applies(self, ctx: OnboardingContext) -> bool:
        return ctx.is_workspace_admin and has_inbox_scopes(ctx.integration)

    def is_done(self, ctx: OnboardingContext) -> bool:
        return is_in_team_inbox_channel(ctx.integration, ctx.slack_user_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        return [
            section_block(
                "*Join #posthog-inbox*\nEverything I find lands in one shared channel, so the team stays in the loop."
            ),
            {
                "type": "actions",
                "elements": [
                    button(ctx, "Join #posthog-inbox", INBOX_JOIN_ACTION_ID, primary=True),
                    skip_button(ctx, self.key),
                ],
            },
        ]

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        channel = ensure_inbox_channel(ctx.integration)
        if channel is None or not invite_user_to_inbox(ctx.integration, channel[0], ctx.slack_user_id):
            return StepClick(
                message="I couldn't add you to #posthog-inbox. Create the channel, then invite me with /invite @PostHog.",
                refresh=False,
            )
        record_feature_used(ctx.integration.integration_id, ctx.slack_user_id, SlackFeature.INBOX_CHANNEL)
        self.record_completed(ctx)
        return StepClick()
