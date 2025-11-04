"""
Format input and output messages for text view.

Handles formatting of LLM messages including role-based conversations, tool calls,
and content blocks. Supports multiple provider formats (OpenAI, Anthropic, etc.)
with truncation and interactive markers for frontend display.
"""

import json
import base64
from typing import Any, TypedDict
from urllib.parse import quote

from .constants import DEFAULT_TRUNCATE_BUFFER, MAX_UNABLE_TO_PARSE_REPR_LENGTH, MAX_UNPARSED_DISPLAY_LENGTH


class FormatterOptions(TypedDict, total=False):
    """Options for formatting text representations."""

    truncated: bool  # Use truncation for long content (default: True)
    truncate_buffer: int  # Chars to show at start/end (default: 1000)
    include_markers: bool  # Use interactive markers vs plain text (default: True)
    collapsed: bool  # Show full hierarchy vs summary (default: False)


class ToolCall(TypedDict, total=False):
    """Tool call structure supporting multiple formats."""

    function: dict[str, Any]  # OpenAI format: {name, arguments}
    name: str  # LangChain format
    args: Any  # LangChain format


class Message(TypedDict, total=False):
    """Message structure."""

    role: str
    type: str
    content: Any
    tool_calls: list[ToolCall]


def truncate_content(content: str, options: FormatterOptions | None = None) -> tuple[list[str], bool]:
    """
    Truncate content with middle ellipsis for long text.
    Can use interactive markers (for frontend) or plain text indicators (for backend/LLM).

    Returns:
        Tuple of (lines, truncated_flag)
    """
    if options is None:
        options = {}

    should_truncate = options.get("truncated", True)  # Default: True
    max_length = options.get("truncate_buffer", DEFAULT_TRUNCATE_BUFFER)
    use_markers = options.get("include_markers", True)  # Default: True

    if not should_truncate or len(content) <= max_length:
        return ([content], False)

    half = max_length // 2
    first_part = content[:half]
    last_part = content[-half:]
    truncated_chars = len(content) - max_length

    if use_markers:
        # Frontend: encoded marker for expand/collapse UI
        middle_part = content[half:-half]
        # Base64 encode the URL-encoded middle part
        encoded_middle = base64.b64encode(quote(middle_part).encode()).decode()
        marker = f"<<<TRUNCATED|{encoded_middle}|{truncated_chars}>>>"
        return ([first_part, "", marker, "", last_part], True)
    else:
        # Backend: plain text indicator for LLM context
        marker = f"\n\n... ({truncated_chars} chars truncated) ...\n\n"
        return ([first_part + marker + last_part], True)


def format_single_tool_call(name: str, args: Any) -> str:
    """Format a single tool call as a function signature."""
    # Parse args into dict if needed
    parsed_args: dict[str, Any] | None = None

    if isinstance(args, dict):
        parsed_args = args
    elif isinstance(args, str) and args:
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            # If parsing fails, will show raw string
            pass

    # Format as function call
    if parsed_args and isinstance(parsed_args, dict):
        arg_entries = list(parsed_args.items())
        if arg_entries:
            arg_strings = [f"{k}={json.dumps(v)}" for k, v in arg_entries]
            return f"{name}({', '.join(arg_strings)})"
        return f"{name}()"
    elif args:
        # Fallback for unparseable args
        return f"{name}({args})"
    return f"{name}()"


def format_tool_calls(tool_calls: list[ToolCall]) -> list[str]:
    """Format tool calls for display."""
    lines: list[str] = []
    lines.append(f"Tool calls: {len(tool_calls)}")

    for tc in tool_calls:
        # Handle both OpenAI format (function: {name, arguments})
        # and LangChain format (name, args)
        if tc.get("function"):
            name = tc["function"].get("name", "unknown")
            args = tc["function"].get("arguments", "")
        else:
            name = tc.get("name", "unknown")
            args = tc.get("args", "")

        lines.append(f"  - {format_single_tool_call(name, args)}")

    return lines


def extract_tool_calls_from_content(content: Any) -> list[ToolCall]:
    """Extract tool calls from content array."""
    if not isinstance(content, list):
        return []

    tool_calls: list[ToolCall] = []
    for block in content:
        if isinstance(block, dict):
            # Handle tool-call format: { type: "tool-call", function: {...} }
            if block.get("type") == "tool-call" and "function" in block:
                if isinstance(block["function"], dict):
                    tool_calls.append({"function": block["function"]})
            # Handle Anthropic function format: { type: "function", function: {...} }
            elif block.get("type") == "function" and "function" in block:
                if isinstance(block["function"], dict):
                    tool_calls.append({"function": block["function"]})

    return tool_calls


