"""
PostHog-native OpenTelemetry conventions.

Attributes with `posthog.ai.*` prefix have highest priority in the waterfall.
"""

from typing import Any


def has_posthog_attributes(span: dict[str, Any]) -> bool:
    """Check if span uses PostHog native conventions."""
    attributes = span.get("attributes", {})
    return any(key.startswith("posthog.ai.") for key in attributes.keys())


def extract_posthog_native_attributes(span: dict[str, Any]) -> dict[str, Any]:
    """
    Extract PostHog-native attributes from span.

    PostHog-native convention uses `posthog.ai.*` prefix.
    This takes highest priority in the waterfall pattern.
    """
    attributes = span.get("attributes", {})
    result: dict[str, Any] = {}

    # Helper to get attribute with prefix
    def get_attr(key: str) -> Any:
        return attributes.get(f"posthog.ai.{key}")

    # Core identifiers
    if (model := get_attr("model")) is not None:
        result["model"] = model
    if (provider := get_attr("provider")) is not None:
        result["provider"] = provider
    if (trace_id := get_attr("trace_id")) is not None:
        result["trace_id"] = trace_id
    if (span_id := get_attr("span_id")) is not None:
        result["span_id"] = span_id
    if (parent_id := get_attr("parent_id")) is not None:
        result["parent_id"] = parent_id
    if (session_id := get_attr("session_id")) is not None:
        result["session_id"] = session_id
    if (generation_id := get_attr("generation_id")) is not None:
        result["generation_id"] = generation_id

    # Token usage
    if (input_tokens := get_attr("input_tokens")) is not None:
        result["input_tokens"] = input_tokens
    if (output_tokens := get_attr("output_tokens")) is not None:
        result["output_tokens"] = output_tokens
    if (cache_read_tokens := get_attr("cache_read_tokens")) is not None:
        result["cache_read_tokens"] = cache_read_tokens
    if (cache_write_tokens := get_attr("cache_write_tokens")) is not None:
        result["cache_write_tokens"] = cache_write_tokens

    # Cost
    if (input_cost_usd := get_attr("input_cost_usd")) is not None:
        result["input_cost_usd"] = input_cost_usd
    if (output_cost_usd := get_attr("output_cost_usd")) is not None:
        result["output_cost_usd"] = output_cost_usd
    if (total_cost_usd := get_attr("total_cost_usd")) is not None:
        result["total_cost_usd"] = total_cost_usd

    # Operation
    if (operation_name := get_attr("operation_name")) is not None:
        result["operation_name"] = operation_name

    # Content
    if (input_content := get_attr("input")) is not None:
        result["input"] = input_content
    if (output_content := get_attr("output")) is not None:
        result["output"] = output_content

    # Model parameters
    if (temperature := get_attr("temperature")) is not None:
        result["temperature"] = temperature
    if (max_tokens := get_attr("max_tokens")) is not None:
        result["max_tokens"] = max_tokens
    if (stream := get_attr("stream")) is not None:
        result["stream"] = stream

    # Error tracking
    if (is_error := get_attr("is_error")) is not None:
        result["is_error"] = is_error
    if (error_message := get_attr("error_message")) is not None:
        result["error_message"] = error_message

    return result
