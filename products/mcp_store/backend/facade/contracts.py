"""
Contract types for mcp_store.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.
"""

from dataclasses import dataclass, field


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
    # Set only for credentials delegated to an agent. Kept out of reprs so the
    # short-lived bearer cannot accidentally land in logs.
    proxy_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, kw_only=True)
class ServiceAccountSummary:
    """A team agent identity (built-in agent or team-created service account)."""

    id: str
    name: str
    kind: str  # "built_in" | "custom"
    status: str  # "active" | "paused"
