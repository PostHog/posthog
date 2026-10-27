"""
Contract types for webmcp.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from typing import Any

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class ExecTool:
    name: str
    description: str
    # MCP carries the schema as opaque JSON, and the browser hands it to WebMCP unchanged.
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class RunExecInput:
    user_id: int
    team_id: int
    command: str


@dataclass(frozen=True)
class ExecResult:
    content: list[dict[str, Any]]
    is_error: bool


@dataclass(frozen=True)
class CallToolInput:
    user_id: int
    team_id: int
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    # The tool's JSON result. None when the tool failed or its result is not a JSON object.
    structured_content: dict[str, Any] | None
    # The text blocks of the result, joined. A failed tool puts its error message here.
    text: str
    is_error: bool


class McpServerError(Exception):
    """The MCP server could not complete the call."""


class McpServerTimeout(McpServerError):
    """The MCP server received the call and did not answer in time. The call can still complete."""
