"""
Tests for tool_formatter.py - available tools section formatting.

Tests cover array and dictionary formats, multiple provider formats, and edge cases.
"""

from ..tool_formatter import format_tools


class TestFormatTools:
    """Test available tools section formatting."""

    def test_empty_tools(self):
        """Should return empty list for no tools."""
        assert format_tools(None) == []
        assert format_tools([]) == []
        assert format_tools({}) == []

    def test_array_format_openai(self):
        """Should format OpenAI array format tools."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "units": {"type": "string"},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 1" in result
        assert "get_weather(location: string, units?: string)" in result
        assert "Get current weather for a location." in result

    def test_array_format_anthropic(self):
        """Should format Anthropic array format tools."""
        tools = [
            {
                "name": "read_file",
                "description": "Read the contents of a file from the filesystem.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "lines": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 1" in result
        assert "read_file(file_path: string, lines?: string)" in result
        assert "Read the contents of a file from the filesystem." in result

    def test_dictionary_format(self):
        """Should format dictionary format tools (tool_name as key)."""
        tools = {
            "lov-view": {
                "name": "lov-view",
                "description": "Use this tool to read the contents of a file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "example": "src/App.tsx"},
                        "lines": {"type": "string", "example": "1-800, 1001-1500"},
                    },
                    "required": ["file_path"],
                },
            },
            "supabase--migration": {
                "name": "supabase--migration",
                "description": "Create a Supabase migration file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "migration_name": {"type": "string"},
                    },
                    "required": ["migration_name"],
                },
            },
        }
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 2" in result
        assert "lov-view(file_path: string, lines?: string)" in result
        assert "Use this tool to read the contents of a file." in result
        assert "supabase--migration(migration_name: string)" in result
        assert "Create a Supabase migration file." in result

    def test_multiple_tools_array(self):
        """Should format multiple tools in array format."""
        tools = [
            {"name": "tool1", "description": "First tool."},
            {"name": "tool2", "description": "Second tool."},
            {"name": "tool3", "description": "Third tool."},
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 3" in result
        assert "tool1()" in result
        assert "tool2()" in result
        assert "tool3()" in result

    def test_tool_with_no_parameters(self):
        """Should format tool with no parameters."""
        tools = [
            {
                "name": "ping",
                "description": "Check if service is alive.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "ping()" in result

    def test_tool_with_all_required_params(self):
        """Should format tool with all required parameters."""
        tools = [
            {
                "name": "create_user",
                "description": "Create a new user.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["username", "email"],
                },
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "create_user(username: string, email: string)" in result

    def test_tool_with_no_description(self):
        """Should handle tool with no description."""
        tools = [{"name": "mystery_tool", "input_schema": {"type": "object", "properties": {}}}]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "mystery_tool()" in result
        # Should not have description line
        assert "N/A" not in result

    def test_tool_with_multiline_description(self):
        """Should show only first line of multiline description."""
        tools = [
            {
                "name": "complex_tool",
                "description": "This is the first sentence.\nThis is the second line.\nThis is the third line.",
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "This is the first sentence." in result
        assert "second line" not in result
        assert "third line" not in result

    def test_google_gemini_format(self):
        """Should handle Google/Gemini functionDeclarations format."""
        tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "search",
                        "description": "Search the web.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                            },
                            "required": ["query"],
                        },
                    }
                ]
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 1" in result
        assert "search(query: string)" in result

    def test_invalid_tool_format(self):
        """Should skip invalid tool entries."""
        tools = [
            "not a dict",
            {"name": "valid_tool", "description": "A valid tool."},
            123,
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "AVAILABLE TOOLS: 3" in result
        assert "valid_tool()" in result

    def test_tool_with_nested_schema(self):
        """Should handle tools with complex nested schemas."""
        tools = [
            {
                "name": "update_config",
                "description": "Update configuration settings.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "config": {"type": "object"},
                        "merge": {"type": "boolean"},
                    },
                    "required": ["config"],
                },
            }
        ]
        lines = format_tools(tools)
        result = "\n".join(lines)
        assert "update_config(config: object, merge?: boolean)" in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_non_dict_non_list_input(self):
        """Should return empty for invalid input types."""
        assert format_tools("string") == []
        assert format_tools(123) == []
        assert format_tools(True) == []

    def test_empty_dictionary(self):
        """Should return empty for empty dictionary."""
        assert format_tools({}) == []

    def test_dictionary_with_invalid_values(self):
        """Should skip non-dict values in dictionary."""
        tools = {
            "tool1": {"name": "tool1", "description": "Valid tool."},
            "tool2": "not a dict",
            "tool3": None,
        }
        lines = format_tools(tools)
        result = "\n".join(lines)
        # Should still process tool1
        assert "AVAILABLE TOOLS:" in result
        assert "tool1()" in result

    def test_tool_without_name(self):
        """Should handle tool without name field."""
        tools = [{"description": "Tool without name"}]
        lines = format_tools(tools)
        result = "\n".join(lines)
        # Should use 'UNKNOWN' or skip
        assert "AVAILABLE TOOLS: 1" in result

    def test_long_tools_list_collapsed_with_markers(self):
        """Should collapse long tool lists (>5) with expandable marker."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(10)]
        lines = format_tools(tools, {"include_markers": True})
        result = "\n".join(lines)
        # Should show expandable marker
        assert "<<<TOOLS_EXPANDABLE|" in result
        assert "AVAILABLE TOOLS: 10" in result
        # Should not show individual tools in output
        assert "tool0()" not in result

    def test_long_tools_list_collapsed_without_markers(self):
        """Should collapse long tool lists (>5) with plain text indicator."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(10)]
        lines = format_tools(tools, {"include_markers": False})
        result = "\n".join(lines)
        # Should show plain text indicator
        assert "[+] AVAILABLE TOOLS: 10" in result
        # Should not show individual tools
        assert "tool0()" not in result

    def test_short_tools_list_not_collapsed(self):
        """Should not collapse short tool lists (<=5)."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(3)]
        lines = format_tools(tools, {"include_markers": True})
        result = "\n".join(lines)
        # Should show full list without expandable marker
        assert "<<<TOOLS_EXPANDABLE|" not in result
        assert "AVAILABLE TOOLS: 3" in result
        assert "tool0()" in result
        assert "tool1()" in result
        assert "tool2()" in result

    def test_exactly_threshold_not_collapsed(self):
        """Should not collapse tool list exactly at threshold (5 tools)."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(5)]
        lines = format_tools(tools, {"include_markers": True})
        result = "\n".join(lines)
        # Should show full list (5 is not > 5)
        assert "<<<TOOLS_EXPANDABLE|" not in result
        assert "AVAILABLE TOOLS: 5" in result
        assert "tool0()" in result

    def test_six_tools_collapsed(self):
        """Should collapse tool list with 6 tools (just over threshold)."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(6)]
        lines = format_tools(tools, {"include_markers": True})
        result = "\n".join(lines)
        # Should be collapsed (6 > 5)
        assert "<<<TOOLS_EXPANDABLE|" in result
        assert "AVAILABLE TOOLS: 6" in result

    def test_custom_collapse_threshold(self):
        """Should respect custom collapse threshold."""
        tools = [{"name": f"tool{i}", "description": f"Tool {i}."} for i in range(3)]
        lines = format_tools(tools, {"include_markers": True, "tools_collapse_threshold": 2})
        result = "\n".join(lines)
        # Should be collapsed with threshold=2 (3 > 2)
        assert "<<<TOOLS_EXPANDABLE|" in result
        assert "AVAILABLE TOOLS: 3" in result
