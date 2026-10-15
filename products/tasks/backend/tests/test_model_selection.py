import pytest

from django.core.exceptions import ValidationError

from products.tasks.backend import model_catalog
from products.tasks.backend.constants import get_required_model_flag
from products.tasks.backend.temporal.process_task.utils import (
    RuntimeAdapter,
    clamp_initial_permission_mode,
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
        ("gpt-6-astra", RuntimeAdapter.CODEX),
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
        pytest.param("codex", "gpt-6-astra", "max", id="gpt-6-max-effort-model"),
        pytest.param("claude", "claude-sonnet-5", None, id="pair-without-effort"),
        pytest.param(None, None, None, id="nothing-selected"),
        pytest.param("claude", "a-model-no-adapter-claims", None, id="model-outside-the-catalogue"),
        pytest.param("fx", "gpt-6-sol", None, id="fx-with-codex-model"),
        pytest.param("fx", "claude-sonnet-5", None, id="fx-with-claude-model"),
        pytest.param("fx", "a-model-no-adapter-claims", None, id="fx-with-model-outside-the-catalogue"),
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
        pytest.param("fx", "gpt-6-sol", "high", "not supported", id="fx-with-effort"),
    ],
)
def test_invalid_selections_raise(runtime_adapter, model, reasoning_effort, expected_message) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        validate_model_selection(runtime_adapter, model, reasoning_effort)


@pytest.mark.parametrize(
    "runtime_adapter,requested,expected",
    [
        pytest.param("fx", "plan", "default", id="fx-plan"),
        pytest.param("fx", "read-only", "default", id="fx-read-only"),
        pytest.param("fx", "full-access", "full-access", id="fx-full-access"),
        pytest.param("fx", "acceptEdits", "acceptEdits", id="fx-accept-edits"),
        pytest.param("fx", None, None, id="fx-unset"),
        pytest.param("claude", "full-access", "default", id="claude-codex-mode"),
        pytest.param("codex", "bypassPermissions", "auto", id="codex-claude-mode"),
    ],
)
def test_clamp_initial_permission_mode(runtime_adapter, requested, expected) -> None:
    assert clamp_initial_permission_mode(runtime_adapter, requested) == expected


@pytest.mark.parametrize(
    "model",
    [
        "zai-org/glm-5.3",
        "anthropic/zai-org/glm-5.3",
        "ANTHROPIC/ZAI-ORG/GLM-5.3",
        "deepseek-ai/deepseek-v4-flash-0731",
        "moonshotai/kimi-k3",
        "claude-opus-5",
    ],
    ids=["canonical", "provider_qualified", "mixed_case", "deepseek", "kimi", "anthropic"],
)
def test_open_weights_models_need_no_entitlement(model: str) -> None:
    # These run on the claude harness and are offered to everyone. Every resolver folds a
    # provider-qualified id onto the model it names, so a spelling that resolved to a gate
    # would reject a selection every other surface accepts.
    assert get_required_model_flag(model) is None


@pytest.mark.parametrize(
    "model",
    [
        "gated-test-model",
        "anthropic/gated-test-model",
        "ANTHROPIC/GATED-TEST-MODEL",
        "  gated-test-model  ",
    ],
    ids=["canonical", "provider_qualified", "mixed_case", "padded"],
)
def test_get_required_model_flag_resolves_a_real_gate(model: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # The test above only proves every open-weights spelling resolves to None. Without a
    # gated catalog entry, a resolver that always returned None would pass it too, leaving
    # the retained rollout mechanism untested until another model is gated. This adds one.
    gated = model_catalog.CatalogModel(
        "gated-test-model", model_catalog.CLAUDE, ("low",), access_flag="tasks-gated-test-model"
    )
    monkeypatch.setitem(model_catalog._MODEL_BY_ID, gated.id, gated)
    assert get_required_model_flag(model) == gated.access_flag


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
