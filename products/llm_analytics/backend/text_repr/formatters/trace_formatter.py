"""
Format full traces with hierarchy for text view.

Creates ASCII tree structure with clickable expandable nodes for trace visualization.
Handles hierarchical event relationships, trace-level input/output state, and
supports both interactive frontend markers and plain text for backend/LLM consumption.
"""

import json
import base64
from typing import Any

from posthog.schema import LLMTrace

from .constants import DEFAULT_MAX_LENGTH, MAX_TREE_DEPTH, SEPARATOR
from .event_formatter import format_event_text_repr
from .message_formatter import (
    FormatterOptions,
    add_line_numbers,
    format_input_messages,
    format_output_messages,
    reduce_by_uniform_sampling,
    truncate_content,
)


def llm_trace_to_formatter_format(llm_trace: LLMTrace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Convert an LLMTrace object to the format expected by format_trace_text_repr.

    Args:
        llm_trace: The LLMTrace object from TraceQueryRunner

    Returns:
        A tuple of (trace_dict, hierarchy) suitable for format_trace_text_repr
    """
    trace_dict = {
        "id": llm_trace.id,
        "properties": {
            "$ai_trace_id": llm_trace.id,
            "$ai_span_name": llm_trace.traceName,
            "$ai_session_id": llm_trace.aiSessionId,
            "$ai_input_state": llm_trace.inputState,
            "$ai_output_state": llm_trace.outputState,
        },
    }

    hierarchy = [
        {
            "event": {
                "id": event.id,
                "event": event.event,
                "properties": event.properties,
                "timestamp": event.createdAt,
            },
            "children": [],
        }
        for event in llm_trace.events
    ]

    return trace_dict, hierarchy


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

        if props.get("$ai_time_to_first_token") is not None:
            parts.append(f"TTFT: {_format_latency(props['$ai_time_to_first_token'])}")

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
        return ["", f"{label}:", "", str(state)]


def _get_node_prefix(event_type: str) -> str:
    """Get the display prefix for an event type."""
    if event_type == "$ai_generation":
        return "[GEN]"
    elif event_type == "$ai_span":
        return "[SPAN]"
    elif event_type == "$ai_embedding":
        return "[EMBED]"
    else:
        return "[EVENT]"


def _is_expandable_event(event_type: str) -> bool:
    """Check if event type supports expandable content."""
    return event_type in ("$ai_generation", "$ai_span", "$ai_embedding")


def _render_collapsed_node(prefix: str, current_prefix: str, node_prefix: str, summary: str) -> str:
    """Render a collapsed node showing only summary."""
    return f"{prefix}{current_prefix}{node_prefix} {summary}"


def _render_expandable_node_with_markers(
    prefix: str,
    current_prefix: str,
    node_prefix: str,
    summary: str,
    event_id: str,
    content: str,
) -> str:
    """Render expandable node with markers for frontend."""
    encoded_content = base64.b64encode(content.encode()).decode()
    display_text = f"{node_prefix} {summary}"
    expandable_marker = f"<<<GEN_EXPANDABLE|{event_id}|{display_text}|{encoded_content}>>>"
    return f"{prefix}{current_prefix}{expandable_marker}"


def _render_expandable_node_plain(
    prefix: str,
    current_prefix: str,
    child_prefix: str,
    node_prefix: str,
    summary: str,
    content: str,
) -> list[str]:
    """Render expandable node as plain text with full content inline."""
    lines = [f"{prefix}{current_prefix}[+] {node_prefix} {summary}"]
    for line in content.split("\n"):
        lines.append(f"{prefix}{child_prefix}    {line}")
    return lines


def _render_event_node(
    event: dict[str, Any],
    summary: str,
    prefix: str,
    current_prefix: str,
    child_prefix: str,
    options: FormatterOptions,
    collapsed: bool,
    include_markers: bool,
) -> list[str]:
    """Render a single event node based on its type and options."""
    event_type = event.get("event", "unknown")
    event_id = event.get("id", "unknown")
    node_prefix = _get_node_prefix(event_type)

    if collapsed:
        return [_render_collapsed_node(prefix, current_prefix, node_prefix, summary)]

    if not _is_expandable_event(event_type):
        if include_markers:
            clickable_prefix = f"<<<EVENT_LINK|{event_id}|{node_prefix}>>>"
            return [f"{prefix}{current_prefix}{clickable_prefix} {summary}"]
        return [f"{prefix}{current_prefix}{node_prefix} {summary}"]

    # Expandable event - disable line numbers for embedded content
    event_options: FormatterOptions = (
        {**options, "include_line_numbers": False} if options else {"include_line_numbers": False}
    )
    event_content = format_event_text_repr(event, event_options)

    if include_markers:
        return [
            _render_expandable_node_with_markers(prefix, current_prefix, node_prefix, summary, event_id, event_content)
        ]
    return _render_expandable_node_plain(prefix, current_prefix, child_prefix, node_prefix, summary, event_content)


def _render_tree(
    nodes: list[dict[str, Any]],
    options: FormatterOptions | None = None,
    prefix: str = "",
    is_last: bool = True,
    depth: int = 0,
) -> list[str]:
    """Render tree structure with ASCII art.

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

        event = node.get("event", node)
        children = node.get("children", [])

        summary = _get_event_summary(event)

        node_lines = _render_event_node(
            event, summary, prefix, current_prefix, child_prefix, options, collapsed, include_markers
        )
        lines.extend(node_lines)

        if children:
            child_lines = _render_tree(
                children, options=options, prefix=prefix + child_prefix, is_last=is_last_node, depth=depth + 1
            )
            lines.extend(child_lines)

    return lines


def format_trace_text_repr(
    trace: dict[str, Any], hierarchy: list[dict[str, Any]], options: FormatterOptions | None = None
) -> tuple[str, bool]:
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
        Tuple of (formatted_text, was_sampled) - the text representation and whether uniform sampling was applied
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

    # Apply max_length constraint by uniformly sampling lines if needed
    # Defaults to 2M chars to fit within LLM context windows
    max_length = options.get("max_length", DEFAULT_MAX_LENGTH) if options else DEFAULT_MAX_LENGTH
    was_sampled = False
    if max_length and len(formatted_text) > max_length:
        formatted_text, was_sampled = reduce_by_uniform_sampling(formatted_text, max_length)

    return formatted_text, was_sampled
