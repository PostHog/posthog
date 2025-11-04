"""
Format available tools section for text view.

Ports TypeScript toolFormatter.ts to Python for pure Python text repr implementation.
"""

import json
import base64
from typing import Any, TypedDict
from urllib.parse import quote

# Constants for formatting behavior
DEFAULT_TOOLS_COLLAPSE_THRESHOLD = 5


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


def _format_tools_list(tools_list: list[dict[str, Any]]) -> str:
    """
    Format a list of tools into text representation.
    Returns the formatted text as a single string.
    """
    lines: list[str] = []

    for tool in tools_list:
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

    return "\n".join(lines)


def format_tools(ai_tools: Any, options: dict[str, Any] | None = None) -> list[str]:
    """
    Format available tools section.

    Supports multiple LLM provider formats:
    - OpenAI: {type: 'function', function: {name, description, parameters}}
    - Anthropic: {name, description, input_schema}
    - Google/Gemini: {functionDeclarations: [...]} or unwrapped
    - Dictionary format: {"tool_name": {name, description, ...}, ...}

    For tool lists > 5 items, creates a collapsed/expandable section by default.
    Use include_markers=False to show plain text "[+]" indicators instead.
    """
    lines: list[str] = []

    if not ai_tools:
        return lines

    # Convert dictionary format to list
    tools_list: list[dict[str, Any]]
    if isinstance(ai_tools, dict):
        # Handle dictionary format: {tool_name: tool_spec, ...}
        tools_list = list(ai_tools.values())
    elif isinstance(ai_tools, list):
        tools_list = ai_tools
    else:
        return lines

    if len(tools_list) == 0:
        return lines

    options = options or {}
    include_markers = options.get("include_markers", True)
    collapse_threshold = options.get("tools_collapse_threshold", DEFAULT_TOOLS_COLLAPSE_THRESHOLD)

    lines.append("")

    # For long tool lists (> threshold), create expandable section
    if len(tools_list) > collapse_threshold:
        display_text = f"AVAILABLE TOOLS: {len(tools_list)}"

        if include_markers:
            # Format all tools and encode for frontend to expand
            tools_content = _format_tools_list(tools_list)
            full_content = f"{display_text}\n{tools_content}"
            encoded_content = base64.b64encode(quote(full_content).encode()).decode()
            expandable_marker = f"<<<TOOLS_EXPANDABLE|{display_text}|{encoded_content}>>>"
            lines.append(expandable_marker)
        else:
            # Plain text for backend/LLM
            lines.append(f"[+] {display_text}")

        return lines

    # For short tool lists (<= threshold), show full list
    lines.append(f"AVAILABLE TOOLS: {len(tools_list)}")
    tools_content = _format_tools_list(tools_list)
    lines.append(tools_content)

    return lines
