"""
Tests for trace_formatter.py - trace hierarchy tree rendering logic.

Tests cover tree structure rendering, expandable nodes, ASCII art, and options handling.
"""

from .trace_formatter import (
    _format_cost,
    _format_latency,
    _format_state,
    _get_event_summary,
    _render_tree,
    _truncate_content,
    format_trace_text_repr,
)


class TestFormatHelpers:
    """Test helper formatting functions."""

    def test_format_latency(self):
        """Should format latency to 2 decimal places."""
        assert _format_latency(1.23456) == "1.23s"
        assert _format_latency(0.1) == "0.10s"
        assert _format_latency(10) == "10.00s"

    def test_format_cost(self):
        """Should format cost in USD to 4 decimal places."""
        assert _format_cost(0.0023) == "$0.0023"
        assert _format_cost(1.23456) == "$1.2346"
        assert _format_cost(0) == "$0.0000"


class TestGetEventSummary:
    """Test event summary generation for tree display."""

    def test_generation_summary_full(self):
        """Should create generation summary with all metrics."""
        event = {
            "event": "$ai_generation",
            "properties": {
                "$ai_span_name": "my-generation",
                "$ai_latency": 0.45,
                "$ai_total_cost_usd": 0.0023,
                "$ai_model": "gpt-4",
            },
        }
        summary = _get_event_summary(event)
        assert "my-generation" in summary
        assert "0.45s" in summary
        assert "$0.0023" in summary
        assert "gpt-4" in summary

    def test_generation_summary_minimal(self):
        """Should create generation summary with minimal data."""
        event = {"event": "$ai_generation", "properties": {}}
        summary = _get_event_summary(event)
        assert "generation" in summary

    def test_generation_summary_with_error(self):
        """Should indicate error in generation summary."""
        event = {
            "event": "$ai_generation",
            "properties": {
                "$ai_span_name": "test",
                "$ai_is_error": True,
            },
        }
        summary = _get_event_summary(event)
        assert "ERROR" in summary

    def test_generation_summary_uses_model_as_fallback(self):
        """Should use model as name if no span_name."""
        event = {
            "event": "$ai_generation",
            "properties": {
                "$ai_model": "claude-3",
            },
        }
        summary = _get_event_summary(event)
        assert "claude-3" in summary

    def test_span_summary_full(self):
        """Should create span summary with all metrics."""
        event = {
            "event": "$ai_span",
            "properties": {
                "$ai_span_name": "my-span",
                "$ai_latency": 1.2,
            },
        }
        summary = _get_event_summary(event)
        assert "my-span" in summary
        assert "1.20s" in summary

    def test_span_summary_with_error(self):
        """Should indicate error in span summary."""
        event = {
            "event": "$ai_span",
            "properties": {
                "$ai_span_name": "test",
                "$ai_is_error": True,
            },
        }
        summary = _get_event_summary(event)
        assert "ERROR" in summary

    def test_unknown_event_type(self):
        """Should return event type for unknown events."""
        event = {"event": "custom_event", "properties": {}}
        summary = _get_event_summary(event)
        assert summary == "custom_event"


class TestTruncateContent:
    """Test content truncation for trace tree."""

    def test_no_truncation_when_short(self):
        """Should not truncate short content."""
        lines, truncated = _truncate_content("Short text", max_length=1000)
        assert truncated is False
        assert lines == ["Short text"]

    def test_truncation_with_marker(self):
        """Should truncate long content with marker."""
        content = "a" * 3000
        lines, truncated = _truncate_content(content, max_length=1000)
        assert truncated is True
        assert len(lines) == 5  # [first, "", marker, "", last]
        assert lines[0] == "a" * 500
        assert "<<<TRUNCATED|" in lines[2]
        assert lines[4] == "a" * 500

    def test_truncation_marker_encoding(self):
        """Should properly encode middle content in marker."""
        content = "START" + ("x" * 1000) + "END"
        lines, truncated = _truncate_content(content, max_length=100)
        assert truncated is True
        # Marker should contain encoded middle part
        assert "<<<TRUNCATED|" in lines[2]
        assert ">>>" in lines[2]


