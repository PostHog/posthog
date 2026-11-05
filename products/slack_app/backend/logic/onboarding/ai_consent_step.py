from products.slack_app.backend.logic.onboarding.actions import AI_CONSENT_ACTION_ID, button, skip_button
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey, OnboardingStepSpec
from products.slack_app.backend.services.onboarding_checks import has_ai_approval
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_welcome_messages import AI_DATA_PROCESSING_TEXT


def _applies(ctx: OnboardingContext) -> bool:
    # Only an org admin can allow it, so other people never see a step they cannot finish.
    return ctx.is_org_admin


def _is_done(ctx: OnboardingContext) -> bool:
    return has_ai_approval(ctx.integration.team_id)


def _render(ctx: OnboardingContext) -> list[dict]:
    return [
        section_block(f"*Allow AI data processing*\n{AI_DATA_PROCESSING_TEXT}"),
        {
            "type": "actions",
            "elements": [
                button(ctx, "Allow AI data processing", AI_CONSENT_ACTION_ID, primary=True),
                skip_button(ctx, OnboardingStepKey.AI_CONSENT),
            ],
        },
    ]


AI_CONSENT_STEP = OnboardingStepSpec(
    key=OnboardingStepKey.AI_CONSENT,
    title="AI data processing",
    done_text="AI data processing allowed",
    skippable=True,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
