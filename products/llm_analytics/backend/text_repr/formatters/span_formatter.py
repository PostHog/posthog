"""
Format span events for text view.

Handles formatting of $ai_span events, which represent units of work within an LLM trace.
Displays span metadata, input/output state, and timing information with truncation support.
"""

import ast
import json
from typing import Any

from .message_formatter import (
    FormatterOptions,
    add_line_numbers,
    format_messages_array,
    format_single_tool_call,
    truncate_content,
)


def _format_string_state(state: str, options: FormatterOptions | None) -> list[str]:
    """Format string state, attempting to parse as Python literal first."""
    try:
        parsed = ast.literal_eval(state)
        if isinstance(parsed, dict | list):
            json_str = json.dumps(parsed, indent=2)
            content_lines, _ = truncate_content(json_str, options)
            return content_lines
    except (ValueError, SyntaxError):
        pass

    content_lines, _ = truncate_content(state, options)
    return content_lines


def _format_messages_array_state(state: list, options: FormatterOptions | None) -> list[str] | None:
    """Format state as messages array if it matches the pattern."""
    if len(state) > 0 and isinstance(state[0], dict):
        first_item = state[0]
        if "role" in first_item or "content" in first_item:
            return format_messages_array(state, options)
    return None


def _format_tool_call_with_context(state: dict, options: FormatterOptions | None) -> list[str] | None:
    """Format tool_call_with_context structure."""
    if state.get("__type") != "tool_call_with_context":
        return None

    lines: list[str] = []
    nested_state = state.get("state", {})
    tool_call = state.get("tool_call", {})

    if isinstance(nested_state, dict):
        messages = nested_state.get("messages", [])
        if isinstance(messages, list) and len(messages) > 0:
            lines.extend(format_messages_array(messages, options))

        remaining_steps = nested_state.get("remaining_steps")
        if remaining_steps is not None:
            lines.append("")
            lines.append(f"Remaining steps: {remaining_steps}")

    if isinstance(tool_call, dict) and tool_call:
        lines.append("")
        lines.append("Tool Call:")
        tool_name = tool_call.get("name", "unknown")
        tool_args = tool_call.get("args", {})
        lines.append(f"  {format_single_tool_call(tool_name, tool_args)}")

    return lines


def _format_dict_with_messages(state: dict, options: FormatterOptions | None) -> list[str] | None:
    """Format dict containing a messages array."""
    if "messages" not in state:
        return None

    messages = state.get("messages")
    if isinstance(messages, list) and len(messages) > 0:
        return format_messages_array(messages, options)
    return None


def _format_tool_result(state: dict, options: FormatterOptions | None) -> list[str] | None:
    """Format tool result structure."""
    if state.get("type") != "tool":
        return None

    lines: list[str] = []
    tool_name = state.get("name")
    status = state.get("status")
    content = state.get("content", "")

    header_parts = ["[TOOL RESULT]"]
    if tool_name:
        header_parts.append(tool_name)
    if status:
        header_parts.append(f"({status})")
    lines.append(" ".join(header_parts))

    if content:
        lines.append("")
        content_lines, _ = truncate_content(str(content), options)
        lines.extend(content_lines)

    return lines


def _format_generic_json(state: dict | list, options: FormatterOptions | None) -> list[str]:
    """Format generic dict or list as JSON."""
    json_str = json.dumps(state, indent=2)
    content_lines, _ = truncate_content(json_str, options)
    return content_lines


def _format_state(state: Any, label: str, options: FormatterOptions | None = None) -> list[str]:
    """Format a state object (input or output) for display.

    Dispatches to specialized formatters based on state type and structure.
    """
    if not state:
        return []

    lines: list[str] = []
    lines.append("")
    lines.append(f"{label}:")
    lines.append("")

    try:
        if isinstance(state, str):
            lines.extend(_format_string_state(state, options))
            return lines

        if isinstance(state, list):
            content_lines = _format_messages_array_state(state, options)
            if content_lines is not None:
                lines.extend(content_lines)
                return lines
            lines.extend(_format_generic_json(state, options))
            return lines

        if isinstance(state, dict):
            content_lines = _format_tool_call_with_context(state, options)
            if content_lines is not None:
                lines.extend(content_lines)
                return lines

            content_lines = _format_dict_with_messages(state, options)
            if content_lines is not None:
                lines.extend(content_lines)
                return lines

            content_lines = _format_tool_result(state, options)
            if content_lines is not None:
                lines.extend(content_lines)
                return lines

            lines.extend(_format_generic_json(state, options))
            return lines

        lines.append(str(state))
        return lines
    except Exception:
        lines.append(str(state))
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
