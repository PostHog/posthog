"""Tests for line numbering feature."""

from ..event_formatter import format_generation_text_repr
from ..message_formatter import add_line_numbers
from ..trace_formatter import format_trace_text_repr


class TestAddLineNumbers:
    """Test add_line_numbers helper function."""

    def test_add_line_numbers_single_line(self):
        """Should add L1: prefix to single line."""
        text = "Hello world"
        result = add_line_numbers(text)
        assert result == "L1: Hello world"

    def test_add_line_numbers_multiple_lines(self):
        """Should add line numbers with proper padding."""
        text = "Line 1\nLine 2\nLine 3"
        result = add_line_numbers(text)
        lines = result.split("\n")
        assert lines[0] == "L1: Line 1"
        assert lines[1] == "L2: Line 2"
        assert lines[2] == "L3: Line 3"

    def test_add_line_numbers_padding(self):
        """Should pad line numbers consistently."""
        text = "\n".join([f"Line {i}" for i in range(1, 101)])
        result = add_line_numbers(text)
        lines = result.split("\n")
        # First line should be padded: "L  1: Line 1"
        assert lines[0].startswith("L  1:")
        # Line 10 should be: "L 10: Line 10"
        assert lines[9].startswith("L 10:")
        # Line 100 should be: "L100: Line 100"
        assert lines[99].startswith("L100:")

    def test_add_line_numbers_empty_lines(self):
        """Should handle empty lines correctly."""
        text = "Line 1\n\nLine 3"
        result = add_line_numbers(text)
        lines = result.split("\n")
        assert lines[0] == "L1: Line 1"
        assert lines[1] == "L2: "
        assert lines[2] == "L3: Line 3"


class TestLineNumbersInGeneration:
    """Test line numbers in generation event formatting."""

    def test_generation_with_line_numbers(self):
        """Should format generation with line numbers when option enabled."""
        event = {
            "properties": {
                "$ai_input": [{"role": "user", "content": "Hello"}],
                "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
            }
        }
        result = format_generation_text_repr(event, {"include_line_numbers": True})
        lines = result.split("\n")

        # Check that line numbers are present
        assert lines[0].startswith("L")
        assert ":" in lines[0]

        # Check that all lines have line numbers
        for line in lines:
            assert line.startswith("L")

    def test_generation_without_line_numbers(self):
        """Should format generation without line numbers by default."""
        event = {
            "properties": {
                "$ai_input": [{"role": "user", "content": "Hello"}],
                "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
            }
        }
        result = format_generation_text_repr(event, {"include_line_numbers": False})
        # Should not have L1: prefix on first line
        assert not result.startswith("L1:")


class TestLineNumbersInTrace:
    """Test line numbers in trace formatting."""

    def test_trace_with_line_numbers(self):
        """Should format trace with line numbers when option enabled."""
        trace = {
            "id": "trace-1",
            "properties": {"$ai_span_name": "My Trace"},
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy, {"include_line_numbers": True})
        lines = result.split("\n")

        # Check that line numbers are present
        assert lines[0].startswith("L")
        assert ":" in lines[0]

        # First content line should contain trace name
        assert "MY TRACE" in lines[0]

    def test_trace_without_line_numbers(self):
        """Should format trace without line numbers by default."""
        trace = {
            "id": "trace-1",
            "properties": {"$ai_span_name": "My Trace"},
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy, {"include_line_numbers": False})
        # Should not have L1: prefix on first line
        assert not result.startswith("L1:")
        # But should still have trace name
        assert result.startswith("MY TRACE")
