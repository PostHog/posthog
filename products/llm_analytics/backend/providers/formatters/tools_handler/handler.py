from typing import Any

from .anthropic import AnthropicToolFormatter
from .gemini import GeminiToolFormatter
from .models import ToolFormat
from .openai import OpenAIToolFormatter


class LLMToolsHandler:
    """Handler for converting between different LLM tool formats"""

    _formatters = {
        ToolFormat.OPENAI: OpenAIToolFormatter(),
        ToolFormat.ANTHROPIC: AnthropicToolFormatter(),
        ToolFormat.GEMINI: GeminiToolFormatter(),
    }

    def __init__(self, tools_data: Any):
        normalized_data = self._normalize_input(tools_data)
        if normalized_data is None:
            self.tools = None
            self.format = None
        else:
            self.format = self._detect_format(normalized_data)
            self.tools = self._formatters[self.format].parse(normalized_data)

    def convert_to(self, format: ToolFormat) -> list[dict[str, Any]] | None:
        """Convert tools to the specified format"""
        if self.tools is None:
            return None

        formatter = self._formatters[format]
        return formatter.serialize(self.tools)

    def _normalize_input(self, tools_data: Any) -> list[dict[str, Any]] | None:
        """Normalize input to a consistent list format"""
        if tools_data is None or tools_data == [] or tools_data == {}:
            return None
        # Some people store tools in a dictionary mapped by id or name, so we extract the values
        if isinstance(tools_data, dict):
            return list(tools_data.values())
        if isinstance(tools_data, list):
            return tools_data
        raise ValueError(f"Tools data is an unknown format: {type(tools_data)}")

    def _detect_format(self, tools_data: list[dict[str, Any]]) -> ToolFormat:
        """Detect which format the tools data uses"""
        first_tool = tools_data[0]
        if not isinstance(first_tool, dict):
            raise ValueError("Each tool must be a dictionary")

        for format_type, formatter in self._formatters.items():
            if formatter.can_parse(first_tool):
                return format_type

        raise ValueError(f"Unknown tool format: {first_tool}")
