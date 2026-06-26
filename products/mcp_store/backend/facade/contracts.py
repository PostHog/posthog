"""
Contract types for mcp_store.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveInstallationInfo:
    """An MCP server installation that is active and ready to use."""

    id: str
    name: str
    proxy_path: str


@dataclass(frozen=True)
class ActiveInstallationToolInfo:
    """Approval metadata for a live tool on an active MCP server installation."""

    installation_id: str
    installation_name: str
    tool_name: str
    approval_state: str
