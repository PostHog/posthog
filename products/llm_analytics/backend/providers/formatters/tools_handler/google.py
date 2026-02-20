from typing import Any

from .base import ToolFormatter
from .models import Tool


class GoogleToolFormatter(ToolFormatter):
    """Google tool format: wrapped or direct function declarations"""

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
        """Parse wrapped Google format with functionDeclarations"""
        return [
            Tool(
                name=func_decl["name"],
                description=func_decl.get("description", ""),
                parameters=func_decl.get("parameters", {"type": "object", "properties": {}}),
            )
            for func_decl in tool_data["functionDeclarations"]
        ]

    def _parse_direct(self, tool_data: dict[str, Any]) -> Tool:
        """Parse direct Google format"""
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
                "parameters": self._clean_schema_for_google(tool.parameters),
            }
            for tool in tools
        ]
        return [{"functionDeclarations": function_declarations}]

    def _clean_schema_for_google(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Clean JSON Schema to be compatible with Google's OpenAPI 3.0 format"""
        forbidden_fields = {"$schema", "additionalProperties", "$id", "$ref", "definitions", "$defs"}

        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key in forbidden_fields:
                continue

            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_google(value)
            elif isinstance(value, list):
                cleaned_list = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned_list.append(self._clean_schema_for_google(item))
                    else:
                        cleaned_list.append(item)
                cleaned[key] = cleaned_list
            else:
                cleaned[key] = value

        return cleaned


# Backward compatibility for older imports.
GeminiToolFormatter = GoogleToolFormatter
