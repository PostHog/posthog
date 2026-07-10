"""
Contract types for mcp_store.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActiveInstallationInfo:
    """An MCP server installation that is active and ready to use."""

    id: str
    name: str
    proxy_path: str
    scope: str = "personal"


@dataclass(frozen=True)
class GatewayServerInfo:
    """The connected MCP server a gateway tool belongs to."""

    slug: str
    display_name: str
    installation_id: str
    scope: str


@dataclass(frozen=True)
class GatewayToolInfo:
    """A tool exposed through the aggregated MCP gateway.

    ``name`` is namespaced as ``{server_slug}/{tool_name}`` — the ``/`` keeps
    connected-server tools distinct from PostHog's own kebab-case tools.
    """

    name: str
    server: GatewayServerInfo
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    approval_state: str


@dataclass(frozen=True)
class GatewayCallResult:
    """Result of a gateway tool call, mirroring the MCP ``CallToolResult``."""

    content: list[Any]
    is_error: bool
    server_slug: str
    tool_name: str
    duration_ms: int
    structured_content: dict[str, Any] | None = None


class GatewayError(Exception):
    """Base class for gateway dispatch failures."""


class GatewayToolNotFoundError(GatewayError):
    """The namespaced tool doesn't resolve to a live tool on a connected server."""


class GatewayToolNeedsApprovalError(GatewayError):
    """The tool exists but requires user approval before it can be called."""

    def __init__(self, message: str, *, approval_url: str) -> None:
        super().__init__(message)
        self.approval_url = approval_url


class GatewayToolBlockedError(GatewayError):
    """The tool has been marked "do not use" by the user."""


class GatewayUpstreamError(GatewayError):
    """The upstream MCP server couldn't be called (auth, network, or protocol failure)."""

    def __init__(self, message: str, *, error_type: str = "upstream_error") -> None:
        super().__init__(message)
        self.error_type = error_type
