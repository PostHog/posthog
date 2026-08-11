import pytest

from products.review_hog.backend.reviewer.constants import (
    CHUNKING_MODEL,
    CHUNKING_REASONING_EFFORT,
    CHUNKING_RUNTIME_ADAPTER,
    DEDUP_MODEL,
    DEDUP_REASONING_EFFORT,
    DEDUP_RUNTIME_ADAPTER,
    DEFAULT_REVIEW_ARM,
    REVIEW_EXPERIMENT_ARMS,
    REVIEW_INITIAL_PERMISSION_MODE,
    REVIEW_MODEL,
    REVIEW_REASONING_EFFORT,
    REVIEW_RUNTIME_ADAPTER,
    VALIDATION_MODEL,
    VALIDATION_REASONING_EFFORT,
    VALIDATION_RUNTIME_ADAPTER,
    ReviewArm,
    draw_review_arm,
    resolve_review_arm,
)
from products.tasks.backend.facade.run_config import (
    LLMProvider,
    ReasoningEffort,
    RuntimeAdapter,
    get_models_for_runtime_adapter,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
)


def test_review_runtime_is_a_registry_supported_combo() -> None:
    # The perspective review pins a hardcoded (adapter, model, effort). Bumping REVIEW_MODEL to a model
    # that doesn't support the pinned effort — or flipping the adapter — would make the agent server
    # reject/misroute the run, surfacing only at e2e. Lock the combo to the Tasks registry that gates it.
    assert get_reasoning_effort_error(REVIEW_RUNTIME_ADAPTER, REVIEW_MODEL, REVIEW_REASONING_EFFORT) is None
    assert get_provider_for_runtime_adapter(REVIEW_RUNTIME_ADAPTER) == LLMProvider.ANTHROPIC


def test_validation_runtime_is_a_registry_supported_combo_when_pinned() -> None:
    # Same lock as the review combo, for the validation-session pins. An unsupported combo here
    # hard-errors the agent server only AFTER the whole review stage has been paid for. All-None
    # (agent default) is a valid configuration and asserts nothing.
    if VALIDATION_MODEL is None:
        assert VALIDATION_REASONING_EFFORT is None
        return
    assert get_reasoning_effort_error(VALIDATION_RUNTIME_ADAPTER, VALIDATION_MODEL, VALIDATION_REASONING_EFFORT) is None


@pytest.mark.parametrize(
    "adapter,model,effort",
    [
        pytest.param(CHUNKING_RUNTIME_ADAPTER, CHUNKING_MODEL, CHUNKING_REASONING_EFFORT, id="chunking"),
        pytest.param(DEDUP_RUNTIME_ADAPTER, DEDUP_MODEL, DEDUP_REASONING_EFFORT, id="dedup"),
    ],
)
def test_sandbox_fallback_runtime_is_a_registry_supported_combo(
    adapter: RuntimeAdapter, model: str, effort: ReasoningEffort
) -> None:
    # Same lock as the review combo, for the chunking/dedup sandbox-fallback pins. A bad combo only
    # surfaces over the one-shot gate — the rarely-exercised path — after the stage spend before it.
    assert get_reasoning_effort_error(adapter, model, effort) is None
    assert get_provider_for_runtime_adapter(adapter) == LLMProvider.ANTHROPIC


def test_review_permission_mode_defaults_to_sandbox_bypass() -> None:
    # Claude sandboxes bypass permissions by default, so the review needs no explicit approval mode.
    # Pinning a mode here would only be needed for Codex, whose default "auto" stalls on MCP calls.
    assert REVIEW_INITIAL_PERMISSION_MODE is None


@pytest.mark.parametrize("arm", [pytest.param(arm, id=arm.model) for _, arm in REVIEW_EXPERIMENT_ARMS])
def test_experiment_arm_is_a_registry_supported_combo(arm: ReviewArm) -> None:
    # Same lock as the pinned combos, per experiment arm: a bad combo is drawn onto half the fleet's
    # reports and fails only mid-review in prod. A Codex arm without "full-access" stalls every
    # headless unit on MCP approval — the exact failure the bundle exists to prevent. Membership is
    # asserted because resolve_review_arm enforces it: an off-list arm would be drawn, persisted,
    # and then silently resolved back to the default pins on every unit.
    assert arm.model in get_models_for_runtime_adapter(arm.runtime_adapter)
    assert get_reasoning_effort_error(arm.runtime_adapter, arm.model, arm.reasoning_effort) is None
    if arm.runtime_adapter == RuntimeAdapter.CODEX:
        assert arm.initial_permission_mode == "full-access"


def test_draw_review_arm_draws_from_the_arm_list() -> None:
    # random.choices accepts a zero weight without complaint, so a typo'd weight would silently
    # starve one arm for weeks while the experiment collects nothing on it. The membership check
    # also locks the (weight, arm) tuple orientation the draw's unpacking depends on.
    assert all(weight > 0 for weight, _ in REVIEW_EXPERIMENT_ARMS)
    assert draw_review_arm() in {arm for _, arm in REVIEW_EXPERIMENT_ARMS}


_SOL_ARM = next(arm for _, arm in REVIEW_EXPERIMENT_ARMS if arm.runtime_adapter == RuntimeAdapter.CODEX)


@pytest.mark.parametrize(
    "persisted,expected",
    [
        # Pre-experiment rows carry NULLs and must run the default pins.
        pytest.param((None, None, None, None), DEFAULT_REVIEW_ARM, id="null-bundle"),
        # A persisted assignment is honored verbatim.
        pytest.param(("codex", "gpt-5.6-sol", "xhigh", "full-access"), _SOL_ARM, id="persisted-codex-arm"),
        # A model that outlived its registration must degrade to the default reviewer, not send an
        # unroutable pin into a paid sandbox turn. Pinned at "high" deliberately: the Codex effort
        # registry accepts any unknown model at <=high, so only the membership check catches this.
        pytest.param(("codex", "gpt-9-vanished", "high", "full-access"), DEFAULT_REVIEW_ARM, id="stale-model"),
        pytest.param(("warp", "gpt-5.6-sol", "xhigh", None), DEFAULT_REVIEW_ARM, id="unknown-adapter"),
        # A Codex assignment without "full-access" stalls every headless unit on MCP approval, so it
        # must fall back rather than reach a sandbox turn.
        pytest.param(("codex", "gpt-5.6-sol", "xhigh", None), DEFAULT_REVIEW_ARM, id="codex-without-full-access"),
    ],
)
def test_resolve_review_arm_honors_valid_assignments_and_falls_back(
    persisted: tuple[str | None, str | None, str | None, str | None], expected: ReviewArm
) -> None:
    assert resolve_review_arm(*persisted) == expected
