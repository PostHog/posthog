from products.review_hog.backend.reviewer.constants import (
    REVIEW_INITIAL_PERMISSION_MODE,
    REVIEW_MODEL,
    REVIEW_REASONING_EFFORT,
    REVIEW_RUNTIME_ADAPTER,
)
from products.tasks.backend.facade.run_config import (
    CODEX_INITIAL_PERMISSION_MODE_CHOICES,
    LLMProvider,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
)


def test_review_runtime_is_a_registry_supported_codex_combo() -> None:
    # The perspective review pins a hardcoded (adapter, model, effort). Bumping REVIEW_MODEL to a Codex
    # model that caps at `high` — or flipping the effort — would make the agent server reject/misroute
    # the run, surfacing only at e2e. Lock the combo to the Tasks registry that actually gates it.
    assert get_reasoning_effort_error(REVIEW_RUNTIME_ADAPTER, REVIEW_MODEL, REVIEW_REASONING_EFFORT) is None
    assert get_provider_for_runtime_adapter(REVIEW_RUNTIME_ADAPTER) == LLMProvider.OPENAI


def test_review_permission_mode_is_a_valid_codex_mode() -> None:
    # A typo here (e.g. "full_access") wouldn't error — it would silently fall back to a prompting mode,
    # and every fresh headless review sandbox would stall on an MCP approval prompt again.
    assert REVIEW_INITIAL_PERMISSION_MODE in CODEX_INITIAL_PERMISSION_MODE_CHOICES
