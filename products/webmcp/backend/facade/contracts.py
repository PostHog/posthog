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
    """One call of a named MCP tool as the user, pinned to one project."""

    user_id: int
    team_id: int
    tool_name: str
    arguments: dict[str, Any]
    # The minted token carries exactly these scopes, so a caller passes only what the tool needs.
    scopes: tuple[str, ...]
    # Self-identifier sent as `x-posthog-mcp-consumer`, for the MCP server's logs and analytics.
    consumer: str


@dataclass(frozen=True)
class ToolCallResult:
    content: list[dict[str, Any]]
    structured_content: Any
    is_error: bool


class McpServerError(Exception):
    """The MCP server could not complete the call."""


class McpScopesUnavailable(McpServerError):
    """The WebMCP application's scope ceiling does not include every scope the call needs."""

    def __init__(self, missing_scopes: list[str]) -> None:
        super().__init__(f"These scopes are not available to server-side MCP calls: {', '.join(missing_scopes)}")
        self.missing_scopes = missing_scopes
