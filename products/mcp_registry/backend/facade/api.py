"""Cross-boundary surface of the MCP registry product.

Presentation (and, later, other products) reach registry capabilities through
here rather than importing internals. Django models stay out of the facade;
the two model imports presentation still needs are TODO-exempted in
pyproject.toml's import-linter contract, mirroring mcp_analytics.
"""

from products.mcp_registry.backend.connect import build_connect_instructions
from products.mcp_registry.backend.constants import MCP_REGISTRY_FEATURE_FLAG
from products.mcp_registry.backend.ranking import DEFAULT_RANKING_VERSION, RANKING_VERSIONS, latest_completed_run

__all__ = [
    "DEFAULT_RANKING_VERSION",
    "MCP_REGISTRY_FEATURE_FLAG",
    "RANKING_VERSIONS",
    "build_connect_instructions",
    "latest_completed_run",
]
