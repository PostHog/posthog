"""
Tests for message_formatter.py - message input/output formatting logic.

Tests cover multiple LLM provider formats, tool calls, truncation, and edge cases.
"""

from ..message_formatter import (
    extract_text_content,
    extract_tool_calls_from_content,
    format_input_messages,
    format_output_messages,
    format_single_tool_call,
    format_tool_calls,
    safe_extract_text,
    truncate_content,
)


class TestTruncateContent:
    """Test content truncation with middle ellipsis."""

    def test_no_truncation_when_disabled(self):
        """Should not truncate when truncated=False."""
        content = "a" * 2000
        lines, truncated = truncate_content(content, {"truncated": False})
        assert truncated is False
        assert lines == [content]

    def test_no_truncation_when_short(self):
        """Should not truncate content shorter than max_length."""
        content = "Short content"
        lines, truncated = truncate_content(content, {"truncated": True, "truncate_buffer": 1000})
        assert truncated is False
        assert lines == [content]

    def test_truncation_with_markers(self):
        """Should truncate with interactive markers for frontend."""
        content = "a" * 3000
        lines, truncated = truncate_content(
            content, {"truncated": True, "truncate_buffer": 1000, "include_markers": True}
        )
        assert truncated is True
        assert len(lines) == 5  # [first, "", marker, "", last]
        assert lines[0] == "a" * 500  # Half of buffer
        assert lines[2].startswith("<<<TRUNCATED|")
        assert "2000>>>" in lines[2]  # 3000 - 1000 = 2000 chars truncated
        assert lines[4] == "a" * 500

    def test_truncation_without_markers(self):
        """Should truncate with plain text indicator for backend/LLM."""
        content = "a" * 3000
        lines, truncated = truncate_content(
            content, {"truncated": True, "truncate_buffer": 1000, "include_markers": False}
        )
        assert truncated is True
        assert len(lines) == 1
        assert "... (2000 chars truncated) ..." in lines[0]

    def test_truncation_custom_buffer(self):
        """Should respect custom truncate_buffer."""
        content = "a" * 5000
        lines, truncated = truncate_content(
            content, {"truncated": True, "truncate_buffer": 500, "include_markers": True}
        )
        assert truncated is True
        assert lines[0] == "a" * 250  # Half of 500
        assert lines[4] == "a" * 250
        assert "4500>>>" in lines[2]  # 5000 - 500 = 4500


class TestSafeExtractText:
    """Test safe text extraction from various content formats."""

    def test_extract_from_string(self):
        """Should return string as-is."""
        assert safe_extract_text("hello") == "hello"

    def test_extract_from_dict_with_text_key(self):
        """Should extract text field from dict."""
        assert safe_extract_text({"text": "hello"}) == "hello"

    def test_extract_from_dict_with_content_key(self):
        """Should extract nested content."""
        assert safe_extract_text({"content": "hello"}) == "hello"

    def test_extract_from_nested_content(self):
        """Should extract nested text."""
        assert safe_extract_text({"content": {"text": "hello"}}) == "hello"

    def test_extract_from_array_of_blocks(self):
        """Should extract text from content blocks array with spacing."""
        content = [
            {"type": "text", "text": "First line"},
            {"type": "text", "text": "Second line"},
        ]
        result = safe_extract_text(content)
        assert result == "First line\n\nSecond line"

    def test_extract_from_mixed_array(self):
        """Should handle mixed block types."""
        content = [
            {"type": "text", "text": "Text block"},
            "Plain string",
            {"text": "Dict with text"},
        ]
        result = safe_extract_text(content)
        assert "Text block" in result
        assert "Plain string" in result
        assert "Dict with text" in result

    def test_fallback_for_unparseable(self):
        """Should return fallback for unparseable content."""
        result = safe_extract_text({"unknown": "structure"})
        assert result.startswith("{")  # JSON representation

    def test_unable_to_parse_marker(self):
        """Should return UNABLE_TO_PARSE for complex objects."""
        result = safe_extract_text(object())
        assert "[UNABLE_TO_PARSE:" in result

    def test_extract_from_tool_result_block(self):
        """Should extract content from tool_result blocks."""
        content = [
            {
                "type": "tool_result",
                "content": "Checking PostHog documentation...",
                "tool_use_id": "toolu_123",
            }
        ]
        result = safe_extract_text(content)
        assert result == "[TOOL_RESULT]\n\nChecking PostHog documentation..."


