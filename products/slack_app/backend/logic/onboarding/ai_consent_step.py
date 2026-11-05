from typing import Any

from products.slack_app.backend.logic.onboarding.actions import (
    AI_CONSENT_ACTION_ID,
    CONTINUE_ACTION_ID,
    button,
    skip_button,
)
from products.slack_app.backend.logic.onboarding.checks import approve_ai_data_processing_for_team, has_ai_approval
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_welcome_messages import AI_DATA_PROCESSING_TEXT


class AiConsentStep(OnboardingStep):
    key = OnboardingStepKey.AI_CONSENT
    title = "AI data processing"
    done_text = "AI data processing allowed"
    action_ids = frozenset({AI_CONSENT_ACTION_ID})

    def applies(self, ctx: OnboardingContext) -> bool:
        # A Slack admin is often the one to ask an org admin for it, even when they cannot allow it.
        return ctx.is_workspace_admin or ctx.is_org_admin

    def is_done(self, ctx: OnboardingContext) -> bool:
        return has_ai_approval(ctx.integration.team_id)

    def render(self, ctx: OnboardingContext) -> list[dict]:
        if not ctx.is_org_admin:
            return [
                section_block(
                    f"*Allow AI data processing*\n{AI_DATA_PROCESSING_TEXT}\n"
                    "Only an organization admin can allow it. Ask one to allow it in PostHog, then press Continue."
                ),
                {"type": "actions", "elements": [button(ctx, "Continue", CONTINUE_ACTION_ID, step=self.key)]},
            ]
        return [
            section_block(f"*Allow AI data processing*\n{AI_DATA_PROCESSING_TEXT}"),
            {
                "type": "actions",
                "elements": [
                    button(ctx, "Allow AI data processing", AI_CONSENT_ACTION_ID, primary=True),
                    skip_button(ctx, self.key),
                ],
            },
        ]

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        if not ctx.is_org_admin:
            return StepClick(message="Only an organization admin can allow AI data processing.", refresh=False)
        approve_ai_data_processing_for_team(ctx.integration.team_id)
        self.record_completed(ctx)
        return StepClick()
