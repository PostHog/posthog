from typing import Any

from products.slack_app.backend.logic.onboarding.actions import (
    CONTINUE_ACTION_ID,
    SOURCES_ACTION_ID,
    SOURCES_BLOCK_PREFIX,
    button,
    skip_button,
)
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.services.onboarding_checks import has_enabled_source
from products.slack_app.backend.services.slack_welcome_messages import sources_blocks


class SourcesStep(OnboardingStep):
    key = OnboardingStepKey.SOURCES
    title = "Signals to watch"
    done_text = "Watching your signals"
    action_ids = frozenset({SOURCES_ACTION_ID})

    def applies(self, ctx: OnboardingContext) -> bool:
        # Turning sources on is recorded for a PostHog user, so it needs the linked account.
        return ctx.is_workspace_admin and ctx.can_link

    def is_done(self, ctx: OnboardingContext) -> bool:
        return has_enabled_source(ctx.integration.team_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
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
                    button(ctx, "Continue", CONTINUE_ACTION_ID, primary=True, step=self.key),
                    skip_button(ctx, self.key),
                ],
            },
        ]

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        from products.signals.backend.facade.api import (  # noqa: PLC0415 — keeps the signals stack off the slack import path
            set_sources,
        )

        user = ctx.posthog_user
        if user is None:
            return StepClick(message="Link your PostHog account first.", refresh=False)
        set_sources(ctx.integration.team_id, user.id, value.get("selected") or [])
        return StepClick(refresh=False)
