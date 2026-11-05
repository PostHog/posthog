// Must match IS_FAILURE_SQL in products/mcp_analytics/backend/hogql_queries/base.py.
export const MCP_IS_FAILURE_HOGQL =
    "toString(properties.$mcp_is_error) IN ('true', '1') AND NOT coalesce(toString(properties.$mcp_error_expected) IN ('true', '1'), false)"