class TestFormatState:
    """Test state object formatting."""

    def test_format_empty_state(self):
        """Should return empty for no state."""
        lines = _format_state(None, "TEST")
        assert len(lines) == 0

    def test_format_string_state(self):
        """Should format string state."""
        lines = _format_state("test state", "INPUT")
        assert "INPUT:" in lines
        assert "test state" in lines

    def test_format_dict_state(self):
        """Should format dict as JSON."""
        state = {"key": "value", "num": 42}
        lines = _format_state(state, "STATE")
        assert "STATE:" in lines
        result = "\n".join(lines)
        assert "key" in result
        assert "value" in result

    def test_format_list_state(self):
        """Should format list as JSON."""
        state = ["item1", "item2"]
        lines = _format_state(state, "STATE")
        assert "STATE:" in lines
        result = "\n".join(lines)
        assert "item1" in result

    def test_format_with_truncation(self):
        """Should apply truncation to long state."""
        state = "a" * 3000
        lines = _format_state(state, "STATE")
        # Should have truncation marker (default max_length is 1000)
        result = "\n".join(lines)
        assert "TRUNCATED" in result or "truncated" in result


class TestRenderTree:
    """Test tree structure rendering with ASCII art."""

    def test_render_single_node(self):
        """Should render single node."""
        nodes = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "test"},
                }
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        assert len(lines) > 0
        # Should have tree character and GEN prefix
        assert any("[GEN]" in line for line in lines)
        assert any("└─" in line or "├─" in line for line in lines)

    def test_render_with_children(self):
        """Should render tree with children."""
        nodes = [
            {
                "event": {
                    "id": "span1",
                    "event": "$ai_span",
                    "properties": {"$ai_span_name": "parent"},
                },
                "children": [
                    {
                        "event": {
                            "id": "gen1",
                            "event": "$ai_generation",
                            "properties": {"$ai_span_name": "child"},
                        }
                    }
                ],
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        # Should have both parent and child
        assert any("[SPAN]" in line for line in lines)
        assert any("[GEN]" in line for line in lines)
        # Should have proper indentation for child
        result = "\n".join(lines)
        assert "   " in result or "│" in result  # Indentation or vertical line

    def test_render_multiple_siblings(self):
        """Should render multiple sibling nodes."""
        nodes = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "first"},
                }
            },
            {
                "event": {
                    "id": "gen2",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "second"},
                }
            },
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        # Should have both nodes
        result = "\n".join(lines)
        assert "first" in result
        assert "second" in result
        # First should use ├─ and last should use └─
        assert any("├─" in line for line in lines)
        assert any("└─" in line for line in lines)

    def test_render_collapsed(self):
        """Should render collapsed tree (summary only)."""
        nodes = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "test"},
                }
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": True})
        result = "\n".join(lines)
        # Should show summary but not have expandable marker
        assert "[GEN]" in result
        assert "GEN_EXPANDABLE" not in result

    def test_render_with_markers(self):
        """Should include expandable markers for frontend."""
        nodes = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "test", "$ai_input": "input"},
                }
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        result = "\n".join(lines)
        # Should have GEN_EXPANDABLE marker
        assert "<<<GEN_EXPANDABLE|" in result
        assert "gen1" in result

    def test_render_without_markers(self):
        """Should use plain text for backend/LLM."""
        nodes = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "test"},
                }
            }
        ]
        lines = _render_tree(nodes, {"include_markers": False, "collapsed": False})
        result = "\n".join(lines)
        # Should have [+] indicator instead of marker
        assert "[+]" in result
        assert "GEN_EXPANDABLE" not in result

    def test_render_max_depth(self):
        """Should limit tree depth."""
        # Create deeply nested structure
        nodes = [
            {
                "event": {"id": "1", "event": "$ai_span", "properties": {}},
                "children": [
                    {
                        "event": {"id": "2", "event": "$ai_span", "properties": {}},
                        "children": [
                            {
                                "event": {"id": "3", "event": "$ai_span", "properties": {}},
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False}, depth=0)
        # At depth 10, should show max depth message
        # But our structure is only 3 deep, so should render normally
        result = "\n".join(lines)
        assert "max depth" not in result

    def test_render_deeply_nested(self):
        """Should handle deeply nested structures."""

        def create_nested(depth, id_start=0):
            if depth == 0:
                return []
            return [
                {
                    "event": {"id": f"node{id_start}", "event": "$ai_span", "properties": {}},
                    "children": create_nested(depth - 1, id_start + 1),
                }
            ]

        nodes = create_nested(5)
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        # Should render without error
        assert len(lines) > 0

    def test_render_event_link(self):
        """Should create event links for other event types."""
        nodes = [
            {
                "event": {
                    "id": "custom1",
                    "event": "custom_event",
                    "properties": {},
                }
            }
        ]
        lines = _render_tree(nodes, {"include_markers": True, "collapsed": False})
        result = "\n".join(lines)
        # Should have EVENT_LINK marker
        assert "<<<EVENT_LINK|" in result
        assert "custom1" in result


class TestFormatTraceTextRepr:
    """Test full trace formatting."""

    def test_format_simple_trace(self):
        """Should format trace with header."""
        trace = {
            "properties": {
                "$ai_trace_id": "trace123",
                "$ai_span_name": "my-trace",
                "$ai_latency": 2.5,
            }
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "MY-TRACE" in result
        assert "=" * 80 in result

    def test_format_trace_with_hierarchy(self):
        """Should format trace with event hierarchy."""
        trace = {
            "properties": {
                "$ai_trace_id": "trace123",
                "$ai_span_name": "test-trace",
            }
        }
        hierarchy = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "generation"},
                }
            }
        ]
        result = format_trace_text_repr(trace, hierarchy, {"include_markers": True})
        assert "TRACE HIERARCHY:" in result
        assert "[GEN]" in result
        assert "generation" in result

    def test_format_trace_with_aggregated_metrics(self):
        """Should format trace with cost and token data."""
        trace = {
            "properties": {},
            "total_cost": 0.05,
            "total_tokens": 1500,
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TRACE" in result
        assert "=" * 80 in result

    def test_format_trace_with_error(self):
        """Should show trace-level error."""
        trace = {
            "properties": {
                "$ai_span_name": "test",
                "$ai_error": "Something went wrong",
            }
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TRACE ERROR:" in result
        assert "Something went wrong" in result

    def test_format_trace_with_input_state(self):
        """Should show trace input state."""
        trace = {
            "properties": {
                "$ai_span_name": "test",
                "$ai_input_state": {"query": "test query"},
            }
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TRACE INPUT" in result
        assert "query" in result

    def test_format_trace_with_output_state(self):
        """Should show trace output state."""
        trace = {
            "properties": {
                "$ai_span_name": "test",
                "$ai_output_state": {"result": "success"},
            }
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TRACE OUTPUT" in result
        assert "result" in result

    def test_format_collapsed_trace(self):
        """Should format collapsed trace (summary only)."""
        trace = {"properties": {"$ai_span_name": "test"}}
        hierarchy = [
            {
                "event": {
                    "id": "gen1",
                    "event": "$ai_generation",
                    "properties": {"$ai_span_name": "gen"},
                }
            }
        ]
        result = format_trace_text_repr(trace, hierarchy, {"collapsed": True})
        # Should show tree but not expandable content
        assert "[GEN]" in result
        assert "GEN_EXPANDABLE" not in result

    def test_format_trace_with_session_id(self):
        """Should format trace with session data."""
        trace = {
            "properties": {
                "$ai_span_name": "test",
                "$ai_session_id": "session123",
            }
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TEST" in result
        assert "=" * 80 in result

    def test_format_trace_fallback_trace_id(self):
        """Should format trace with fallback trace_id field."""
        trace = {
            "properties": {"$ai_span_name": "test"},
            "trace_id": "trace456",
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TEST" in result
        assert "=" * 80 in result

    def test_format_trace_camelcase_metrics(self):
        """Should format trace with camelCase metric fields."""
        trace = {
            "properties": {},
            "totalCost": 0.05,
            "totalTokens": 1500,
        }
        hierarchy = []
        result = format_trace_text_repr(trace, hierarchy)
        assert "TRACE" in result
        assert "=" * 80 in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_hierarchy(self):
        """Should handle empty hierarchy."""
        trace = {"properties": {"$ai_span_name": "test"}}
        result = format_trace_text_repr(trace, [])
        assert "TEST" in result
        # Should not crash

    def test_malformed_event(self):
        """Should handle malformed events in hierarchy."""
        trace = {"properties": {"$ai_span_name": "test"}}
        hierarchy = [{"invalid": "structure"}]
        # Should not crash
        result = format_trace_text_repr(trace, hierarchy)
        assert isinstance(result, str)

    def test_none_options(self):
        """Should handle None options."""
        trace = {"properties": {"$ai_span_name": "test"}}
        result = format_trace_text_repr(trace, [], None)
        assert isinstance(result, str)

    def test_missing_properties(self):
        """Should handle missing properties field."""
        trace = {}
        result = format_trace_text_repr(trace, [])
        assert isinstance(result, str)

    def test_complex_error_object(self):
        """Should handle complex error objects."""
        trace = {
            "properties": {
                "$ai_span_name": "test",
                "$ai_error": {"message": "error", "code": 500, "details": {"info": "test"}},
            }
        }
        result = format_trace_text_repr(trace, [])
        assert "TRACE ERROR:" in result
        # Should serialize error object
        assert "message" in result or "error" in result
