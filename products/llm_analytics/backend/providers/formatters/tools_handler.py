from typing import Any, Literal

FormatType = Literal["openai", "anthropic", "gemini"]


class LLMToolsHandler:
    def __init__(self, tools_data: dict[str, Any] | list[dict[str, Any]] | None):
        if tools_data is None:
            self.tools_data = None
        elif isinstance(tools_data, dict):
            self.tools_data = list(tools_data.values())
        else:
            self.tools_data = tools_data

    def detect_format(self) -> FormatType | None:
        if self.tools_data is None or not self.tools_data:
            return None

        if not isinstance(self.tools_data, list) or not self.tools_data:
            raise ValueError("Tools data must be a non-empty list")

        first_tool = self.tools_data[0]
        if not isinstance(first_tool, dict):
            raise ValueError("Each tool must be a dictionary")

        # OpenAI format detection
        if "type" in first_tool and first_tool.get("type") == "function":
            if "function" in first_tool:
                function = first_tool["function"]
                if "name" in function and "parameters" in function:
                    return "openai"

        # Anthropic format detection
        if "name" in first_tool and "input_schema" in first_tool:
            return "anthropic"

        # Gemini format detection
        if "functionDeclarations" in first_tool:
            return "gemini"

        # Check if it's a direct function declaration (Gemini style but not wrapped)
        # This includes tools with just name and description, or with parameters
        if "name" in first_tool and "input_schema" not in first_tool:
            return "gemini"

        raise ValueError(f"Unknown tool format: {first_tool}")

    def convert_to(self, format: FormatType) -> list[dict[str, Any]] | None:
        if self.tools_data is None:
            return None

        current_format = self.detect_format()
        if current_format is None:
            return None

        if current_format == format:
            return self.tools_data

        # Convert to OpenAI first, then to target format
        openai_tools = self._convert_to_openai(current_format)

        if format == "openai":
            return openai_tools
        elif format == "anthropic":
            return self._openai_to_anthropic(openai_tools)
        elif format == "gemini":
            return self._openai_to_gemini(openai_tools)

        raise ValueError(f"Unsupported target format: {format}")

    def _convert_to_openai(self, current_format: FormatType) -> list[dict[str, Any]]:
        if current_format == "openai":
            return self.tools_data
        elif current_format == "anthropic":
            return self._anthropic_to_openai(self.tools_data)
        elif current_format == "gemini":
            return self._gemini_to_openai(self.tools_data)

        raise ValueError(f"Unsupported source format: {current_format}")

    def _anthropic_to_openai(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        openai_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            }
            openai_tools.append(openai_tool)
        return openai_tools

    def _gemini_to_openai(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        openai_tools = []
        for tool in tools:
            # Handle wrapped format
            if "functionDeclarations" in tool:
                for func_decl in tool["functionDeclarations"]:
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": func_decl["name"],
                            "description": func_decl.get("description", ""),
                            "parameters": func_decl.get("parameters", {"type": "object", "properties": {}}),
                        },
                    }
                    openai_tools.append(openai_tool)
            else:
                # Direct function declaration format
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                openai_tools.append(openai_tool)
        return openai_tools

    def _openai_to_anthropic(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        anthropic_tools = []
        for tool in tools:
            function = tool["function"]
            anthropic_tool = {
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function["parameters"],
            }
            anthropic_tools.append(anthropic_tool)
        return anthropic_tools

    def _openai_to_gemini(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        function_declarations = []
        for tool in tools:
            function = tool["function"]
            func_decl = {
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": self._clean_schema_for_gemini(function["parameters"]),
            }
            function_declarations.append(func_decl)

        return [{"functionDeclarations": function_declarations}]

    def _clean_schema_for_gemini(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Clean JSON Schema to be compatible with Gemini's OpenAPI 3.0 format"""
        if not isinstance(schema, dict):
            return schema

        # Fields that are not allowed in OpenAPI 3.0/Gemini
        forbidden_fields = {"$schema", "additionalProperties", "$id", "$ref", "definitions", "$defs"}

        cleaned = {}
        for key, value in schema.items():
            if key in forbidden_fields:
                continue

            # Recursively clean nested objects
            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_gemini(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    self._clean_schema_for_gemini(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                cleaned[key] = value

        return cleaned
