from products.slack_app.backend.logic.onboarding.actions import (
    CONTINUE_ACTION_ID,
    SOURCES_ACTION_ID,
    SOURCES_BLOCK_PREFIX,
    button,
    skip_button,
)
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey, OnboardingStepSpec
from products.slack_app.backend.services.onboarding_checks import has_enabled_source
from products.slack_app.backend.services.slack_welcome_messages import sources_blocks


def _applies(ctx: OnboardingContext) -> bool:
    # Turning sources on is recorded for a PostHog user, so it needs the linked account.
    return ctx.is_workspace_admin and ctx.posthog_user is not None


def _is_done(ctx: OnboardingContext) -> bool:
    return has_enabled_source(ctx.integration.team_id)


def _render(ctx: OnboardingContext) -> list[dict]:
    return [
        *sources_blocks(
            ctx.integration,
            title="*Choose what I watch*\nTick the signals I should monitor and investigate. Press Continue when you're done.",
            action_id=SOURCES_ACTION_ID,
            block_id=f"{SOURCES_BLOCK_PREFIX}:{ctx.integration.id}",
        ),
        {
            "type": "actions",
            "elements": [
                button(ctx, "Continue", CONTINUE_ACTION_ID, primary=True),
                skip_button(ctx, OnboardingStepKey.SOURCES),
            ],
        },
    ]


SOURCES_STEP = OnboardingStepSpec(
    key=OnboardingStepKey.SOURCES,
    title="Signals to watch",
    done_text="Watching your signals",
    skippable=True,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
