"""
Contract types for mcp_store.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActiveInstallationInfo:
    """An MCP server installation that is active and ready to use."""

    id: str
    name: str
    proxy_path: str
    scope: str = "personal"
    # Set only for agent-scoped shared installations. Kept out of reprs so the
    # short-lived bearer cannot accidentally land in logs.
    proxy_token: str | None = field(default=None, repr=False)
