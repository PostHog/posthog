"""
Format input and output messages for text view.

Ports TypeScript messageFormatter.ts to Python for pure Python text repr implementation.
"""

import json
import base64
from typing import Any, TypedDict
from urllib.parse import quote


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
    max_length = options.get("truncate_buffer", 1000)  # Default: 1000
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
    """
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
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(item["text"])
                elif "text" in item:
                    text_parts.append(str(item["text"]))
            elif isinstance(item, str):
                text_parts.append(item)
        if text_parts:
            return "\n".join(text_parts)

    # Fallback
    return f"[UNABLE_TO_PARSE: {type(content).__name__}]"


def extract_text_content(content: Any) -> str:
    """
    Extract text content from various message content formats.
    Uses safe extraction with fallback for unparseable content.
    """
    # Use safe extraction
    extracted = safe_extract_text(content)

    # Handle special cases that need inline formatting
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # Skip tool-call and function blocks as they'll be handled separately
                if block.get("type") in ("tool-call", "function"):
                    continue

                # Handle tool-call content for inline display
                if "content" in block:
                    block_content = block["content"]
                    if isinstance(block_content, dict) and "toolName" in block_content:
                        tool_name = block_content.get("toolName", "unknown")
                        args = block_content.get("args", "")
                        text_parts.append(format_single_tool_call(tool_name, args))
                        continue
                    # Handle tool-result content
                    elif isinstance(block_content, dict) and "result" in block_content:
                        tool_name = block_content.get("toolName", "unknown")
                        text_parts.append(f"[Tool result: {tool_name}]")
                        continue

                # Handle tool_use type (Anthropic format)
                if block.get("type") == "tool_use":
                    text_parts.append(f"[Tool use: {block.get('name', 'unknown')}]")
                    continue

            # For regular blocks, use safe extraction
            block_text = safe_extract_text(block)
            if block_text and not block_text.startswith("[UNABLE_TO_PARSE"):
                text_parts.append(block_text)

        if text_parts:
            return "\n".join(text_parts)

    return extracted


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
        lines.append("[User input]")
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

    # Unknown format - show raw
    lines.append("")
    lines.append(f"[Unparsed input format: {type(ai_input).__name__}]")
    lines.append(json.dumps(ai_input)[:500])

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
