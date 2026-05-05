"""
Main event formatter for LLM analytics events.

Combines metadata, tools, input, and output into a readable text representation.
Handles $ai_generation and $ai_embedding events with structured error formatting,
model/timing information, and YAML-like rendering for complex data structures.
Dispatches to span_formatter for $ai_span events.
"""

import json
from datetime import date, datetime
from typing import Any

from .constants import SEPARATOR
from .message_formatter import FormatterOptions, add_line_numbers, format_input_messages, format_output_messages
from .tool_formatter import format_tools


def _dict_to_yaml_lines(obj: Any, indent: int = 0) -> list[str]:
    """
    Convert a dict/list/value to YAML-like formatted lines.
    Simple implementation that handles nested structures.
    """
    lines: list[str] = []
    prefix = "  " * indent

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict | list):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dict_to_yaml_lines(value, indent + 1))
            else:
                # Simple value - show inline
                lines.append(f"{prefix}{key}: {value}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict | list):
                lines.append(f"{prefix}-")
                lines.extend(_dict_to_yaml_lines(item, indent + 1))
            else:
                lines.append(f"{prefix}- {item}")
    else:
        # Simple value at root level
        lines.append(f"{prefix}{obj}")

    return lines


def _format_error_section(props: dict[str, Any]) -> list[str]:
    """
    Format error section with YAML-like rendering for dicts.

    Handles both $ai_error and $ai_is_error properties.
    Parses JSON strings and formats structured errors nicely.
    """
    lines: list[str] = []
    if not (props.get("$ai_error") or props.get("$ai_is_error")):
        return lines

    lines.append("")
    lines.append(SEPARATOR)
    lines.append("")
    lines.append("ERROR:")
    lines.append("")

    error_value = props.get("$ai_error")
    if error_value:
        # Try to parse string as JSON first
        parsed_dict = None
        if isinstance(error_value, str):
            try:
                parsed = json.loads(error_value)
                if isinstance(parsed, dict):
                    parsed_dict = parsed
            except (json.JSONDecodeError, ValueError):
                pass
        elif isinstance(error_value, dict):
            parsed_dict = error_value

        # If we have a dict, render as YAML-like format
        if parsed_dict:
            lines.extend(_dict_to_yaml_lines(parsed_dict, indent=0))
        else:
            # Fallback: just use the string as-is
            lines.append(str(error_value))
    else:
        lines.append("An error occurred (no details available)")

    lines.append("")
    return lines


def format_generation_text_repr(event: dict[str, Any], options: FormatterOptions | None = None) -> str:
    """
    Generate complete text representation of a generation event.
    This is the main entry point for converting an event to text.

    Displays sections in natural flow order: Tools → Input → Output → Error
    """
    lines: list[str] = []
    props = event.get("properties", {})

    # Tools (if available)
    tools_lines = format_tools(props.get("$ai_tools"), options)
    if tools_lines:
        lines.append(SEPARATOR)
        lines.extend(tools_lines)

    # Input messages
    input_lines = format_input_messages(props.get("$ai_input"), options)
    if input_lines:
        if lines:
            lines.append("")
        lines.append(SEPARATOR)
        lines.extend(input_lines)

    # Output messages
    output_lines = format_output_messages(props.get("$ai_output"), props.get("$ai_output_choices"), options)
    if output_lines:
        if lines:
            lines.append("")
        lines.append(SEPARATOR)
        lines.extend(output_lines)

    # Error information (show at the end after natural flow)
    error_lines = _format_error_section(props)
    if error_lines:
        if lines:
            lines.append("")
        lines.extend(error_lines)

    formatted_text = "\n".join(lines)

    # Add line numbers if requested
    if options and options.get("include_line_numbers", False):
        formatted_text = add_line_numbers(formatted_text)

    return formatted_text


def format_embedding_text_repr(event: dict[str, Any], options: FormatterOptions | None = None) -> str:
    """
    Generate text representation of an embedding event.
    Embeddings only have input text and metadata - no output vector is stored.
    """
    lines: list[str] = []
    props = event.get("properties", {})

    # Input text being embedded
    input_lines = format_input_messages(props.get("$ai_input"), options)
    if input_lines:
        lines.append(SEPARATOR)
        lines.extend(input_lines)

    # Output section
    if lines:
        lines.append("")
    lines.append(SEPARATOR)
    lines.append("")
    lines.append("OUTPUT:")
    lines.append("")
    lines.append("Embedding vector generated")
    lines.append("")

    # Error information if present
    error_lines = _format_error_section(props)
    if error_lines:
        lines.append("")
        lines.extend(error_lines)

    formatted_text = "\n".join(lines)

    # Add line numbers if requested
    if options and options.get("include_line_numbers", False):
        formatted_text = add_line_numbers(formatted_text)

    return formatted_text


def format_event_text_repr(event: dict[str, Any], options: FormatterOptions | None = None) -> str:
    """
    Generate complete text representation of any LLM event.
    Routes to the appropriate formatter based on event type.
    """
    event_type = event.get("event")

    if event_type == "$ai_span":
        # Import here to avoid circular dependency
        from .span_formatter import format_span_text_repr

        return format_span_text_repr(event, options)

    if event_type == "$ai_embedding":
        return format_embedding_text_repr(event, options)

    # Default to generation formatter for $ai_generation and other events
    return format_generation_text_repr(event, options)


def _maybe_decode_json(value: Any) -> Any:
    """Parse a JSON-encoded string, falling back to the raw value on miss.

    On `posthog.ai_events`, the heavy columns (`input`, `output`,
    `output_choices`, `tools`, `input_state`, `output_state`) are stored as
    JSON-encoded strings. The formatter needs them as parsed structures
    (lists / dicts), but plain-text inputs that were never JSON should still
    render as text — so we attempt a decode and pass the original through on
    failure.
    """
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def format_event_text_repr_from_ai_events_row(row: dict[str, Any], options: FormatterOptions | None = None) -> str:
    """Format an event whose heavy fields come from `posthog.ai_events` columns.

    Bridges the dedicated-column shape (`input`, `output`, `output_choices`,
    `tools`, `is_error`, `error`, `input_state`, `output_state`) to the
    `properties`-shaped event dict that `format_event_text_repr` consumes.

    Use this from query callers that read `posthog.ai_events` directly (i.e.
    that need the heavy columns post-strip-migration). Callers that already
    have an `events.properties` blob should keep using `format_event_text_repr`.

    Expected `row` keys: `uuid`, `event`, `timestamp`, plus any of the heavy /
    error / state columns listed above. Missing keys render as if the property
    were absent.
    """
    props: dict[str, Any] = {}
    if "input" in row:
        props["$ai_input"] = _maybe_decode_json(row["input"])
    if "output" in row:
        props["$ai_output"] = _maybe_decode_json(row["output"])
    if "output_choices" in row:
        props["$ai_output_choices"] = _maybe_decode_json(row["output_choices"])
    if "tools" in row:
        props["$ai_tools"] = _maybe_decode_json(row["tools"])
    if "input_state" in row:
        props["$ai_input_state"] = _maybe_decode_json(row["input_state"])
    if "output_state" in row:
        props["$ai_output_state"] = _maybe_decode_json(row["output_state"])
    if row.get("is_error"):
        props["$ai_is_error"] = True
        if row.get("error"):
            props["$ai_error"] = row["error"]

    timestamp = row.get("timestamp")
    if isinstance(timestamp, datetime | date):
        timestamp_str = timestamp.isoformat()
    else:
        timestamp_str = str(timestamp or "")
    event_data = {
        "id": str(row.get("uuid", "")),
        "event": row.get("event"),
        "timestamp": timestamp_str,
        "properties": props,
    }
    return format_event_text_repr(event_data, options)
