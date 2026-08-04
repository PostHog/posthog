"""Facade re-exports for the Slack-app per-(workspace, user) settings subsystem.

Cross-product callers (e.g. Temporal activities under `posthog/temporal/`)
import from here rather than reaching into `services/`. Mirrors the layering
in `products/tasks/backend/facade/`.
"""

from products.slack_app.backend.feature_flags import SLACK_APP_HOME_FLAG
from products.slack_app.backend.services.slack_settings import (
    AIPreferences,
    resolve_ai_preferences,
    validate_ai_preferences,
)

__all__ = [
    "SLACK_APP_HOME_FLAG",
    "AIPreferences",
    "resolve_ai_preferences",
    "validate_ai_preferences",
]
