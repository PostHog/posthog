"""
Tests for event_formatter.py - main event formatting logic.

Tests cover error formatting with various input types including JSON strings,
dicts, nested structures, and plain text.
"""

import json
from datetime import datetime

from ..event_formatter import (
    _dict_to_yaml_lines,
    format_embedding_text_repr,
    format_event_text_repr_from_ai_events_row,
    format_generation_text_repr,
)


class TestDictToYamlLines:
    """Test YAML-like formatting helper function."""

    def test_simple_dict(self):
        """Should format simple key-value pairs."""
        obj = {"key1": "value1", "key2": "value2"}
        lines = _dict_to_yaml_lines(obj)
        assert lines == ["key1: value1", "key2: value2"]

    def test_nested_dict(self):
        """Should format nested dictionaries with indentation."""
        obj = {"outer": {"inner": "value"}}
        lines = _dict_to_yaml_lines(obj)
        assert lines == ["outer:", "  inner: value"]

    def test_list_of_primitives(self):
        """Should format lists with dash prefix."""
        obj = {"items": ["item1", "item2"]}
        lines = _dict_to_yaml_lines(obj)
        assert lines == ["items:", "  - item1", "  - item2"]

    def test_list_of_dicts(self):
        """Should format list of dicts with proper structure."""
        obj = {"items": [{"name": "item1"}, {"name": "item2"}]}
        lines = _dict_to_yaml_lines(obj)
        assert lines == ["items:", "  -", "    name: item1", "  -", "    name: item2"]

    def test_deeply_nested_structure(self):
        """Should handle multiple levels of nesting."""
        obj = {"level1": {"level2": {"level3": "value"}}}
        lines = _dict_to_yaml_lines(obj)
        assert lines == ["level1:", "  level2:", "    level3: value"]

    def test_mixed_types(self):
        """Should handle mixed types (strings, numbers, booleans, None)."""
        obj = {"str": "text", "num": 42, "bool": True, "null": None}
        lines = _dict_to_yaml_lines(obj)
        assert "str: text" in lines
        assert "num: 42" in lines
        assert "bool: True" in lines
        assert "null: None" in lines


