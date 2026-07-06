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
    # Catalog template name when the installation came from the store (None for custom installs).
    template_name: str | None = None


@dataclass(frozen=True)
class TemplateInfo:
    """An installable MCP server template from the store catalog."""

    id: str
    name: str
    auth_type: str
    icon_key: str
    # True when a browser GET to the authorize endpoint can complete the connect on its own
    # (OAuth — shared credentials, or DCR registered at connect time). API-key templates
    # need the store UI instead.
    connect_via_redirect: bool