def safe_extract_text(content: Any) -> str:
    """
    Safely extract text from various content formats.
    Handles strings, dicts with 'text' key, arrays of content blocks, etc.

    Includes data preservation in error cases to aid debugging and discovery of edge cases.
    """
    try:
        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            # Try common text keys
            if "text" in content:
                return str(content["text"])
            if "content" in content:
                return safe_extract_text(content["content"])
            # Fallback to JSON representation
            return json.dumps(content)

        if isinstance(content, list):
            text_parts = []
            for i, item in enumerate(content):
                if isinstance(item, dict):
                    item_type = item.get("type")
                    # Try both "text" and "content" keys (tool_result uses "content")
                    text_value = item.get("text") or item.get("content")

                    if text_value:
                        # Add spacing between all content blocks in the array
                        if i > 0 and text_parts:
                            text_parts.append("")  # Blank line separator

                        # If we have a type and it's not just "text", label it
                        if item_type and item_type != "text":
                            text_parts.append(f"[{item_type.upper()}]")
                            text_parts.append("")  # Blank line after label

                        text_parts.append(str(text_value))
                elif isinstance(item, str):
                    # Add spacing before string items too
                    if i > 0 and text_parts:
                        text_parts.append("")
                    text_parts.append(item)
            if text_parts:
                return "\n".join(text_parts)

        # Fallback with data preservation for debugging
        data_repr = repr(content)[:MAX_UNABLE_TO_PARSE_REPR_LENGTH]
        if len(repr(content)) > MAX_UNABLE_TO_PARSE_REPR_LENGTH:
            data_repr += "..."
        return f"[UNABLE_TO_PARSE: {type(content).__name__}] {data_repr}"
    except Exception as e:
        # Handle any unexpected errors during extraction
        try:
            data_repr = repr(content)[:MAX_UNABLE_TO_PARSE_REPR_LENGTH]
            return f"[PARSE_ERROR: {type(content).__name__}] {str(e)} | Data: {data_repr}"
        except:
            return f"[PARSE_ERROR: {type(content).__name__}] {str(e)}"


def _is_special_block(block: Any) -> bool:
    """Check if a block needs special handling (tool calls, functions, etc)."""
    if not isinstance(block, dict):
        return False

    block_type = block.get("type")
    if block_type in ("tool-call", "tool_use", "function"):
        return True

    # Check for tool-call content format
    if "content" in block and isinstance(block["content"], dict) and "toolName" in block["content"]:
        return True

    return False


def _format_special_block(block: dict) -> str | None:
    """
    Format special blocks (tool calls, tool_use, etc).

    Returns:
        Formatted string if block was handled, None if block should be skipped.
    """
    block_type = block.get("type")

    # Handle tool-call type directly (format: {type: "tool-call", toolName, input})
    if block_type == "tool-call":
        tool_name = block.get("toolName", "unknown")
        tool_input = block.get("input", {})
        return format_single_tool_call(tool_name, tool_input)

    # Handle tool_use type (Anthropic format)
    if block_type == "tool_use":
        tool_name = block.get("name", "unknown")
        tool_input = block.get("input", {})

        # If input is empty, check for partial_json field
        if not tool_input and "partial_json" in block:
            try:
                tool_input = json.loads(block["partial_json"])
            except (json.JSONDecodeError, ValueError):
                pass

        return format_single_tool_call(tool_name, tool_input)

    # Skip function blocks as they'll be handled separately
    if block_type == "function":
        return None

    # Handle tool-call content for inline display
    if "content" in block:
        block_content = block["content"]
        if isinstance(block_content, dict) and "toolName" in block_content:
            tool_name = block_content.get("toolName", "unknown")
            args = block_content.get("args", "")
            return format_single_tool_call(tool_name, args)
        # Handle tool-result content
        elif isinstance(block_content, dict) and "result" in block_content:
            tool_name = block_content.get("toolName", "unknown")
            return f"[Tool result: {tool_name}]"

    # Block not handled by this function
    return safe_extract_text(block)


