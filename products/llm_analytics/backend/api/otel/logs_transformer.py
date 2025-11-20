"""
Core OTel log record to PostHog AI event transformer.

Transforms OpenTelemetry log records into PostHog AI events.
Log records from GenAI instrumentation typically contain message content
(prompts/completions) in the body field.
"""

import json
from datetime import UTC, datetime
from typing import Any

OTEL_TRANSFORMER_VERSION = "1.0.0"


def transform_log_to_ai_event(
    log_record: dict[str, Any],
    resource: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """
    Transform a single OTel log record to PostHog AI event.

    Args:
        log_record: Parsed OTel log record
        resource: Resource attributes (service.name, etc.)
        scope: Instrumentation scope info

    Returns:
        PostHog AI event dict with:
        - event: Event type ($ai_generation, $ai_span, etc.)
        - distinct_id: User identifier
        - timestamp: ISO 8601 timestamp
        - properties: AI event properties
    """
    attributes = log_record.get("attributes", {})

    # Build AI event properties
    properties = build_event_properties(log_record, attributes, resource, scope)

    # Determine event type
    event_type = determine_event_type(log_record, attributes)

    # Calculate timestamp
    timestamp = calculate_timestamp(log_record)

    # Get distinct_id
    distinct_id = extract_distinct_id(resource, attributes)

    return {
        "event": event_type,
        "distinct_id": distinct_id,
        "timestamp": timestamp,
        "properties": properties,
    }


def build_event_properties(
    log_record: dict[str, Any],
    attributes: dict[str, Any],
    resource: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    """Build PostHog AI event properties from log record."""

    # Core identifiers (from log record)
    trace_id = log_record.get("trace_id")
    span_id = log_record.get("span_id")

    # Session ID (from attributes or resource)
    session_id = attributes.get("session_id") or resource.get("session.id")

    # Extract message content from body
    body = log_record.get("body")

    # Build base properties
    properties: dict[str, Any] = {}

    # Core IDs
    if trace_id:
        properties["$ai_trace_id"] = trace_id
    if span_id:
        properties["$ai_span_id"] = span_id
    if session_id:
        properties["$ai_session_id"] = session_id

    # Model info (from attributes)
    if attributes.get("gen_ai.system"):
        properties["$ai_provider"] = attributes["gen_ai.system"]
    elif attributes.get("model.provider"):
        properties["$ai_provider"] = attributes["model.provider"]

    if attributes.get("gen_ai.request.model"):
        properties["$ai_model"] = attributes["gen_ai.request.model"]
    elif attributes.get("gen_ai.response.model"):
        properties["$ai_model"] = attributes["gen_ai.response.model"]
    elif attributes.get("model.name"):
        properties["$ai_model"] = attributes["model.name"]

    # Tokens (from attributes)
    if attributes.get("gen_ai.usage.input_tokens") is not None:
        properties["$ai_input_tokens"] = attributes["gen_ai.usage.input_tokens"]
    if attributes.get("gen_ai.usage.output_tokens") is not None:
        properties["$ai_output_tokens"] = attributes["gen_ai.usage.output_tokens"]

    # Message content - handle v2 structured log events
    # v2 instrumentation sends logs with event names like:
    # - gen_ai.user.message (body: {"content": "..."})
    # - gen_ai.assistant.message (body: {"content": "..."} or {"tool_calls": [...]})
    # - gen_ai.choice (body: {"index": 0, "finish_reason": "stop", "message": {...}})

    # Handle v2 message events
    # v2 uses LogRecord.event_name (in attributes) and structured body
    if isinstance(body, dict):
        # v2 user/system messages: {"content": "..."}
        if "content" in body and isinstance(body["content"], str):
            content_text = body["content"]
            # Determine if input or output based on context
            # For now, store as generic message - the span will have role info
            properties["$ai_message_content"] = content_text

        # v2 assistant messages with tool calls: {"tool_calls": [...]}
        if "tool_calls" in body and isinstance(body["tool_calls"], list):
            properties["$ai_tool_calls"] = body["tool_calls"]

        # v2 choice events: {"index": 0, "finish_reason": "stop", "message": {...}}
        if "message" in body and isinstance(body["message"], dict):
            message_obj = body["message"]
            if "content" in message_obj:
                properties["$ai_output_content"] = message_obj["content"]
            if "tool_calls" in message_obj:
                properties["$ai_tool_calls"] = message_obj["tool_calls"]
            if "role" in message_obj:
                properties["$ai_message_role"] = message_obj["role"]
            if "finish_reason" in body:
                properties["$ai_finish_reason"] = body["finish_reason"]

    # Fallback: legacy v1-style attributes
    if attributes.get("gen_ai.prompt"):
        properties["$ai_input"] = stringify_content(attributes["gen_ai.prompt"])
    elif attributes.get("message.content"):
        properties["$ai_input"] = stringify_content(attributes["message.content"])

    if attributes.get("gen_ai.completion"):
        properties["$ai_output_choices"] = stringify_content(attributes["gen_ai.completion"])

    # Severity
    if log_record.get("severity_number"):
        properties["$ai_log_severity_number"] = log_record["severity_number"]
    if log_record.get("severity_text"):
        properties["$ai_log_severity_text"] = log_record["severity_text"]

    # Metadata
    properties["$ai_otel_transformer_version"] = OTEL_TRANSFORMER_VERSION
    properties["$ai_otel_log_source"] = "logs"

    # Resource attributes (service name, etc.)
    if resource.get("service.name"):
        properties["$ai_service_name"] = resource["service.name"]

    # Instrumentation scope
    properties["$ai_instrumentation_scope_name"] = scope.get("name", "unknown")
    if scope.get("version"):
        properties["$ai_instrumentation_scope_version"] = scope["version"]

    # Add remaining log attributes (not already mapped)
    mapped_keys = {
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.prompt",
        "gen_ai.completion",
        "model.provider",
        "model.name",
        "message.content",
        "session_id",
        "session.id",
        "event.name",
        "service.name",
    }

    for key, value in attributes.items():
        if key not in mapped_keys and not key.startswith("gen_ai."):
            # Add unmapped attributes with prefix
            properties[f"otel.{key}"] = value

    return properties


def determine_event_type(log_record: dict[str, Any], attributes: dict[str, Any]) -> str:
    """Determine AI event type from log record."""
    event_name = attributes.get("event.name", "").lower()

    # Check event name for GenAI events
    if "prompt" in event_name or "input" in event_name:
        return "$ai_generation"
    elif "completion" in event_name or "output" in event_name or "response" in event_name:
        return "$ai_generation"
    elif "embedding" in event_name:
        return "$ai_embedding"

    # Check operation name
    op_name = attributes.get("gen_ai.operation.name", "").lower()
    if op_name in ("chat", "completion"):
        return "$ai_generation"
    elif op_name in ("embedding", "embeddings"):
        return "$ai_embedding"

    # Default to generic span
    return "$ai_span"


def calculate_timestamp(log_record: dict[str, Any]) -> str:
    """Calculate timestamp from log record time."""
    time_nanos = int(log_record.get("time_unix_nano", 0))
    if time_nanos == 0:
        # Fallback to observed time if time is not set
        time_nanos = int(log_record.get("observed_time_unix_nano", 0))

    millis = time_nanos // 1_000_000
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


def extract_distinct_id(resource: dict[str, Any], attributes: dict[str, Any]) -> str:
    """Extract distinct_id from resource or attributes."""
    # Try resource attributes
    user_id = resource.get("user.id") or resource.get("enduser.id") or resource.get("posthog.distinct_id")

    if user_id and isinstance(user_id, str):
        return user_id

    # Try log attributes
    if attributes.get("user_id"):
        return str(attributes["user_id"])
    if attributes.get("distinct_id"):
        return str(attributes["distinct_id"])

    # Default to anonymous
    return "anonymous"


def stringify_content(content: Any) -> str:
    """Stringify content (handles objects and strings)."""
    if isinstance(content, str):
        return content
    return json.dumps(content)
