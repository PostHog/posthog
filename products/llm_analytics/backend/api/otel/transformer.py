"""
Core OTel span to PostHog AI event transformer.

Transforms OpenTelemetry spans into PostHog AI events using a waterfall
pattern for attribute extraction:
1. PostHog native attributes (highest priority)
2. GenAI semantic conventions (fallback)
3. OTel span built-ins (trace_id, span_id, etc.)
"""

import json
from datetime import UTC, datetime
from typing import Any

from .conventions.genai import extract_genai_attributes, has_genai_attributes
from .conventions.posthog_native import extract_posthog_native_attributes, has_posthog_attributes
from .event_merger import cache_and_merge_properties

OTEL_TRANSFORMER_VERSION = "1.0.0"

# Span status codes (from OpenTelemetry spec)
SPAN_STATUS_UNSET = 0
SPAN_STATUS_OK = 1
SPAN_STATUS_ERROR = 2


def transform_span_to_ai_event(
    span: dict[str, Any],
    resource: dict[str, Any],
    scope: dict[str, Any],
    baggage: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Transform a single OTel span to PostHog AI event.

    Args:
        span: Parsed OTel span
        resource: Resource attributes (service.name, etc.)
        scope: Instrumentation scope info
        baggage: Baggage context (session_id, etc.)

    Returns:
        PostHog AI event dict OR None if this is first arrival (cached, waiting for logs):
        - event: Event type ($ai_generation, $ai_span, etc.)
        - distinct_id: User identifier
        - timestamp: ISO 8601 timestamp
        - properties: AI event properties
        - uuid: Event UUID (for deduplication with log events)
    """
    baggage = baggage or {}

    # Extract attributes using waterfall pattern
    posthog_attrs = extract_posthog_native_attributes(span)
    genai_attrs = extract_genai_attributes(span, scope)

    # Merge with precedence: PostHog > GenAI
    merged_attrs = {**genai_attrs, **posthog_attrs}

    # Build AI event properties
    properties = build_event_properties(span, merged_attrs, resource, scope, baggage)

    # Detect v1 vs v2 instrumentation:
    # v1: Everything in span attributes (extracted as "prompt", "completion") - send immediately
    # v2: Metadata in span, content in logs - use event merger
    # Some frameworks (e.g., Mastra) are v1 but may have spans without prompt/completion (parent spans)
    # Detect these by instrumentation scope name
    scope_name = scope.get("name", "")
    is_v1_framework = scope_name == "@mastra/otel"  # Mastra uses v1 (attributes in spans)
    is_v1_span = bool(merged_attrs.get("prompt") or merged_attrs.get("completion")) or is_v1_framework

    if not is_v1_span:
        # v2 instrumentation - use event merger for bidirectional merge with logs
        trace_id = span.get("trace_id", "")
        span_id = span.get("span_id", "")
        if trace_id and span_id:
            merged = cache_and_merge_properties(trace_id, span_id, properties, is_trace=True)
            if merged is None:
                # This is first arrival - trace cached, waiting for logs
                # Don't send this event yet
                return None
            # Second arrival - logs already cached, merged contains complete event
            properties = merged
    # else: v1 span has everything - send immediately without merging

    # Determine event type
    event_type = determine_event_type(span, merged_attrs, scope)

    # Calculate timestamp
    timestamp = calculate_timestamp(span)

    # Get distinct_id
    distinct_id = extract_distinct_id(resource, baggage)

    # Generate consistent UUID from trace_id + span_id for deduplication
    # This allows log events and trace events for the same span to merge
    import uuid

    trace_id = span.get("trace_id", "")
    span_id = span.get("span_id", "")
    event_uuid = None
    if trace_id and span_id:
        # Create deterministic UUID from trace_id + span_id
        namespace = uuid.UUID("00000000-0000-0000-0000-000000000000")
        event_uuid = str(uuid.uuid5(namespace, f"{trace_id}:{span_id}"))

    result = {
        "event": event_type,
        "distinct_id": distinct_id,
        "timestamp": timestamp,
        "properties": properties,
    }

    if event_uuid:
        result["uuid"] = event_uuid

    return result


def build_event_properties(
    span: dict[str, Any],
    attrs: dict[str, Any],
    resource: dict[str, Any],
    scope: dict[str, Any],
    baggage: dict[str, str],
) -> dict[str, Any]:
    """Build PostHog AI event properties from extracted attributes."""
    attributes = span.get("attributes", {})
    status = span.get("status", {})

    # Core identifiers (prefer extracted, fallback to span built-ins)
    trace_id = attrs.get("trace_id") or span.get("trace_id")
    span_id = attrs.get("span_id") or span.get("span_id")
    parent_id = attrs.get("parent_id") or span.get("parent_span_id")

    # Session ID (prefer extracted, fallback to baggage)
    session_id = attrs.get("session_id") or baggage.get("session_id") or baggage.get("posthog.session_id")

    # Calculate latency
    latency = calculate_latency(span)

    # Detect error from span status
    is_error = attrs.get("is_error")
    if is_error is None:
        is_error = status.get("code") == SPAN_STATUS_ERROR
    error_message = attrs.get("error_message")
    if error_message is None and is_error:
        error_message = status.get("message")

    # Build base properties
    properties: dict[str, Any] = {
        # Core IDs
        "$ai_trace_id": trace_id,
        "$ai_span_id": span_id,
    }

    # Optional core IDs
    if parent_id:
        properties["$ai_parent_id"] = parent_id
    if session_id:
        properties["$ai_session_id"] = session_id
    if attrs.get("generation_id"):
        properties["$ai_generation_id"] = attrs["generation_id"]

    # Model info
    if attrs.get("model"):
        properties["$ai_model"] = attrs["model"]
    if attrs.get("provider"):
        properties["$ai_provider"] = attrs["provider"]

    # Tokens
    if attrs.get("input_tokens") is not None:
        properties["$ai_input_tokens"] = attrs["input_tokens"]
    if attrs.get("output_tokens") is not None:
        properties["$ai_output_tokens"] = attrs["output_tokens"]
    if attrs.get("cache_read_tokens") is not None:
        properties["$ai_cache_read_input_tokens"] = attrs["cache_read_tokens"]
    if attrs.get("cache_write_tokens") is not None:
        properties["$ai_cache_creation_input_tokens"] = attrs["cache_write_tokens"]

    # Cost
    if attrs.get("input_cost_usd") is not None:
        properties["$ai_input_cost_usd"] = attrs["input_cost_usd"]
    if attrs.get("output_cost_usd") is not None:
        properties["$ai_output_cost_usd"] = attrs["output_cost_usd"]
    if attrs.get("total_cost_usd") is not None:
        properties["$ai_total_cost_usd"] = attrs["total_cost_usd"]

    # Timing
    if latency is not None:
        properties["$ai_latency"] = latency

    # Error
    if is_error:
        properties["$ai_is_error"] = is_error
    if error_message:
        properties["$ai_error"] = error_message

    # Model parameters
    if attrs.get("temperature") is not None:
        properties["$ai_temperature"] = attrs["temperature"]
    if attrs.get("max_tokens") is not None:
        properties["$ai_max_tokens"] = attrs["max_tokens"]
    if attrs.get("stream") is not None:
        properties["$ai_stream"] = attrs["stream"]

    # Content (handle both direct input/output and prompt/completion)
    # Ensure $ai_input is array of messages
    content_input = attrs.get("input") or attrs.get("prompt")
    if content_input:
        if isinstance(content_input, list):
            properties["$ai_input"] = content_input
        elif isinstance(content_input, dict):
            properties["$ai_input"] = [content_input]
        elif isinstance(content_input, str):
            try:
                parsed = json.loads(content_input)
                properties["$ai_input"] = (
                    parsed if isinstance(parsed, list) else [{"role": "user", "content": content_input}]
                )
            except (json.JSONDecodeError, TypeError):
                properties["$ai_input"] = [{"role": "user", "content": content_input}]
        else:
            properties["$ai_input"] = [{"role": "user", "content": str(content_input)}]

    # Ensure $ai_output_choices is array of choices
    content_output = attrs.get("output") or attrs.get("completion")
    if content_output:
        if isinstance(content_output, list):
            properties["$ai_output_choices"] = content_output
        elif isinstance(content_output, dict):
            properties["$ai_output_choices"] = [content_output]
        elif isinstance(content_output, str):
            try:
                parsed = json.loads(content_output)
                properties["$ai_output_choices"] = (
                    parsed if isinstance(parsed, list) else [{"role": "assistant", "content": content_output}]
                )
            except (json.JSONDecodeError, TypeError):
                properties["$ai_output_choices"] = [{"role": "assistant", "content": content_output}]
        else:
            properties["$ai_output_choices"] = [{"role": "assistant", "content": str(content_output)}]

    # Span name
    if span.get("name"):
        properties["$ai_span_name"] = span["name"]

    # Metadata
    properties["$ai_otel_transformer_version"] = OTEL_TRANSFORMER_VERSION
    properties["$ai_otel_span_kind"] = str(span.get("kind", 0))
    properties["$ai_otel_status_code"] = str(status.get("code", 0))

    # Resource attributes (service name, etc.)
    if resource.get("service.name"):
        properties["$ai_service_name"] = resource["service.name"]

    # Instrumentation scope
    properties["$ai_instrumentation_scope_name"] = scope.get("name", "unknown")
    if scope.get("version"):
        properties["$ai_instrumentation_scope_version"] = scope["version"]

    # Extract tool definitions from llm.request.functions.* attributes
    tools = _extract_tools_from_attributes(attributes)
    if tools:
        properties["$ai_tools"] = tools

    # Add remaining span attributes (not already mapped)
    mapped_keys = {
        "posthog.ai.model",
        "posthog.ai.provider",
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.operation.name",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.prompt",
        "gen_ai.completion",
        "service.name",
        "input",  # Generic input (e.g., Mastra for Laminar compatibility)
        "output",  # Generic output (e.g., Mastra for Laminar compatibility)
    }

    for key, value in attributes.items():
        if key not in mapped_keys and not key.startswith("posthog.ai.") and not key.startswith("gen_ai."):
            # Skip llm.request.functions.* as they're now in $ai_tools
            if not key.startswith("llm.request.functions."):
                # Add unmapped attributes with prefix
                properties[f"otel.{key}"] = value

    return properties


def _extract_tools_from_attributes(attributes: dict[str, Any]) -> list[dict[str, Any]] | None:
    """
    Extract tool definitions from llm.request.functions.* attributes.

    Converts flat attributes like:
      llm.request.functions.0.name = "get_weather"
      llm.request.functions.0.description = "Get weather"
      llm.request.functions.0.parameters = "{...}"

    Into structured array:
      [{"name": "get_weather", "description": "Get weather", "input_schema": {...}}]
    """
    from collections import defaultdict

    tools_by_index: dict[int, dict[str, Any]] = defaultdict(dict)

    for key, value in attributes.items():
        if not key.startswith("llm.request.functions."):
            continue

        # Parse: llm.request.functions.0.name -> index=0, field=name
        parts = key[len("llm.request.functions.") :].split(".", 1)
        if len(parts) != 2:
            continue

        try:
            index = int(parts[0])
            field = parts[1]

            # Map OTEL field names to PostHog SDK format
            if field == "parameters":
                # Parse JSON string to dict for input_schema
                try:
                    tools_by_index[index]["input_schema"] = json.loads(value) if isinstance(value, str) else value
                except (json.JSONDecodeError, TypeError):
                    tools_by_index[index]["input_schema"] = value
            else:
                tools_by_index[index][field] = value

        except (ValueError, IndexError):
            continue

    if not tools_by_index:
        return None

    # Convert to sorted list
    return [tools_by_index[i] for i in sorted(tools_by_index.keys())]


def determine_event_type(span: dict[str, Any], attrs: dict[str, Any], scope: dict[str, Any] | None = None) -> str:
    """Determine AI event type from span."""
    scope = scope or {}
    op_name = attrs.get("operation_name", "").lower()

    # Check operation name first (highest priority)
    if op_name in ("chat", "completion"):
        return "$ai_generation"
    elif op_name in ("embedding", "embeddings"):
        return "$ai_embedding"

    # Check if span has LLM-specific attributes (provider, model, tokens)
    # These indicate it's an actual LLM generation, not just a wrapper span
    has_llm_attrs = bool(
        attrs.get("provider") and attrs.get("model") and (attrs.get("input_tokens") is not None or attrs.get("prompt"))
    )
    if has_llm_attrs:
        return "$ai_generation"

    # Check if span is root (no parent)
    # For v1 frameworks (like Mastra), root spans should be $ai_span, not $ai_trace
    # $ai_trace events get filtered out by TraceQueryRunner, breaking tree hierarchy
    if not span.get("parent_span_id"):
        scope_name = scope.get("name", "")
        is_v1_framework = scope_name == "@mastra/otel"
        if is_v1_framework:
            # v1 frameworks: root span should be $ai_span (will be included in tree)
            return "$ai_span"
        else:
            # v2 frameworks: root is $ai_trace (separate from event tree)
            return "$ai_trace"

    # Default to generic span
    return "$ai_span"


def calculate_timestamp(span: dict[str, Any]) -> str:
    """Calculate timestamp from span start time."""
    start_nanos = int(span.get("start_time_unix_nano", 0))
    millis = start_nanos // 1_000_000
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


def calculate_latency(span: dict[str, Any]) -> float | None:
    """Calculate latency in seconds from span start/end time."""
    end_nanos = span.get("end_time_unix_nano")
    if not end_nanos:
        return None

    start_nanos = int(span.get("start_time_unix_nano", 0))
    end_nanos = int(end_nanos)
    duration_nanos = end_nanos - start_nanos

    # Convert to seconds
    return duration_nanos / 1_000_000_000


def extract_distinct_id(resource: dict[str, Any], baggage: dict[str, str]) -> str:
    """Extract distinct_id from resource or baggage."""
    # Try resource attributes
    user_id = resource.get("user.id") or resource.get("enduser.id") or resource.get("posthog.distinct_id")

    if user_id and isinstance(user_id, str):
        return user_id

    # Try baggage
    if baggage.get("user_id"):
        return baggage["user_id"]
    if baggage.get("distinct_id"):
        return baggage["distinct_id"]

    # Default to anonymous
    return "anonymous"


def stringify_content(content: Any) -> Any:
    """
    Return content in appropriate format for PostHog properties.

    Keep structured data (lists/dicts) as-is for better UI rendering.
    Only convert to JSON string if it's already a string (rare case).
    """
    if isinstance(content, list | dict):
        return content
    if isinstance(content, str):
        # If it's already a JSON string, parse it to get structured data
        try:
            parsed = json.loads(content)
            return parsed
        except (json.JSONDecodeError, TypeError):
            return content
    return content


def span_uses_known_conventions(span: dict[str, Any]) -> bool:
    """Check if span uses PostHog or GenAI conventions."""
    return has_posthog_attributes(span) or has_genai_attributes(span)