def extract_text_content(content: Any) -> str:
    """
    Extract text content from various message content formats.
    Uses safe extraction with fallback for unparseable content.

    Handles special blocks like tool calls inline for better readability.
    """
    # Handle special cases that need inline formatting (tool calls, etc)
    if isinstance(content, list):
        # Check if any blocks need special handling
        if any(_is_special_block(block) for block in content):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    formatted = _format_special_block(block)
                    if formatted is not None:
                        # Skip empty strings and UNABLE_TO_PARSE markers from non-text blocks
                        if formatted and not formatted.startswith("[UNABLE_TO_PARSE"):
                            text_parts.append(formatted)
                # Handle non-dict items in list
                elif isinstance(block, str):
                    text_parts.append(block)

            if text_parts:
                return "\n\n".join(text_parts)

    # Use safe extraction for non-special content (handles type labels for text/reasoning/etc)
    return safe_extract_text(content)


def format_input_messages(ai_input: Any, options: FormatterOptions | None = None) -> list[str]:
    """Format input messages section."""
    lines: list[str] = []

    if not ai_input or (isinstance(ai_input, list) and len(ai_input) == 0):
        return lines

    lines.append("")
    lines.append("INPUT:")

    # Handle simple string input
    if isinstance(ai_input, str):
        lines.append("")
        content_lines, _ = truncate_content(ai_input, options)
        lines.extend(content_lines)
        return lines

    # Handle array of message objects
    if isinstance(ai_input, list):
        for i, msg in enumerate(ai_input):
            if not isinstance(msg, dict):
                continue

            role = msg.get("role") or msg.get("type") or "unknown"
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            lines.append("")
            lines.append(f"[{i + 1}] {role.upper()}")
            lines.append("")

            if content:
                text_content = extract_text_content(content)
                if text_content:
                    content_lines, _ = truncate_content(text_content, options)
                    lines.extend(content_lines)

            if tool_calls:
                lines.append("")
                lines.extend(format_tool_calls(tool_calls))

            # Add separator between messages (but not after the last one)
            if i < len(ai_input) - 1:
                lines.append("")
                lines.append("-" * 80)

        return lines

    # Unknown format - show raw with data preservation
    lines.append("")
    lines.append(f"[Unparsed input format: {type(ai_input).__name__}]")
    json_repr = json.dumps(ai_input)
    if len(json_repr) > MAX_UNPARSED_DISPLAY_LENGTH:
        json_repr = json_repr[:MAX_UNPARSED_DISPLAY_LENGTH] + "..."
    lines.append(json_repr)

    return lines


def format_output_messages(
    ai_output: Any, ai_output_choices: Any, options: FormatterOptions | None = None
) -> list[str]:
    """Format output messages section."""
    lines: list[str] = []

    # Simple string output
    if ai_output and isinstance(ai_output, str):
        lines.append("")
        lines.append("OUTPUT:")
        lines.append("")
        content_lines, _ = truncate_content(ai_output, options)
        lines.extend(content_lines)
        return lines

    # Extract choices array if wrapped in an object (e.g., xai format: {choices: [...]})
    choices = ai_output_choices
    if ai_output_choices and isinstance(ai_output_choices, dict) and "choices" in ai_output_choices:
        if isinstance(ai_output_choices["choices"], list):
            choices = ai_output_choices["choices"]

    # Output choices (most common format)
    if choices and isinstance(choices, list) and len(choices) > 0:
        lines.append("")
        lines.append("OUTPUT:")

        for i, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue

            # Extract message from choice
            # Handle both OpenAI format (choice.message) and Anthropic format (choice is the message)
            message = choice.get("message")
            if not message or not isinstance(message, dict):
                # Anthropic/direct format - choice IS the message
                if "role" in choice or "content" in choice:
                    message = choice
                else:
                    continue

            role = message.get("role", "assistant")
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            # Extract tool calls from content if present
            content_tool_calls = extract_tool_calls_from_content(content)
            if content_tool_calls:
                tool_calls = content_tool_calls

            lines.append("")
            lines.append(f"[{i + 1}] {role.upper()}")
            lines.append("")

            if content:
                text_content = extract_text_content(content)
                if text_content:
                    content_lines, _ = truncate_content(text_content, options)
                    lines.extend(content_lines)

            if tool_calls:
                lines.append("")
                lines.extend(format_tool_calls(tool_calls))

        return lines

    # Fallback - no recognizable output format
    return lines
