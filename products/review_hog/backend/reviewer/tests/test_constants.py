from products.review_hog.backend.reviewer.constants import (
    REVIEW_INITIAL_PERMISSION_MODE,
    REVIEW_MODEL,
    REVIEW_REASONING_EFFORT,
    REVIEW_RUNTIME_ADAPTER,
)
from products.tasks.backend.facade.run_config import (
    LLMProvider,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
)


def test_review_runtime_is_a_registry_supported_combo() -> None:
    # The perspective review pins a hardcoded (adapter, model, effort). Bumping REVIEW_MODEL to a model
    # that doesn't support the pinned effort — or flipping the adapter — would make the agent server
    # reject/misroute the run, surfacing only at e2e. Lock the combo to the Tasks registry that gates it.
    assert get_reasoning_effort_error(REVIEW_RUNTIME_ADAPTER, REVIEW_MODEL, REVIEW_REASONING_EFFORT) is None
    assert get_provider_for_runtime_adapter(REVIEW_RUNTIME_ADAPTER) == LLMProvider.ANTHROPIC


def test_review_permission_mode_defaults_to_sandbox_bypass() -> None:
    # Claude sandboxes bypass permissions by default, so the review needs no explicit approval mode.
    # Pinning a mode here would only be needed for Codex, whose default "auto" stalls on MCP calls.
    assert REVIEW_INITIAL_PERMISSION_MODE is None