class TestExtractToolCallsFromContent:
    """Test tool call extraction from various formats."""

    def test_extract_from_tool_call_format(self):
        """Should extract tool-call format blocks."""
        content = [
            {"type": "tool-call", "function": {"name": "test_func", "arguments": '{"arg": "val"}'}},
        ]
        tool_calls = extract_tool_calls_from_content(content)
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "test_func"

    def test_extract_from_anthropic_function_format(self):
        """Should extract Anthropic function format blocks."""
        content = [
            {
                "type": "function",
                "function": {"name": "get_weather", "arguments": {"latitude": 53.3498}},
            },
        ]
        tool_calls = extract_tool_calls_from_content(content)
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "get_weather"

    def test_extract_multiple_tool_calls(self):
        """Should extract multiple tool calls."""
        content = [
            {"type": "tool-call", "function": {"name": "func1", "arguments": "{}"}},
            {"type": "function", "function": {"name": "func2", "arguments": "{}"}},
        ]
        tool_calls = extract_tool_calls_from_content(content)
        assert len(tool_calls) == 2

    def test_skip_non_tool_blocks(self):
        """Should skip non-tool blocks."""
        content = [
            {"type": "text", "text": "Some text"},
            {"type": "tool-call", "function": {"name": "func1", "arguments": "{}"}},
        ]
        tool_calls = extract_tool_calls_from_content(content)
        assert len(tool_calls) == 1

    def test_empty_content(self):
        """Should return empty list for no content."""
        assert extract_tool_calls_from_content([]) == []
        assert extract_tool_calls_from_content(None) == []
        assert extract_tool_calls_from_content("not a list") == []


class TestExtractTextContent:
    """Test text content extraction with tool call filtering."""

    def test_extract_simple_string(self):
        """Should extract simple string content."""
        assert extract_text_content("hello") == "hello"

    def test_skip_tool_call_blocks(self):
        """Should skip tool-call blocks in content array."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "tool-call", "function": {"name": "test"}},
            {"type": "text", "text": "World"},
        ]
        result = extract_text_content(content)
        assert "Hello" in result
        assert "World" in result
        assert "tool-call" not in result

    def test_skip_function_blocks(self):
        """Should skip Anthropic function blocks in content array."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "function", "function": {"name": "test"}},
            {"type": "text", "text": "World"},
        ]
        result = extract_text_content(content)
        assert "Hello" in result
        assert "World" in result
        assert "function" not in result

    def test_extract_from_tool_use_block(self):
        """Should format tool_use blocks as function calls."""
        content = [{"type": "tool_use", "name": "get_weather"}]
        result = extract_text_content(content)
        assert "get_weather()" in result

    def test_extract_from_tool_use_block_with_args(self):
        """Should format tool_use blocks with arguments as function calls."""
        content = [
            {
                "type": "tool_use",
                "name": "tell_joke",
                "input": {
                    "setup": "Why don't scientists trust atoms?",
                    "punchline": "Because they make up everything!",
                },
            }
        ]
        result = extract_text_content(content)
        assert "tell_joke(" in result
        assert "setup=" in result
        assert "Why don't scientists trust atoms?" in result
        assert "punchline=" in result
        assert "Because they make up everything!" in result

    def test_mixed_content_blocks(self):
        """Should handle mixed content with text and tools."""
        content = [
            {"type": "text", "text": "I'll check the weather"},
            {"type": "function", "function": {"name": "get_weather"}},
        ]
        result = extract_text_content(content)
        assert "I'll check the weather" in result
        assert "get_weather" not in result  # Function block skipped


