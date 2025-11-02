"""
Format available tools section for text view.

Ports TypeScript toolFormatter.ts to Python for pure Python text repr implementation.
"""

import json
from typing import Any, TypedDict


class Tool(TypedDict, total=False):
    """Tool structure supporting multiple LLM provider formats."""

    type: str
    function: dict[str, Any]  # OpenAI format: {name, description, parameters}
    name: str  # Anthropic, direct formats
    description: str
    input_schema: dict[str, Any]  # Anthropic format (snake_case)
    inputSchema: dict[str, Any]  # OpenAI format (camelCase)
    functionDeclarations: list[Any]  # Google/Gemini format
    parameters: dict[str, Any]  # Google/Gemini format (unwrapped)


def format_tools(ai_tools: Any) -> list[str]:
    """
    Format available tools section.

    Supports multiple LLM provider formats:
    - OpenAI: {type: 'function', function: {name, description, parameters}}
    - Anthropic: {name, description, input_schema}
    - Google/Gemini: {functionDeclarations: [...]} or unwrapped
    """
    lines: list[str] = []

    if not ai_tools or not isinstance(ai_tools, list) or len(ai_tools) == 0:
        return lines

    lines.append("")
    lines.append(f"AVAILABLE TOOLS: {len(ai_tools)}")

    for tool in ai_tools:
        if not isinstance(tool, dict):
            continue

        # Handle Google/Gemini format: {functionDeclarations: [{name, description, parameters}]}
        tools_to_process: list[dict[str, Any]] = []
        if "functionDeclarations" in tool and isinstance(tool["functionDeclarations"], list):
            tools_to_process = tool["functionDeclarations"]
        else:
            tools_to_process = [tool]

        for t in tools_to_process:
            name: str
            desc: str
            schema: dict[str, Any] | None = None

            # Handle different tool formats
            if "function" in t and isinstance(t["function"], dict):
                # OpenAI format: {type: 'function', function: {name, description, parameters}}
                name = t["function"].get("name", "unknown")
                desc = t["function"].get("description", "N/A")
                schema = t["function"].get("parameters")
            elif "name" in t:
                # Multiple formats:
                # - Anthropic: {name, description, input_schema} (snake_case)
                # - OpenAI: {name, description, inputSchema} (camelCase)
                # - Google/Gemini unwrapped: {name, description, parameters}
                name = t["name"]
                desc = t.get("description", "N/A")
                schema = t.get("input_schema") or t.get("inputSchema") or t.get("parameters")
            else:
                # Unknown format
                name = t.get("type", "UNKNOWN")
                desc = json.dumps(t)[:100]
                schema = None

            # Build function signature from schema
            signature = f"{name}("
            if schema and isinstance(schema, dict) and "properties" in schema:
                properties = schema["properties"]
                required = schema.get("required", [])
                params: list[str] = []

                for param_name, param_info in properties.items():
                    if not isinstance(param_info, dict):
                        continue
                    param_type = param_info.get("type", "any")
                    if param_name in required:
                        params.append(f"{param_name}: {param_type}")
                    else:
                        params.append(f"{param_name}?: {param_type}")

                signature += ", ".join(params)
            signature += ")"

            # Show signature
            lines.append("")
            lines.append(f"  {signature}")

            # Show only first line of description (up to first newline or sentence)
            if desc and desc != "N/A":
                # Split by newline first, then by sentence
                first_line = desc.split("\n")[0]
                first_sentence = first_line.split(". ")[0]
                final_sentence = first_sentence if first_sentence.endswith(".") else f"{first_sentence}."
                lines.append(f"    {final_sentence}")

    return lines
