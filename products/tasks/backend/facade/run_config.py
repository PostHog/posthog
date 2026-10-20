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
    REASONING_EFFORTS,
    InitialPermissionMode,
    get_required_model_flag,
)
from products.tasks.backend.facade.profiles import task_profiles
from products.tasks.backend.feature_flags import get_model_access_error

# TaskArtifact's choice enums live on the model as Django ``TextChoices``; re-exported here
# so presentation builds serializer choices without importing the ORM model directly.
from products.tasks.backend.models import (
    Task as _Task,
    TaskArtifact as _TaskArtifact,
)
from products.tasks.backend.temporal.process_task.utils import (
    CONTEXT_WINDOW_CHOICES,
    GitHubCredentialSource,
    LLMProvider,
    PrAuthorshipMode,
    ReasoningEffort,
    RunSource,
    RunState,
    RuntimeAdapter,
    get_default_model_for_runtime_adapter,
    get_models_for_runtime_adapter,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
    get_runtime_adapter_for_model,
    get_supported_reasoning_efforts,
    parse_run_state,
    runtime_adapter_serves_model,
    validate_model_selection,
)

TaskArtifactType = _TaskArtifact.ArtifactType
TaskArtifactAdapter = _TaskArtifact.Adapter
TaskArtifactStatus = _TaskArtifact.Status

_warmable_origins = {profile.origin_product for profile in task_profiles() if profile.warm is not None}
WARMABLE_ORIGIN_PRODUCTS: list[str] = [origin for origin in _Task.OriginProduct.values if origin in _warmable_origins]

__all__ = [
    "ALL_INITIAL_PERMISSION_MODE_CHOICES",
    "CODEX_INITIAL_PERMISSION_MODE_CHOICES",
    "CONTEXT_WINDOW_CHOICES",
    "INITIAL_PERMISSION_MODE_CHOICES",
    "WARMABLE_ORIGIN_PRODUCTS",
    "InitialPermissionMode",
    "REASONING_EFFORTS",
    "GitHubCredentialSource",
    "LLMProvider",
    "PrAuthorshipMode",
    "ReasoningEffort",
    "RunSource",
    "RunState",
    "RuntimeAdapter",
    "TaskArtifactAdapter",
    "TaskArtifactStatus",
    "TaskArtifactType",
    "get_default_model_for_runtime_adapter",
    "get_model_access_error",
    "get_models_for_runtime_adapter",
    "runtime_adapter_serves_model",
    "get_provider_for_runtime_adapter",
    "get_reasoning_effort_error",
    "get_required_model_flag",
    "get_runtime_adapter_for_model",
    "get_supported_reasoning_efforts",
    "parse_run_state",
    "validate_model_selection",
]