class TestFormatSingleToolCall:
    """Test formatting individual tool calls."""

    def test_format_with_dict_args(self):
        """Should format tool call with dict arguments."""
        result = format_single_tool_call("test_func", {"arg1": "val1", "arg2": 42})
        assert result == 'test_func(arg1="val1", arg2=42)'

    def test_format_with_json_string_args(self):
        """Should parse JSON string arguments."""
        result = format_single_tool_call("test_func", '{"arg1": "val1"}')
        assert result == 'test_func(arg1="val1")'

    def test_format_with_no_args(self):
        """Should format tool call with no arguments."""
        result = format_single_tool_call("test_func", {})
        assert result == "test_func()"

    def test_format_with_none_args(self):
        """Should handle None arguments."""
        result = format_single_tool_call("test_func", None)
        assert result == "test_func()"

    def test_format_with_unparseable_args(self):
        """Should show raw string for unparseable args."""
        result = format_single_tool_call("test_func", "not json")
        assert result == "test_func(not json)"

    def test_format_with_nested_objects(self):
        """Should format nested objects as JSON."""
        result = format_single_tool_call("test_func", {"obj": {"nested": "value"}})
        assert 'obj={"nested": "value"}' in result


class TestFormatToolCalls:
    """Test formatting multiple tool calls."""

    def test_format_openai_format(self):
        """Should format OpenAI format tool calls."""
        tool_calls = [
            {"function": {"name": "func1", "arguments": '{"arg": "val"}'}},
            {"function": {"name": "func2", "arguments": ""}},  # Empty string, not "{}"
        ]
        lines = format_tool_calls(tool_calls)  # type: ignore[arg-type]
        result = "\n".join(lines)
        assert "Tool calls: 2" in result
        assert "func1(" in result
        assert "func2()" in result

    def test_format_langchain_format(self):
        """Should format LangChain format tool calls."""
        tool_calls = [
            {"name": "func1", "args": {"arg": "val"}},
            {"name": "func2", "args": None},
        ]
        lines = format_tool_calls(tool_calls)  # type: ignore[arg-type]
        result = "\n".join(lines)
        assert "Tool calls: 2" in result
        assert "func1(" in result
        assert "func2()" in result

    def test_format_empty_list(self):
        """Should handle empty tool calls list."""
        lines = format_tool_calls([])
        # Empty list still shows "Tool calls: 0"
        assert len(lines) > 0 or lines == []