class TestErrorFormattingGeneration:
    """Test error formatting in generation events."""

    def test_error_with_json_string(self):
        """Should parse and format JSON string errors as YAML."""
        error_dict = {
            "status": 400,
            "message": "Invalid parameter",
            "code": "invalid_request",
        }
        error_json = json.dumps(error_dict)

        event = {"properties": {"$ai_error": error_json, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        # Check that error section is present
        assert "ERROR:" in result
        # Check YAML formatting
        assert "status: 400" in result
        assert "message: Invalid parameter" in result
        assert "code: invalid_request" in result

    def test_error_with_nested_json_string(self):
        """Should handle nested error structures from OpenAI/Anthropic."""
        error_dict = {
            "status": 400,
            "error": {
                "message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
                "type": "invalid_request_error",
                "param": "max_tokens",
                "code": "unsupported_parameter",
            },
            "code": "unsupported_parameter",
        }
        error_json = json.dumps(error_dict)

        event = {"properties": {"$ai_error": error_json, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert "status: 400" in result
        assert "error:" in result
        assert "message: Unsupported parameter" in result
        assert "type: invalid_request_error" in result

    def test_error_with_dict_directly(self):
        """Should format dict errors (not JSON strings)."""
        error_dict = {"message": "Connection timeout", "code": 503}

        event = {"properties": {"$ai_error": error_dict, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert "message: Connection timeout" in result
        assert "code: 503" in result

    def test_error_with_plain_string(self):
        """Should handle plain string errors gracefully."""
        error_string = "Connection timeout after 30 seconds"

        event = {"properties": {"$ai_error": error_string, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert error_string in result

    def test_error_with_invalid_json_string(self):
        """Should fall back to plain string for invalid JSON."""
        error_string = "Not valid JSON: {broken"

        event = {"properties": {"$ai_error": error_string, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert error_string in result

    def test_error_is_true_without_error_value(self):
        """Should show generic message when is_error=True but no error value."""
        event = {"properties": {"$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert "An error occurred (no details available)" in result

    def test_error_with_complex_nested_structure(self):
        """Should handle complex nested error structures with arrays."""
        error_dict = {
            "message": "Multiple validation errors",
            "errors": [
                {"field": "temperature", "message": "Must be between 0 and 2"},
                {"field": "max_tokens", "message": "Must be positive"},
            ],
        }
        error_json = json.dumps(error_dict)

        event = {"properties": {"$ai_error": error_json, "$ai_is_error": True}}
        result = format_generation_text_repr(event)

        assert "ERROR:" in result
        assert "message: Multiple validation errors" in result
        assert "errors:" in result
        # Check list formatting
        assert "- field: temperature" in result.replace("\n", " ") or "field: temperature" in result

    def test_no_error_section_when_no_error(self):
        """Should not show error section when no error present."""
        event = {"properties": {"$ai_model": "gpt-4"}}
        result = format_generation_text_repr(event)

        assert "ERROR:" not in result


class TestErrorFormattingEmbedding:
    """Test error formatting in embedding events."""

    def test_embedding_error_with_json_string(self):
        """Should format errors in embedding events same as generation."""
        error_dict = {"status": 500, "message": "Internal server error"}
        error_json = json.dumps(error_dict)

        event = {"properties": {"$ai_error": error_json, "$ai_is_error": True}}
        result = format_embedding_text_repr(event)

        assert "ERROR:" in result
        assert "status: 500" in result
        assert "message: Internal server error" in result

    def test_embedding_error_with_plain_string(self):
        """Should handle plain string errors in embeddings."""
        error_string = "Rate limit exceeded"

        event = {"properties": {"$ai_error": error_string, "$ai_is_error": True}}
        result = format_embedding_text_repr(event)

        assert "ERROR:" in result
        assert error_string in result


class TestFormatEventTextReprFromAiEventsRow:
    """Adapter for callers reading the ai_events dedicated-column shape.

    Heavy columns (`input` / `output` / `output_choices` / `tools` / state)
    are stored on `posthog.ai_events` as JSON-encoded strings. The shared
    formatter wants parsed structures, so this adapter handles the decode and
    builds the `properties` dict the existing formatters expect.
    """

    def test_decodes_json_input_and_output(self):
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
                "input": '[{"role":"user","content":"hi"}]',
                "output": '"hello"',
            }
        )
        assert "INPUT:" in result
        assert "hi" in result
        assert "OUTPUT:" in result
        assert "hello" in result

    def test_decodes_output_choices_dict_shape(self):
        """`format_output_messages` requires `$ai_output_choices` as a parsed
        list/dict — a raw JSON string would silently render nothing."""
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
                "input": '[{"role":"user","content":"hi"}]',
                "output_choices": '[{"message":{"role":"assistant","content":"choice content"}}]',
            }
        )
        assert "choice content" in result

    def test_decodes_tools(self):
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
                "tools": '[{"type":"function","function":{"name":"lookup","description":"finds things"}}]',
                "input": '[{"role":"user","content":"go"}]',
            }
        )
        assert "lookup" in result

    def test_passes_invalid_json_string_through(self):
        """A non-JSON heavy value (e.g. plain text input) should still render —
        the adapter falls back to the raw string."""
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
                "input": "plain text prompt",
            }
        )
        assert "plain text prompt" in result

    def test_renders_error_section_from_dedicated_columns(self):
        """`is_error` / `error` come from native columns, not properties — the
        adapter must surface them as `$ai_is_error` / `$ai_error` so the
        existing error section fires."""
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
                "is_error": 1,
                "error": "boom",
            }
        )
        assert "ERROR:" in result
        assert "boom" in result

    def test_skips_missing_columns(self):
        """A row that omits all heavy/error fields renders empty (no exception)."""
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_generation",
                "timestamp": datetime(2026, 4, 27),
            }
        )
        assert "INPUT:" not in result
        assert "OUTPUT:" not in result
        assert "ERROR:" not in result

    def test_dispatches_to_embedding_formatter_for_embedding_event(self):
        """Adapter passes through to `format_event_text_repr` which routes by
        event type — confirm `$ai_embedding` still ends up at the embedding
        formatter (so its OUTPUT placeholder still appears)."""
        result = format_event_text_repr_from_ai_events_row(
            {
                "uuid": "u1",
                "event": "$ai_embedding",
                "timestamp": datetime(2026, 4, 27),
                "input": '"text to embed"',
            }
        )
        assert "Embedding vector generated" in result
        assert "text to embed" in result
