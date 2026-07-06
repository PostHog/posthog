"""
Facade re-exports for task-run configuration value types.

These are the framework-free enums, constants, and pure parse/validation helpers that
describe how a run is configured (runtime adapter, provider, authorship mode, run source,
permission mode, reasoning effort). Presentation imports them from here for serializer field
choices and request validation rather than reaching the internal ``constants`` /
``temporal.process_task.utils`` modules. ORM-touching helpers (github-integration resolution,
token caching, pr-authorship inference off a Task) are deliberately NOT exposed — those are
absorbed into the run-lifecycle facade functions in ``api.py``.
"""

from products.tasks.backend.constants import (
    ALL_INITIAL_PERMISSION_MODE_CHOICES,
    CODEX_INITIAL_PERMISSION_MODE_CHOICES,
    INITIAL_PERMISSION_MODE_CHOICES,
    InitialPermissionMode,
)
from products.tasks.backend.temporal.process_task.utils import (
    PUBLIC_REASONING_EFFORTS,
    GitHubCredentialSource,
    LLMProvider,
    PrAuthorshipMode,
    RunSource,
    RunState,
    RuntimeAdapter,
    get_models_for_runtime_adapter,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
    get_supported_reasoning_efforts,
    parse_run_state,
)

__all__ = [
    "ALL_INITIAL_PERMISSION_MODE_CHOICES",
    "CODEX_INITIAL_PERMISSION_MODE_CHOICES",
    "INITIAL_PERMISSION_MODE_CHOICES",
    "InitialPermissionMode",
    "PUBLIC_REASONING_EFFORTS",
    "GitHubCredentialSource",
    "LLMProvider",
    "PrAuthorshipMode",
    "RunSource",
    "RunState",
    "RuntimeAdapter",
    "get_models_for_runtime_adapter",
    "get_provider_for_runtime_adapter",
    "get_reasoning_effort_error",
    "get_supported_reasoning_efforts",
    "parse_run_state",
]
