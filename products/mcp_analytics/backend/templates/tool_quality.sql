/*
-- Per-tool quality metrics for the MCP analytics Tool quality tab.
-- One row per effective tool name with call volume, error rate, latency
-- percentiles, and reach (unique users / sessions / first / last seen).
--
-- Source events: `mcp_tool_call`. Events arrive in three property shapes
-- (mirrored in frontend/mcpEventShape.ts — keep the coalesces in sync):
--   - native tools/call events: $mcp_tool_name / $mcp_is_error / $mcp_duration_ms
--   - SDK single-exec events: real tool in $mcp_exec_tool_call_name
--   - legacy hono exec inner-call events: snake_case tool_name / success / duration_ms
-- The outer `exec` dispatcher wrapper is excluded: each exec invocation also
-- emits an inner event for the real tool, so counting both double-counts.
*/

SELECT
    coalesce(
        nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
        nullIf(toString(properties.$mcp_tool_name), ''),
        nullIf(toString(properties.tool_name), '')
    ) AS tool,
    count() AS total_calls,
    countIf(coalesce(toBool(properties.$mcp_is_error), not(toBool(properties.success)), false)) AS errors,
    round(countIf(coalesce(toBool(properties.$mcp_is_error), not(toBool(properties.success)), false)) * 100.0 / count(), 1) AS error_rate_pct,
    round(quantile(0.5)(coalesce(toFloat(properties.$mcp_duration_ms), toFloat(properties.duration_ms)))) AS p50_duration_ms,
    round(quantile(0.95)(coalesce(toFloat(properties.$mcp_duration_ms), toFloat(properties.duration_ms)))) AS p95_duration_ms,
    uniq(distinct_id) AS users,
    countDistinctIf(properties.$session_id, properties.$session_id != '') AS sessions,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events
WHERE event = 'mcp_tool_call'
    -- Repeats the `tool` coalesce: HogQL resolves SELECT aliases in GROUP BY /
    -- HAVING but not reliably in WHERE. The IS NOT NULL is load-bearing:
    -- HogQL's != is null-tolerant (NULL != 'exec' keeps the row), so without
    -- it shapeless events surface as a NULL tool row.
    AND coalesce(
        nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
        nullIf(toString(properties.$mcp_tool_name), ''),
        nullIf(toString(properties.tool_name), '')
    ) IS NOT NULL
    AND coalesce(
        nullIf(toString(properties.$mcp_exec_tool_call_name), ''),
        nullIf(toString(properties.$mcp_tool_name), ''),
        nullIf(toString(properties.tool_name), '')
    ) != 'exec'
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 200
