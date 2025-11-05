"""
Format span events for text view.

Handles formatting of $ai_span events, which represent units of work within an LLM trace.
Displays span metadata, input/output state, and timing information with truncation support.
"""

import json
from typing import Any

from .message_formatter import FormatterOptions, add_line_numbers, truncate_content


def _format_state(state: Any, label: str, options: FormatterOptions | None = None) -> list[str]:
    """Format a state object (input or output) for display."""
    if not state:
        return []

    lines: list[str] = []
    lines.append("")
    lines.append(f"{label}:")
    lines.append("")

    try:
        # Handle string state
        if isinstance(state, str):
            content_lines, _ = truncate_content(state, options)
            lines.extend(content_lines)
            return lines

        # Handle object state
        if isinstance(state, dict) or isinstance(state, list):
            json_str = json.dumps(state, indent=2)
            content_lines, _ = truncate_content(json_str, options)
            lines.extend(content_lines)
            return lines

        # Fallback for other types
        lines.append(str(state))
        return lines
    except Exception:
        # Safe fallback if JSON.dumps fails (circular refs, etc.)
        lines.append(f"[UNABLE_TO_PARSE: {type(state).__name__}]")
        return lines


def format_span_text_repr(event: dict[str, Any], options: FormatterOptions | None = None) -> str:
    """Generate complete text representation of a span event."""
    lines: list[str] = []
    props = event.get("properties", {})

    # Span name/title
    span_name = props.get("$ai_span_name", "Span")
    lines.append(span_name.upper())
    lines.append("=" * 80)

    # Error information
    if props.get("$ai_error"):
        lines.append("-" * 80)
        lines.append("")
        lines.append("ERROR:")
        lines.append("")

        error_value = props["$ai_error"]
        if isinstance(error_value, str):
            lines.append(error_value)
        elif isinstance(error_value, dict):
            lines.append(json.dumps(error_value, indent=2))
        else:
            lines.append(str(error_value))

    # Input state
    input_lines = _format_state(props.get("$ai_input_state"), "INPUT STATE", options)
    if input_lines:
        lines.append("-" * 80)
        lines.extend(input_lines)

    # Output state
    output_lines = _format_state(props.get("$ai_output_state"), "OUTPUT STATE", options)
    if output_lines:
        lines.append("-" * 80)
        lines.extend(output_lines)

    formatted_text = "\n".join(lines)

    # Add line numbers if requested
    if options and options.get("include_line_numbers", False):
        formatted_text = add_line_numbers(formatted_text)

    return formatted_text
