"""Request-shape fixes shared by every backend that speaks the Anthropic Messages format."""

from __future__ import annotations

from typing import Any, Final

from litellm.litellm_core_utils.reasoning_effort_utils import reasoning_effort_from_thinking_budget

from llm_gateway.metrics.prometheus import CLEAR_THINKING_EDIT_DROPPED

CLEAR_THINKING_EDIT: Final[str] = "clear_thinking_20251015"
OPUS_5_REQUIRED_THINKING_EFFORTS: Final[frozenset[str]] = frozenset({"xhigh", "max"})


def enable_required_opus_5_thinking(request_data: dict[str, Any]) -> dict[str, Any]:
    output_config = request_data.get("output_config")
    effort = output_config.get("effort") if isinstance(output_config, dict) else None
    thinking = request_data.get("thinking")

    if (
        request_data.get("model") != "claude-opus-5"
        or effort not in OPUS_5_REQUIRED_THINKING_EFFORTS
        or not isinstance(thinking, dict)
        or thinking.get("type") != "disabled"
    ):
        return request_data

    return {**request_data, "thinking": {"type": "adaptive"}}


def convert_enabled_thinking_to_adaptive(request_data: dict[str, Any]) -> dict[str, Any]:
    """Swap enabled thinking for adaptive so litellm keeps the request on chat/completions.

    litellm's Anthropic->chat/completions adapter reroutes provider="openai" requests carrying
    `thinking: {"type": "enabled"}` through OpenAI's native Responses API by prefixing the model
    with "responses/". Our OpenAI-compatible backends (Cloudflare, Modal, Baseten) only serve
    chat/completions, and the prefixed model id fails litellm's provider lookup with a 400
    ("LLM Provider NOT provided"). Adaptive thinking translates to `reasoning_effort` without the
    reroute; the budget maps to `output_config.effort` with litellm's own thresholds, so the
    request carries the same effort the enabled-thinking translation would have produced.
    """
    thinking = request_data.get("thinking")
    if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
        return request_data

    normalized = {**request_data, "thinking": {"type": "adaptive"}}
    output_config = normalized.get("output_config")
    output_config = dict(output_config) if isinstance(output_config, dict) else {}
    if not output_config.get("effort"):
        budget = thinking.get("budget_tokens")
        output_config["effort"] = reasoning_effort_from_thinking_budget(budget if isinstance(budget, int) else 0)
        normalized["output_config"] = output_config
    return normalized


def drop_orphaned_clear_thinking(request_data: dict[str, Any], *, product: str) -> dict[str, Any]:
    """Strip a `clear_thinking_20251015` edit the request can't legally carry.

    Anthropic 400s the pair ("strategy requires `thinking` to be enabled or adaptive"), so dropping
    the edit costs a context-management optimization while keeping it costs the whole turn.
    """
    thinking = request_data.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") in {"enabled", "adaptive"}:
        return request_data

    context_management = request_data.get("context_management")
    if not isinstance(context_management, dict):
        return request_data
    edits = context_management.get("edits")
    if not isinstance(edits, list):
        return request_data

    kept = [edit for edit in edits if not (isinstance(edit, dict) and edit.get("type") == CLEAR_THINKING_EDIT)]
    if len(kept) == len(edits):
        return request_data

    CLEAR_THINKING_EDIT_DROPPED.labels(product=product).inc()
    normalized = dict(request_data)
    if kept:
        normalized["context_management"] = {**context_management, "edits": kept}
    else:
        normalized.pop("context_management", None)
    return normalized
