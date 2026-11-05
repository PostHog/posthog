from products.slack_app.backend.inbox_channel import has_inbox_scopes, is_in_team_inbox_channel
from products.slack_app.backend.logic.onboarding.actions import INBOX_JOIN_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey, OnboardingStepSpec
from products.slack_app.backend.services.slack_messages import section_block


def _applies(ctx: OnboardingContext) -> bool:
    return ctx.is_workspace_admin and has_inbox_scopes(ctx.integration)


def _is_done(ctx: OnboardingContext) -> bool:
    return is_in_team_inbox_channel(ctx.integration, ctx.slack_user_id)


def _render(ctx: OnboardingContext) -> list[dict]:
    return [
        section_block(
            "*Join #posthog-inbox*\nEverything I find lands in one shared channel, so the team stays in the loop."
        ),
        {
            "type": "actions",
            "elements": [
                button(ctx, "Join #posthog-inbox", INBOX_JOIN_ACTION_ID, primary=True),
                skip_button(ctx, OnboardingStepKey.INBOX_CHANNEL),
            ],
        },
    ]


INBOX_CHANNEL_STEP = OnboardingStepSpec(
    key=OnboardingStepKey.INBOX_CHANNEL,
    title="#posthog-inbox",
    done_text="You're in #posthog-inbox",
    skippable=True,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
