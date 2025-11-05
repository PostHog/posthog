"""
Format full traces with hierarchy for text view.

Creates ASCII tree structure with clickable expandable nodes for trace visualization.
Handles hierarchical event relationships, trace-level input/output state, and
supports both interactive frontend markers and plain text for backend/LLM consumption.
"""

import json
import base64
from typing import Any
from urllib.parse import quote

from .constants import MAX_TREE_DEPTH, SEPARATOR
from .event_formatter import format_event_text_repr
from .message_formatter import (
    FormatterOptions,
    add_line_numbers,
    format_input_messages,
    format_output_messages,
    truncate_content,
)


def _format_latency(latency: float) -> str:
    """Format latency to 2 decimal places."""
    return f"{latency:.2f}s"


def _format_cost(cost: float) -> str:
    """Format cost in USD."""
    return f"${cost:.4f}"


def _get_event_summary(event: dict[str, Any]) -> str:
    """
    Get a brief summary of an event for tree display.

    Returns a one-line summary like:
    - "my-generation (0.45s, $0.0023, gpt-4)"
    - "my-span (1.2s)"
    - "ERROR: my-generation (0.45s, gpt-4)"
    """
    props = event.get("properties", {})
    event_type = event.get("event", "unknown")

    if event_type == "$ai_generation":
        span_name = props.get("$ai_span_name") or props.get("$ai_model") or "generation"
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_total_cost_usd") is not None:
            parts.append(_format_cost(props["$ai_total_cost_usd"]))

        if props.get("$ai_model"):
            parts.append(props["$ai_model"])

        if props.get("$ai_is_error") or props.get("$ai_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    if event_type == "$ai_span":
        span_name = props.get("$ai_span_name", "span")
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_is_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    if event_type == "$ai_embedding":
        span_name = props.get("$ai_span_name") or props.get("$ai_model") or "embedding"
        parts = []

        if props.get("$ai_latency") is not None:
            parts.append(_format_latency(props["$ai_latency"]))

        if props.get("$ai_total_cost_usd") is not None:
            parts.append(_format_cost(props["$ai_total_cost_usd"]))

        if props.get("$ai_model"):
            parts.append(props["$ai_model"])

        if props.get("$ai_is_error") or props.get("$ai_error"):
            parts.append("ERROR")

        summary = span_name
        if parts:
            summary += f" ({', '.join(parts)})"
        return summary

    return event_type


def _format_state(state: Any, label: str, options: FormatterOptions | None = None) -> list[str]:
    """Format a state object for display."""
    if not state:
        return []

    try:
        # Check if state looks like messages (list of dicts with role/content)
        if isinstance(state, list) and len(state) > 0 and isinstance(state[0], dict):
            first_item = state[0]
            if "role" in first_item or "content" in first_item:
                # Format as messages using appropriate formatter (they add their own headers)
                if "INPUT" in label:
                    return format_input_messages(state, options)
                else:
                    # For output, pass state as choices (second param)
                    return format_output_messages(None, state, options)

        # For non-message state, add the label header
        lines = ["", f"{label}:", ""]

        if isinstance(state, str):
            content_lines, _ = truncate_content(state, options)
            lines.extend(content_lines)
            return lines

        if isinstance(state, dict) or isinstance(state, list):
            json_str = json.dumps(state, indent=2)
            content_lines, _ = truncate_content(json_str, options)
            lines.extend(content_lines)
            return lines

        lines.append(str(state))
        return lines
    except Exception:
        # Safe fallback if JSON.stringify fails (circular refs, etc.)
        return ["", f"{label}:", "", f"[UNABLE_TO_PARSE: {type(state).__name__}]"]


def _render_tree(
    nodes: list[dict[str, Any]],
    options: FormatterOptions | None = None,
    prefix: str = "",
    is_last: bool = True,
    depth: int = 0,
) -> list[str]:
    """
    Render tree structure with ASCII art.

    Creates expandable nodes using:
    - <<<GEN_EXPANDABLE|eventId|displayText|encodedContent>>> for include_markers=True
    - Plain text [+] indicators for include_markers=False
    """
    lines: list[str] = []

    if depth > MAX_TREE_DEPTH:
        lines.append(f"{prefix}  [... max depth reached]")
        return lines

    options = options or {}
    include_markers = options.get("include_markers", True)
    collapsed = options.get("collapsed", False)

    for i, node in enumerate(nodes):
        is_last_node = i == len(nodes) - 1
        current_prefix = "└─ " if is_last_node else "├─ "
        child_prefix = "   " if is_last_node else "│  "

        event = node.get("event", node)  # Handle both {event: ..., children: ...} and plain event
        children = node.get("children", [])

        summary = _get_event_summary(event)
        event_type = event.get("event", "unknown")
        event_id = event.get("id", "unknown")

        # Format the node line with event type prefix
        if event_type == "$ai_generation":
            node_prefix = "[GEN]"

            if collapsed:
                # Just show summary, no expandable content
                lines.append(f"{prefix}{current_prefix}{node_prefix} {summary}")
            else:
                # Create expandable generation content
                gen_content = format_event_text_repr(event, options)

                if include_markers:
                    # Encode content for frontend to expand
                    encoded_content = base64.b64encode(quote(gen_content).encode()).decode()
                    display_text = f"{node_prefix} {summary}"
                    expandable_marker = f"<<<GEN_EXPANDABLE|{event_id}|{display_text}|{encoded_content}>>>"
                    lines.append(f"{prefix}{current_prefix}{expandable_marker}")
                else:
                    # Plain text for backend/LLM
                    lines.append(f"{prefix}{current_prefix}[+] {node_prefix} {summary}")

        elif event_type == "$ai_span":
            node_prefix = "[SPAN]"

            if collapsed:
                # Just show summary, no expandable content
                lines.append(f"{prefix}{current_prefix}{node_prefix} {summary}")
            else:
                # Create expandable span content
                span_content = format_event_text_repr(event, options)

                if include_markers:
                    # Encode content for frontend to expand
                    encoded_content = base64.b64encode(quote(span_content).encode()).decode()
                    display_text = f"{node_prefix} {summary}"
                    expandable_marker = f"<<<GEN_EXPANDABLE|{event_id}|{display_text}|{encoded_content}>>>"
                    lines.append(f"{prefix}{current_prefix}{expandable_marker}")
                else:
                    # Plain text for backend/LLM
                    lines.append(f"{prefix}{current_prefix}[+] {node_prefix} {summary}")

        elif event_type == "$ai_embedding":
            node_prefix = "[EMBED]"

            if collapsed:
                # Just show summary, no expandable content
                lines.append(f"{prefix}{current_prefix}{node_prefix} {summary}")
            else:
                # Create expandable embedding content
                embedding_content = format_event_text_repr(event, options)

                if include_markers:
                    # Encode content for frontend to expand
                    encoded_content = base64.b64encode(quote(embedding_content).encode()).decode()
                    display_text = f"{node_prefix} {summary}"
                    expandable_marker = f"<<<GEN_EXPANDABLE|{event_id}|{display_text}|{encoded_content}>>>"
                    lines.append(f"{prefix}{current_prefix}{expandable_marker}")
                else:
                    # Plain text for backend/LLM
                    lines.append(f"{prefix}{current_prefix}[+] {node_prefix} {summary}")

        else:
            # For other events, use event link marker
            node_prefix = "[EVENT]"
            if include_markers:
                clickable_prefix = f"<<<EVENT_LINK|{event_id}|{node_prefix}>>>"
                lines.append(f"{prefix}{current_prefix}{clickable_prefix} {summary}")
            else:
                lines.append(f"{prefix}{current_prefix}{node_prefix} {summary}")

        # Recursively render children
        if children:
            child_lines = _render_tree(
                children, options=options, prefix=prefix + child_prefix, is_last=is_last_node, depth=depth + 1
            )
            lines.extend(child_lines)

    return lines


def format_trace_text_repr(
    trace: dict[str, Any], hierarchy: list[dict[str, Any]], options: FormatterOptions | None = None
) -> str:
    """
    Format a complete trace with hierarchical event structure.

    Creates an ASCII tree view with clickable expandable nodes for generations/spans.

    Options:
        - collapsed: If True, show only tree structure without expandable content
        - include_markers: If True, use <<<MARKERS>>> for frontend, else plain text
        - truncated: Whether to truncate long content within events
        - truncate_buffer: Chars to show at start/end when truncating
        - include_line_numbers: If True, prefix each line with line number (L1:, L2:, etc.)

    Args:
        trace: The trace metadata with properties
        hierarchy: List of event nodes with children in tree structure
        options: Formatting options

    Returns:
        Formatted text representation of the trace with tree structure
    """
    lines: list[str] = []
    props = trace.get("properties", {})

    # Trace header - support both camelCase (API) and snake_case (properties)
    trace_name = props.get("$ai_span_name") or trace.get("traceName") or trace.get("trace_name") or "TRACE"
    lines.append(trace_name.upper())
    lines.append("=" * 80)

    # Error information (if at trace level)
    if props.get("$ai_error"):
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("TRACE ERROR:")
        lines.append("")
        error = props["$ai_error"]
        if isinstance(error, str):
            lines.append(error)
        else:
            lines.append(json.dumps(error, indent=2))

    # Only show trace-level input/output if there are NO events in hierarchy
    # When events exist, the hierarchy tells the full story
    if not hierarchy:
        # Trace-level input state - check both locations
        input_state = props.get("$ai_input_state") or trace.get("inputState") or trace.get("input_state")
        input_lines = _format_state(input_state, "TRACE INPUT", options)
        if input_lines:
            lines.append("")
            lines.append(SEPARATOR)
            lines.extend(input_lines)

        # Trace-level output state - check both locations
        output_state = props.get("$ai_output_state") or trace.get("outputState") or trace.get("output_state")
        output_lines = _format_state(output_state, "TRACE OUTPUT", options)
        if output_lines:
            lines.append("")
            lines.append(SEPARATOR)
            lines.extend(output_lines)
    else:
        # Tree structure exists - show it instead of trace input/output
        lines.append("")
        lines.append(SEPARATOR)
        lines.append("")
        lines.append("TRACE HIERARCHY:")
        lines.append("")
        lines.extend(_render_tree(hierarchy, options=options))

    formatted_text = "\n".join(lines)

    # Add line numbers if requested
    if options and options.get("include_line_numbers", False):
        formatted_text = add_line_numbers(formatted_text)

    return formatted_text
