from typing import Any

import pytest

from llm_gateway.anthropic_request import drop_orphaned_clear_thinking, enable_required_opus_5_thinking
from llm_gateway.metrics.prometheus import CLEAR_THINKING_EDIT_DROPPED

PRODUCT = "posthog_code"
OTHER_PRODUCT = "llm_gateway"
CLEAR_THINKING = {"type": "clear_thinking_20251015", "keep": "all"}
CLEAR_TOOL_USES = {"type": "clear_tool_uses_20250919"}


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_opus_5_high_effort_enables_adaptive_thinking(effort: str) -> None:
    request = {
        "model": "claude-opus-5",
        "output_config": {"effort": effort},
        "thinking": {"type": "disabled"},
    }

    normalized = enable_required_opus_5_thinking(request)

    assert normalized["thinking"] == {"type": "adaptive"}
    assert request["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize(
    ("model", "effort", "thinking"),
    [
        pytest.param("claude-opus-5", "high", {"type": "disabled"}, id="lower_effort"),
        pytest.param("claude-opus-4-8", "xhigh", {"type": "disabled"}, id="other_model"),
        pytest.param("claude-opus-5", "xhigh", {"type": "adaptive"}, id="already_adaptive"),
    ],
)
def test_other_thinking_configurations_are_untouched(model: str, effort: str, thinking: dict[str, str]) -> None:
    request = {"model": model, "output_config": {"effort": effort}, "thinking": thinking}

    assert enable_required_opus_5_thinking(request) is request


def _dropped_count(product: str) -> float:
    return CLEAR_THINKING_EDIT_DROPPED.labels(product=product)._value.get()


@pytest.mark.parametrize(
    ("thinking", "edits", "expected_context_management", "expected_increment"),
    [
        pytest.param(None, [CLEAR_THINKING], None, 1, id="no_thinking_drops_context_management"),
        pytest.param({"type": "disabled"}, [CLEAR_THINKING], None, 1, id="disabled_thinking_drops_context_management"),
        pytest.param(
            {"type": "disabled"},
            [CLEAR_THINKING, CLEAR_TOOL_USES],
            {"edits": [CLEAR_TOOL_USES]},
            1,
            id="other_edits_survive",
        ),
        pytest.param(
            {"type": "adaptive"},
            [CLEAR_THINKING],
            {"edits": [CLEAR_THINKING]},
            0,
            id="adaptive_thinking_keeps_the_edit",
        ),
        pytest.param(
            {"type": "enabled", "budget_tokens": 1024},
            [CLEAR_THINKING],
            {"edits": [CLEAR_THINKING]},
            0,
            id="enabled_thinking_keeps_the_edit",
        ),
        pytest.param(None, [CLEAR_TOOL_USES], {"edits": [CLEAR_TOOL_USES]}, 0, id="unrelated_edits_untouched"),
    ],
)
def test_clear_thinking_edit_is_dropped_only_without_thinking(
    thinking: dict[str, Any] | None,
    edits: list[dict[str, Any]],
    expected_context_management: dict[str, Any] | None,
    expected_increment: int,
) -> None:
    request = {
        "model": "claude-opus-4-8",
        "messages": [{"role": "user", "content": "hi"}],
        "context_management": {"edits": edits},
        **({"thinking": thinking} if thinking else {}),
    }
    before = _dropped_count(PRODUCT)
    before_other = _dropped_count(OTHER_PRODUCT)

    normalized = drop_orphaned_clear_thinking(request, product=PRODUCT)

    assert normalized.get("context_management") == expected_context_management
    assert request["context_management"] == {"edits": edits}
    # The counter is the only signal that this fired, so pin both that it ticks on a drop and that
    # it stays put otherwise — and that it lands on the caller's product, not some other series.
    assert _dropped_count(PRODUCT) == before + expected_increment
    assert _dropped_count(OTHER_PRODUCT) == before_other


@pytest.mark.parametrize(
    "context_management",
    [
        pytest.param(None, id="absent"),
        pytest.param({}, id="no_edits_key"),
        pytest.param({"edits": "not-a-list"}, id="malformed_edits"),
    ],
)
def test_request_without_edits_is_returned_untouched(context_management: Any) -> None:
    request: dict[str, Any] = {"model": "claude-opus-4-8", "messages": []}
    if context_management is not None:
        request["context_management"] = context_management

    assert drop_orphaned_clear_thinking(request, product=PRODUCT) is request
