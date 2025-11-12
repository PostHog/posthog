"""
GenAI semantic conventions for OpenTelemetry.

Implements the GenAI semantic conventions (gen_ai.*) as fallback
when PostHog-native attributes are not present.

Reference: https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

from typing import Any


def has_genai_attributes(span: dict[str, Any]) -> bool:
    """Check if span uses GenAI semantic conventions."""
    attributes = span.get("attributes", {})
    return any(key.startswith("gen_ai.") for key in attributes.keys())


def extract_genai_attributes(span: dict[str, Any]) -> dict[str, Any]:
    """
    Extract GenAI semantic convention attributes from span.

    GenAI conventions use `gen_ai.*` prefix and are fallback
    when PostHog-native attributes are not present.
    """
    attributes = span.get("attributes", {})
    result: dict[str, Any] = {}

    # Model (prefer request, fallback to response, then system)
    model = (
        attributes.get("gen_ai.request.model")
        or attributes.get("gen_ai.response.model")
        or attributes.get("gen_ai.model")
    )
    if model is not None:
        result["model"] = model

    # Provider (from gen_ai.system)
    if (system := attributes.get("gen_ai.system")) is not None:
        result["provider"] = system

    # Operation name
    if (operation_name := attributes.get("gen_ai.operation.name")) is not None:
        result["operation_name"] = operation_name

    # Token usage
    if (input_tokens := attributes.get("gen_ai.usage.input_tokens")) is not None:
        result["input_tokens"] = input_tokens
    if (output_tokens := attributes.get("gen_ai.usage.output_tokens")) is not None:
        result["output_tokens"] = output_tokens

    # Content (prompt and completion)
    if (prompt := attributes.get("gen_ai.prompt")) is not None:
        result["prompt"] = prompt
    if (completion := attributes.get("gen_ai.completion")) is not None:
        result["completion"] = completion

    # Model parameters
    if (temperature := attributes.get("gen_ai.request.temperature")) is not None:
        result["temperature"] = temperature
    if (max_tokens := attributes.get("gen_ai.request.max_tokens")) is not None:
        result["max_tokens"] = max_tokens
    if (top_p := attributes.get("gen_ai.request.top_p")) is not None:
        result["top_p"] = top_p
    if (frequency_penalty := attributes.get("gen_ai.request.frequency_penalty")) is not None:
        result["frequency_penalty"] = frequency_penalty
    if (presence_penalty := attributes.get("gen_ai.request.presence_penalty")) is not None:
        result["presence_penalty"] = presence_penalty

    # Response metadata
    if (finish_reasons := attributes.get("gen_ai.response.finish_reasons")) is not None:
        result["finish_reasons"] = finish_reasons
    if (response_id := attributes.get("gen_ai.response.id")) is not None:
        result["response_id"] = response_id

    return result
