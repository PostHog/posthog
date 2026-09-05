import pytest

from django.core.exceptions import ValidationError

from products.tasks.backend.constants import get_required_model_flag
from products.tasks.backend.temporal.process_task.utils import (
    RuntimeAdapter,
    get_runtime_adapter_for_model,
    runtime_adapter_serves_model,
    validate_model_selection,
)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", RuntimeAdapter.CLAUDE),
        ("CLAUDE-SONNET-5", RuntimeAdapter.CLAUDE),
        ("gpt-5.6-sol", RuntimeAdapter.CODEX),
        # The gateway serves some models provider-qualified and a picker hands back either
        # spelling, so both resolve to the adapter the bare id does.
        ("anthropic/claude-sonnet-5", RuntimeAdapter.CLAUDE),
        ("openai/gpt-5.6-sol", RuntimeAdapter.CODEX),
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


@pytest.mark.parametrize(
    "model,expected_flag",
    [
        ("zai-org/glm-5.3", "posthog-code-glm-53-model"),
        ("anthropic/zai-org/glm-5.3", "posthog-code-glm-53-model"),
        ("ANTHROPIC/ZAI-ORG/GLM-5.3", "posthog-code-glm-53-model"),
        ("claude-opus-5", None),
    ],
    ids=["canonical", "provider_qualified", "mixed_case", "ungated"],
)
def test_gated_model_is_gated_in_every_spelling(model: str, expected_flag: str | None) -> None:
    # Every resolver folds a provider-qualified id onto the model it names, so a gate that
    # missed that spelling would skip the entitlement check on an id the rest of the stack
    # already treats as the gated one.
    assert get_required_model_flag(model) == expected_flag


@pytest.mark.parametrize(
    "adapter,model,expected",
    [
        ("codex", "gpt-5.6-sol", True),
        ("codex", "openai/gpt-5.6-sol", True),
        ("claude", "anthropic/claude-opus-5", True),
        ("codex", "claude-opus-5", False),
        ("codex", "some-model-nobody-serves", False),
        ("codex", None, False),
    ],
    ids=[
        "canonical",
        "provider_qualified",
        "provider_qualified_claude",
        "wrong_adapter",
        "unserved",
        "no_model",
    ],
)
def test_allowlist_accepts_the_spellings_the_resolvers_accept(adapter: str, model: str | None, expected: bool) -> None:
    # The loops serializer rejects anything this call rejects, so a spelling the gateway
    # serves and the pickers offer has to pass here or the save 400s.
    assert runtime_adapter_serves_model(adapter, model) is expected
