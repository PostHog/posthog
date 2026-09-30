"""Facade re-exports for resolving which model a Slack-triggered run uses.

Cross-product callers (the Temporal activities under `posthog/temporal/`) import from
here rather than reaching into `services/`: the model catalogue and the precedence
that resolves it for one run.
"""

from products.slack_app.backend.services.model_catalogue import (
    ModelChoice,
    available_model_choices,
    describe_run_model,
    group_by_runtime,
)
from products.slack_app.backend.services.run_preferences import (
    LiveRunModelChange,
    find_model_choice,
    resolve_live_run_override,
    resolve_run_preferences,
)

__all__ = [
    "LiveRunModelChange",
    "ModelChoice",
    "available_model_choices",
    "describe_run_model",
    "find_model_choice",
    "group_by_runtime",
    "resolve_live_run_override",
    "resolve_run_preferences",
]
