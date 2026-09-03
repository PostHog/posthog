"""SQL fragments other products may embed when querying $mcp_* events.

Re-exported here so cross-product consumers (mcp_registry's measured-server
aggregation) share the exec-coalescing rules with this product's query runners
instead of drifting copies.
"""

from products.mcp_analytics.backend.hogql_queries.base import (
    EFFECTIVE_DESCRIPTION_SQL,
    EFFECTIVE_TOOL_SQL,
    NEW_SDK_SOURCE,
)

__all__ = ["EFFECTIVE_DESCRIPTION_SQL", "EFFECTIVE_TOOL_SQL", "NEW_SDK_SOURCE"]
