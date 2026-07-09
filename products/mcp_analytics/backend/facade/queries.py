"""Query runners core dispatches on — the public wiring surface for HogQL queries.

mcp_analytics is tach-isolated to expose only `backend.facade.*`, so core's
`get_query_runner` dispatch imports the runner from here rather than reaching into
`backend.hogql_queries` directly.
"""

from products.mcp_analytics.backend.hogql_queries.harness_breakdown import MCPHarnessBreakdownQueryRunner
from products.mcp_analytics.backend.hogql_queries.tool_tables import (
    MCPToolDailyStatsQueryRunner,
    MCPToolDescriptionsQueryRunner,
    MCPToolFailuresQueryRunner,
    MCPToolNeighborsQueryRunner,
    MCPToolSampleIntentsQueryRunner,
    MCPToolStatsQueryRunner,
    MCPToolTopUsersQueryRunner,
)

__all__ = [
    "MCPHarnessBreakdownQueryRunner",
    "MCPToolDailyStatsQueryRunner",
    "MCPToolDescriptionsQueryRunner",
    "MCPToolFailuresQueryRunner",
    "MCPToolNeighborsQueryRunner",
    "MCPToolSampleIntentsQueryRunner",
    "MCPToolStatsQueryRunner",
    "MCPToolTopUsersQueryRunner",
]
