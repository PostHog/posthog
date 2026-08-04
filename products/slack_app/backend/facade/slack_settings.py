"""Facade re-exports for the Slack-app per-(workspace, user) settings subsystem.

Cross-product callers (e.g. Temporal activities under `posthog/temporal/`)
import from here rather than reaching into `services/`. Mirrors the layering
in `products/tasks/backend/facade/`.
"""

from products.slack_app.backend.feature_flags import SLACK_APP_HOME_FLAG, is_slack_app_model_classifier_enabled
from products.slack_app.backend.services.model_catalogue import ModelChoice, available_model_choices
from products.slack_app.backend.services.run_preferences import (
    describe_run_model,
    find_model_choice,
    mentions_model_choice,
    resolve_run_preferences,
)
from products.slack_app.backend.services.slack_settings import (
    AIPreferences,
    resolve_ai_preferences,
    validate_ai_preferences,
)

__all__ = [
    "SLACK_APP_HOME_FLAG",
    "AIPreferences",
    "ModelChoice",
    "available_model_choices",
    "describe_run_model",
    "find_model_choice",
    "is_slack_app_model_classifier_enabled",
    "mentions_model_choice",
    "resolve_ai_preferences",
    "resolve_run_preferences",
    "validate_ai_preferences",
]
