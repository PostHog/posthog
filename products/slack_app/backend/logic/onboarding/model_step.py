from typing import Any

from django.core.exceptions import ValidationError

from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.state import record_feature_used
from products.slack_app.backend.logic.onboarding.actions import (
    AUTO_MODEL_ACTION_ID,
    MODEL_ACTION_ID,
    action_value,
    skip_button,
)
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    OnboardingStepKey,
    StepClick,
)
from products.slack_app.backend.services.model_catalogue import offered_model_choices
from products.slack_app.backend.services.slack_app_home import has_personal_model, set_personal_model
from products.slack_app.backend.services.slack_messages import section_block
from products.slack_app.backend.services.slack_settings import resolve_auto_model_choice, set_auto_model_choice

# Slack refuses a static_select with more options than this.
SLACK_SELECT_MAX_OPTIONS = 100


class ModelStep(OnboardingStep):
    key = OnboardingStepKey.MODEL
    title = "Your model"
    done_text = "Model chosen"
    action_ids = frozenset({AUTO_MODEL_ACTION_ID, MODEL_ACTION_ID})

    def applies(self, ctx: OnboardingContext) -> bool:
        # The model is saved for the linked PostHog user, so the step needs an install that can link.
        return is_slack_app_oauth_enabled(ctx.integration)

    def is_done(self, ctx: OnboardingContext) -> bool:
        return resolve_auto_model_choice(ctx.integration.integration_id, ctx.slack_user_id) or has_personal_model(
            ctx.integration, ctx.slack_user_id
        )

    def render(self, ctx: OnboardingContext) -> list[dict]:
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
        elements.append(skip_button(ctx, self.key))
        return [
            section_block(
                "*Choose your model*\n"
                "PostHog can pick the model for each task you start, or you can pick one model for all of them. "
                "You can change this later in the Home tab."
            ),
            {"type": "actions", "elements": elements},
        ]

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        slack_workspace_id = ctx.integration.integration_id
        if action_id == AUTO_MODEL_ACTION_ID:
            set_auto_model_choice(slack_workspace_id, ctx.slack_user_id, True)
            record_feature_used(slack_workspace_id, ctx.slack_user_id, SlackFeature.AUTO_MODEL_CHOICE)
            self.record_completed(ctx, choice="auto")
            return StepClick()
        model = value.get("model")
        if model not in {choice.model for choice in offered_model_choices()}:
            return StepClick(message="That model is no longer available. Pick another one.", refresh=False)
        try:
            set_personal_model(ctx.integration, ctx.slack_user_id, str(model))
        except ValidationError as error:
            return StepClick(message=error.messages[0], refresh=False)
        self.record_completed(ctx, choice="model", model=str(model))
        return StepClick()