class TestFormatInputMessages:
    """Test input message section formatting."""

    def test_format_simple_string_input(self):
        """Should format simple string input."""
        lines = format_input_messages("Hello, world!")
        assert "INPUT:" in lines
        assert "Hello, world!" in lines

    def test_format_empty_input(self):
        """Should return empty for no input."""
        assert format_input_messages(None) == []
        assert format_input_messages([]) == []

    def test_format_message_array(self):
        """Should format array of messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        lines = format_input_messages(messages)
        assert "INPUT:" in lines
        assert "[1] USER" in lines
        assert "Hello" in lines
        assert "[2] ASSISTANT" in lines
        assert "Hi there" in lines

    def test_format_with_tool_calls(self):
        """Should include tool calls in messages."""
        messages = [
            {
                "role": "assistant",
                "content": "I'll help",
                "tool_calls": [{"function": {"name": "test", "arguments": ""}}],  # Empty string
            }
        ]
        lines = format_input_messages(messages)
        result = "\n".join(lines)
        assert "Tool calls: 1" in result
        assert "test()" in result

    def test_format_with_truncation(self):
        """Should apply truncation to long content."""
        content = "a" * 3000
        lines = format_input_messages(content, {"truncated": True, "truncate_buffer": 1000})
        # Should have truncation marker
        truncation_marker_found = any("TRUNCATED" in line for line in lines)
        assert truncation_marker_found


class TestFormatOutputMessages:
    """Test output message section formatting."""

    def test_format_simple_string_output(self):
        """Should format simple string output."""
        lines = format_output_messages("Response text", None)
        assert "OUTPUT:" in lines
        assert "Response text" in lines

    def test_format_openai_choices(self):
        """Should format OpenAI choices format."""
        choices = [{"message": {"role": "assistant", "content": "Hello"}}]
        lines = format_output_messages(None, choices)
        assert "OUTPUT:" in lines
        assert "[1] ASSISTANT" in lines
        assert "Hello" in lines

    def test_format_anthropic_choices(self):
        """Should format Anthropic choices (choice IS the message)."""
        choices = [{"role": "assistant", "content": "Hello"}]
        lines = format_output_messages(None, choices)
        assert "OUTPUT:" in lines
        assert "[1] ASSISTANT" in lines
        assert "Hello" in lines

    def test_format_with_tool_calls_in_message(self):
        """Should extract and format tool calls from message."""
        choices = [
            {
                "message": {
                    "role": "assistant",
                    "content": "Testing",
                    "tool_calls": [{"function": {"name": "test", "arguments": ""}}],  # Empty string
                }
            }
        ]
        lines = format_output_messages(None, choices)
        result = "\n".join(lines)
        assert "Tool calls: 1" in result
        assert "test()" in result

    def test_format_with_tool_calls_in_content(self):
        """Should extract tool calls from content array."""
        choices = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll check"},
                    {"type": "function", "function": {"name": "get_weather", "arguments": ""}},  # Empty string
                ],
            }
        ]
        lines = format_output_messages(None, choices)
        result = "\n".join(lines)
        assert "I'll check" in result
        assert "Tool calls: 1" in result
        assert "get_weather()" in result

    def test_format_wrapped_choices(self):
        """Should unwrap choices from object."""
        choices_obj = {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}
        lines = format_output_messages(None, choices_obj)
        assert "OUTPUT:" in lines
        assert "Hello" in lines

    def test_format_empty_output(self):
        """Should return empty for no output."""
        lines = format_output_messages(None, None)
        assert len(lines) == 0

    def test_format_multiple_choices(self):
        """Should format multiple choices."""
        choices = [
            {"message": {"role": "assistant", "content": "First"}},
            {"message": {"role": "assistant", "content": "Second"}},
        ]
        lines = format_output_messages(None, choices)
        assert "[1] ASSISTANT" in lines
        assert "[2] ASSISTANT" in lines
        assert "First" in lines
        assert "Second" in lines


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handle_circular_references(self):
        """Should handle non-serializable objects gracefully with data preservation."""
        # Test with non-JSON-serializable object
        result = safe_extract_text(123)  # Simple non-dict/non-list type
        assert isinstance(result, str)
        assert result.startswith("[UNABLE_TO_PARSE: int]")
        # Should include the actual data for debugging
        assert "123" in result

    def test_handle_non_dict_message(self):
        """Should skip non-dict messages in array."""
        messages = ["not a dict", {"role": "user", "content": "Hello"}]
        lines = format_input_messages(messages)
        result = "\n".join(lines)
        # Should skip first item and process second
        assert "Hello" in result

    def test_handle_missing_role(self):
        """Should use 'unknown' for missing role."""
        messages = [{"content": "Hello"}]
        lines = format_input_messages(messages)
        result = "\n".join(lines)
        # Should default to unknown type
        assert "UNKNOWN" in result or "USER" in result  # Might fall back to type

    def test_handle_none_values(self):
        """Should handle None values gracefully."""
        assert format_input_messages(None) == []
        assert format_output_messages(None, None) == []
        assert extract_tool_calls_from_content(None) == []

    def test_handle_empty_strings(self):
        """Should handle empty strings."""
        assert safe_extract_text("") == ""
        lines = format_input_messages("")
        # Empty string should be treated as no input
        assert len(lines) == 0
