from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class Tool:
    """Internal representation of a tool/function"""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolFormat(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"


class ToolFormatter(ABC):
    """Abstract base class for tool format parsers and serializers"""

    @abstractmethod
    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        """Check if this formatter can parse the given tool data"""
        pass

    @abstractmethod
    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        """Parse tool data into internal Tool objects"""
        pass

    @abstractmethod
    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        """Serialize Tool objects into format-specific data"""
        pass


class OpenAIToolFormatter(ToolFormatter):
    """OpenAI tool format: {"type": "function", "function": {...}}"""

    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        return (
            tool_data.get("type") == "function"
            and "function" in tool_data
            and "name" in tool_data["function"]
            and "parameters" in tool_data["function"]
        )

    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        return [
            Tool(
                name=tool_data["function"]["name"],
                description=tool_data["function"].get("description", ""),
                parameters=tool_data["function"]["parameters"],
            )
            for tool_data in tools_data
        ]

    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]


class AnthropicToolFormatter(ToolFormatter):
    """Anthropic tool format: {"name": ..., "description": ..., "input_schema": ...}"""

    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        return "name" in tool_data and "input_schema" in tool_data

    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        return [
            Tool(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                parameters=tool_data["input_schema"],
            )
            for tool_data in tools_data
        ]

    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]


class GeminiToolFormatter(ToolFormatter):
    """Gemini tool format: wrapped or direct function declarations"""

    def can_parse(self, tool_data: dict[str, Any]) -> bool:
        # Wrapped format
        if "functionDeclarations" in tool_data:
            return True
        # Direct format (has name but not input_schema to distinguish from Anthropic)
        return "name" in tool_data and "input_schema" not in tool_data

    def parse(self, tools_data: list[dict[str, Any]]) -> list[Tool]:
        tools = []
        for tool_data in tools_data:
            if "functionDeclarations" in tool_data:
                tools.extend(self._parse_wrapped(tool_data))
            else:
                tools.append(self._parse_direct(tool_data))
        return tools

    def _parse_wrapped(self, tool_data: dict[str, Any]) -> list[Tool]:
        """Parse wrapped Gemini format with functionDeclarations"""
        return [
            Tool(
                name=func_decl["name"],
                description=func_decl.get("description", ""),
                parameters=func_decl.get("parameters", {"type": "object", "properties": {}}),
            )
            for func_decl in tool_data["functionDeclarations"]
        ]

    def _parse_direct(self, tool_data: dict[str, Any]) -> Tool:
        """Parse direct Gemini format"""
        return Tool(
            name=tool_data["name"],
            description=tool_data.get("description", ""),
            parameters=tool_data.get("parameters", {"type": "object", "properties": {}}),
        )

    def serialize(self, tools: list[Tool]) -> list[dict[str, Any]]:
        function_declarations = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": self._clean_schema_for_gemini(tool.parameters),
            }
            for tool in tools
        ]
        return [{"functionDeclarations": function_declarations}]

    def _clean_schema_for_gemini(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Clean JSON Schema to be compatible with Gemini's OpenAPI 3.0 format"""
        forbidden_fields = {"$schema", "additionalProperties", "$id", "$ref", "definitions", "$defs"}

        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key in forbidden_fields:
                continue

            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_gemini(value)
            elif isinstance(value, list):
                cleaned_list = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned_list.append(self._clean_schema_for_gemini(item))
                    else:
                        cleaned_list.append(item)
                cleaned[key] = cleaned_list
            else:
                cleaned[key] = value

        return cleaned


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
