"""
Main text formatter for LLM trace events.

Combines metadata, tools, input, and output into a readable text representation.
Supports both $ai_generation and $ai_span events.

Ports TypeScript textFormatter.ts to Python for pure Python text repr implementation.
"""

from typing import Any

from .message_formatter import FormatterOptions, format_input_messages, format_output_messages
from .tool_formatter import format_tools

SEPARATOR = "-" * 80


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
    if props.get("$ai_error") or props.get("$ai_is_error"):
        if lines:
            lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("ERROR:")
        lines.append("")

        error_value = props.get("$ai_error")
        if error_value:
            if isinstance(error_value, str):
                lines.append(error_value)
            elif isinstance(error_value, dict):
                import json

                lines.append(json.dumps(error_value, indent=2))
            else:
                lines.append(str(error_value))
        else:
            lines.append("An error occurred (no details available)")

        lines.append("")

    return "\n".join(lines)


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
    if props.get("$ai_error") or props.get("$ai_is_error"):
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("ERROR:")
        lines.append("")

        error_value = props.get("$ai_error")
        if error_value:
            if isinstance(error_value, str):
                lines.append(error_value)
            elif isinstance(error_value, dict):
                import json

                lines.append(json.dumps(error_value, indent=2))
            else:
                lines.append(str(error_value))
        else:
            lines.append("An error occurred (no details available)")

        lines.append("")

    return "\n".join(lines)


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
