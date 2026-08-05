"""Facade re-exports for resolving which model a Slack-triggered run uses.

Cross-product callers (the Temporal activities under `posthog/temporal/`) import from
here rather than reaching into `services/`. Kept separate from `facade/slack_settings.py`
because that one is about stored per-(workspace, user) settings, while this is about the
catalogue those settings pick from and the precedence that resolves them for one run.
"""

from products.slack_app.backend.feature_flags import is_slack_app_model_classifier_enabled
from products.slack_app.backend.services.model_catalogue import ModelChoice, available_model_choices
from products.slack_app.backend.services.run_preferences import find_model_choice, resolve_run_preferences

__all__ = [
    "ModelChoice",
    "available_model_choices",
    "find_model_choice",
    "is_slack_app_model_classifier_enabled",
    "resolve_run_preferences",
]
