import pytest

from django.core.exceptions import ValidationError

from products.tasks.backend.temporal.process_task.utils import (
    RuntimeAdapter,
    get_runtime_adapter_for_model,
    validate_model_selection,
)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", RuntimeAdapter.CLAUDE),
        ("CLAUDE-SONNET-5", RuntimeAdapter.CLAUDE),
        ("gpt-5.6-sol", RuntimeAdapter.CODEX),
        ("some-model-nobody-serves", None),
        (None, None),
    ],
)
def test_get_runtime_adapter_for_model(model: str | None, expected: RuntimeAdapter | None) -> None:
    assert get_runtime_adapter_for_model(model) == expected


@pytest.mark.parametrize(
    "runtime_adapter,model,reasoning_effort",
    [
        pytest.param("claude", "claude-sonnet-5", "high", id="pair-with-supported-effort"),
        pytest.param("codex", "gpt-5.6-sol", "max", id="codex-max-effort-model"),
        pytest.param("claude", "claude-sonnet-5", None, id="pair-without-effort"),
        pytest.param(None, None, None, id="nothing-selected"),
        pytest.param("claude", "a-model-no-adapter-claims", None, id="model-outside-the-catalogue"),
    ],
)
def test_valid_selections_pass(runtime_adapter, model, reasoning_effort) -> None:
    validate_model_selection(runtime_adapter, model, reasoning_effort)


@pytest.mark.parametrize(
    "runtime_adapter,model,reasoning_effort,expected_message",
    [
        pytest.param("claude", "gpt-5.6-sol", None, "runs on runtime_adapter 'codex'", id="openai-model-under-claude"),
        pytest.param(
            "codex", "claude-sonnet-5", None, "runs on runtime_adapter 'claude'", id="anthropic-model-under-codex"
        ),
        pytest.param("bedrock", "claude-sonnet-5", None, "Unknown runtime_adapter", id="unknown-adapter"),
        pytest.param("claude", "claude-sonnet-4-6", "max", "not supported", id="effort-above-what-model-offers"),
    ],
)
def test_invalid_selections_raise(runtime_adapter, model, reasoning_effort, expected_message) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        validate_model_selection(runtime_adapter, model, reasoning_effort)
