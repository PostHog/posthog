"""
GenAI semantic conventions for OpenTelemetry.

Implements the GenAI semantic conventions (gen_ai.*) as fallback
when PostHog-native attributes are not present.

Supports provider-specific transformations for frameworks like Mastra
that use custom OTEL formats.

Reference: https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .providers.base import ProviderTransformer


def has_genai_attributes(span: dict[str, Any]) -> bool:
    """Check if span uses GenAI semantic conventions."""
    attributes = span.get("attributes", {})
    return any(key.startswith("gen_ai.") for key in attributes.keys())


def _extract_indexed_messages(attributes: dict[str, Any], prefix: str) -> list[dict[str, Any]] | None:
    """
    Extract indexed message attributes like gen_ai.prompt.{N}.{field} into a list of message dicts.

    Args:
        attributes: Span attributes dictionary
        prefix: Message prefix (e.g., "gen_ai.prompt" or "gen_ai.completion")

    Returns:
        List of message dicts with role, content, etc., or None if no messages found
    """
    # Group attributes by index
    messages_by_index: dict[int, dict[str, Any]] = defaultdict(dict)

    for key, value in attributes.items():
        if not key.startswith(f"{prefix}."):
            continue

        # Parse: gen_ai.prompt.0.role -> index=0, field=role
        parts = key[len(prefix) + 1 :].split(".", 1)
        if len(parts) != 2:
            continue

        try:
            index = int(parts[0])
            field = parts[1]
            messages_by_index[index][field] = value
        except (ValueError, IndexError):
            continue

    if not messages_by_index:
        return None

    # Convert to sorted list of messages
    messages = []
    for index in sorted(messages_by_index.keys()):
        msg = messages_by_index[index]
        if msg:  # Only include non-empty messages
            messages.append(msg)

    return messages if messages else None


def detect_provider(span: dict[str, Any], scope: dict[str, Any] | None = None) -> "ProviderTransformer | None":
    """
    Detect which provider transformer handles this span.

    Args:
        span: Parsed OTEL span
        scope: Instrumentation scope info

    Returns:
        Matching ProviderTransformer instance, or None if no provider matches
    """
    from .providers import PROVIDER_TRANSFORMERS

    scope = scope or {}
    for transformer_class in PROVIDER_TRANSFORMERS:
        transformer = transformer_class()
        if transformer.can_handle(span, scope):
            return transformer
    return None


def extract_genai_attributes(span: dict[str, Any], scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Extract GenAI semantic convention attributes from span.

    GenAI conventions use `gen_ai.*` prefix and are fallback
    when PostHog-native attributes are not present.

    Supports provider-specific transformations for frameworks that use
    custom OTEL formats (e.g., Mastra).

    Args:
        span: Parsed OTEL span
        scope: Instrumentation scope info (for provider detection)

    Returns:
        Extracted attributes dict
    """
    import structlog

    logger = structlog.get_logger(__name__)
    attributes = span.get("attributes", {})
    scope = scope or {}
    result: dict[str, Any] = {}

    # Detect provider-specific transformer
    provider_transformer = detect_provider(span, scope)
    if provider_transformer:
        logger.info(
            "provider_transformer_detected",
            provider=provider_transformer.get_provider_name(),
            scope_name=scope.get("name"),
            span_name=span.get("name"),
        )

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
    # Try indexed messages first (gen_ai.prompt.0.role, gen_ai.prompt.0.content, etc.)
    prompts = _extract_indexed_messages(attributes, "gen_ai.prompt")
    if prompts:
        result["prompt"] = prompts
    # Fallback to direct gen_ai.prompt attribute
    elif (prompt := attributes.get("gen_ai.prompt")) is not None:
        # Try provider-specific transformation
        if provider_transformer:
            logger.info(
                "provider_transform_prompt_attempt",
                provider=provider_transformer.get_provider_name(),
                prompt_type=type(prompt).__name__,
                prompt_length=len(str(prompt)) if prompt else 0,
            )
            transformed = provider_transformer.transform_prompt(prompt)
            if transformed is not None:
                logger.info(
                    "provider_transform_prompt_success",
                    provider=provider_transformer.get_provider_name(),
                    result_type=type(transformed).__name__,
                    result_length=len(transformed) if isinstance(transformed, list) else 0,
                )
                result["prompt"] = transformed
            else:
                logger.info(
                    "provider_transform_prompt_none",
                    provider=provider_transformer.get_provider_name(),
                )
                result["prompt"] = prompt
        else:
            result["prompt"] = prompt

    completions = _extract_indexed_messages(attributes, "gen_ai.completion")
    if completions:
        result["completion"] = completions
    # Fallback to direct gen_ai.completion attribute
    elif (completion := attributes.get("gen_ai.completion")) is not None:
        # Try provider-specific transformation
        if provider_transformer:
            logger.info(
                "provider_transform_completion_attempt",
                provider=provider_transformer.get_provider_name(),
                completion_type=type(completion).__name__,
                completion_length=len(str(completion)) if completion else 0,
            )
            transformed = provider_transformer.transform_completion(completion)
            if transformed is not None:
                logger.info(
                    "provider_transform_completion_success",
                    provider=provider_transformer.get_provider_name(),
                    result_type=type(transformed).__name__,
                    result_length=len(transformed) if isinstance(transformed, list) else 0,
                )
                result["completion"] = transformed
            else:
                logger.info(
                    "provider_transform_completion_none",
                    provider=provider_transformer.get_provider_name(),
                )
                result["completion"] = completion
        else:
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
