"""Facade re-exports for resolving which model a Slack-triggered run uses.

Cross-product callers (the Temporal activities under `posthog/temporal/`) import from
here rather than reaching into `services/`. Kept separate from `facade/slack_settings.py`
because that one is about stored per-(workspace, user) settings, while this is about the
catalogue those settings pick from and the precedence that resolves them for one run.
"""

from products.slack_app.backend.services.model_catalogue import (
    ModelChoice,
    available_model_choices,
    describe_run_model,
    group_by_runtime,
)
from products.slack_app.backend.services.run_preferences import (
    SLACK_DEFAULT_MODEL,
    LiveRunModelChange,
    find_model_choice,
    resolve_live_run_override,
    resolve_run_preferences,
)

__all__ = [
    "SLACK_DEFAULT_MODEL",
    "LiveRunModelChange",
    "ModelChoice",
    "available_model_choices",
    "describe_run_model",
    "find_model_choice",
    "group_by_runtime",
    "resolve_live_run_override",
    "resolve_run_preferences",
]
