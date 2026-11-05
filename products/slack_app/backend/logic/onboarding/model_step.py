from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.logic.onboarding.actions import (
    AUTO_MODEL_ACTION_ID,
    MODEL_ACTION_ID,
    action_value,
    skip_button,
)
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, OnboardingStepKey, OnboardingStepSpec
from products.slack_app.backend.services.model_catalogue import offered_model_choices
from products.slack_app.backend.services.slack_app_home import has_personal_model
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_settings import resolve_auto_model_choice

# Slack refuses a static_select with more options than this.
SLACK_SELECT_MAX_OPTIONS = 100


def _applies(ctx: OnboardingContext) -> bool:
    # The model is saved for the linked PostHog user, so the step needs an install that can link.
    return is_slack_app_oauth_enabled(ctx.integration)


def _is_done(ctx: OnboardingContext) -> bool:
    return resolve_auto_model_choice(ctx.integration.integration_id, ctx.slack_user_id) or has_personal_model(
        ctx.integration, ctx.slack_user_id
    )


def _render(ctx: OnboardingContext) -> list[dict]:
    options = [
        {
            "text": {"type": "plain_text", "text": choice.label[:75]},
            "value": action_value(ctx, model=choice.model),
        }
        for choice in offered_model_choices()[:SLACK_SELECT_MAX_OPTIONS]
    ]
    elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Let PostHog choose"},
            "style": "primary",
            "action_id": AUTO_MODEL_ACTION_ID,
            "value": action_value(ctx),
        }
    ]
    if options:
        elements.append(
            {
                "type": "static_select",
                "placeholder": {"type": "plain_text", "text": "Pick a model"},
                "action_id": MODEL_ACTION_ID,
                "options": options,
            }
        )
    elements.append(skip_button(ctx, OnboardingStepKey.MODEL))
    return [
        section_block(
            "*Choose your model*\n"
            "PostHog can pick the model for each task you start, or you can pick one model for all of them. "
            "You can change this later in the Home tab."
        ),
        {"type": "actions", "elements": elements},
    ]


MODEL_STEP = OnboardingStepSpec(
    key=OnboardingStepKey.MODEL,
    title="Your model",
    done_text="Model chosen",
    skippable=True,
    applies=_applies,
    is_done=_is_done,
    render=_render,
)
