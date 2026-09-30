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


class McpServerError(Exception):
    """The MCP server could not complete the call."""


class McpServerUnauthorizedError(McpServerError):
    pass
