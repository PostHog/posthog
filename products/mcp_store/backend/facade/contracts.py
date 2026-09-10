"""
Contract types for mcp_store.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ConnectorTool:
    """One tool a connected MCP server exposes to a member."""

    name: str
    description: str
    input_schema: dict[str, Any]
    # False when the server marks the tool destructive or its name reads as a write.
    read_only: bool


ConnectorCallStatus = Literal[
    "ok", "not_connected", "needs_reauth", "blocked", "tool_missing", "write_blocked", "upstream_error"
]


@dataclass(frozen=True)
class ConnectorCallOutcome:
    """Result of one tool call made with a member's own connection."""

    status: ConnectorCallStatus
    content: tuple[dict[str, Any], ...] = ()
    structured_content: Any = None
    is_error: bool = False
    detail: str = ""


@dataclass(frozen=True)
class ActiveInstallation:
    """An MCP server installation that is active and ready to use."""

    id: str
    name: str
    proxy_path: str
    # What the server does, in one line. Agents mount connectors without connecting to them,
    # so until the first call this is all their tool search has to match on.
    description: str = ""
    scope: str = "personal"
    # Set only for credentials delegated to a built-in agent. Kept out of reprs so the
    # short-lived bearer cannot accidentally land in logs.
    proxy_token: str | None = field(default=None, repr=False)
