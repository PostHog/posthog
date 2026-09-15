"""Facade re-exports for AI run default preferences.

Team-level and per-(user, project) default `(runtime, runtime_adapter, model,
reasoning_effort)` selections, applied to task runs created without an explicit
runtime selection. Presentation and other products import from here rather
than reaching the internal ``logic.services`` module.
"""

from products.tasks.backend.logic.services.ai_run_defaults import (
    ACP,
    PI,
    ResolvedAIRunConfig,
    build_ai_run_preferences_payload,
    get_team_ai_run_preferences,
    get_user_ai_run_preferences,
    resolve_ai_run_defaults,
    update_team_ai_run_preferences,
    update_user_ai_run_preferences,
    validate_ai_run_preferences,
)

__all__ = [
    "ACP",
    "PI",
    "ResolvedAIRunConfig",
    "build_ai_run_preferences_payload",
    "get_team_ai_run_preferences",
    "get_user_ai_run_preferences",
    "resolve_ai_run_defaults",
    "update_team_ai_run_preferences",
    "update_user_ai_run_preferences",
    "validate_ai_run_preferences",
]
