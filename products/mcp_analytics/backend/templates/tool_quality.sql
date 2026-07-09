/*
-- Per-tool quality metrics for the MCP analytics Tool quality tab.
-- One row per $mcp_tool_name with call volume, error rate, latency percentiles,
-- and reach (unique users / sessions / first / last seen).
--
-- Source events: `$mcp_tool_call`, emitted by the MCP analytics SDK on every
-- tool invocation. Expected properties:
--   $mcp_tool_name      string
--   $mcp_is_error       boolean
--   $mcp_duration_ms    number (milliseconds)
--   $session_id         string
*/

SELECT
    properties.$mcp_tool_name AS tool,
    count() AS total_calls,
    countIf(toBool(properties.$mcp_is_error)) AS errors,
    round(countIf(toBool(properties.$mcp_is_error)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.5)(toFloat(properties.$mcp_duration_ms))) AS p50_duration_ms,
    round(quantile(0.95)(toFloat(properties.$mcp_duration_ms))) AS p95_duration_ms,
    round(quantile(0.99)(toFloat(properties.$mcp_duration_ms))) AS p99_duration_ms,
    uniq(distinct_id) AS users,
    countDistinctIf(properties.$session_id, properties.$session_id != '') AS sessions,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = '$mcp_tool_call'
    AND properties.$mcp_tool_name IS NOT NULL
    AND properties.$mcp_tool_name != ''
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 200
