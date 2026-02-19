/*
-- Tool call extraction is done at ingestion time.
-- The $ai_tools_called property contains a JSON array of tool names called.
-- See: nodejs/src/ingestion/ai/tools/extract-tool-calls.ts
--
-- This query uses ARRAY JOIN JSONExtractArrayRaw() to explode the JSON array
-- of tool names into individual rows, then aggregates per tool name.
*/

SELECT
    replaceAll(tool_name, '"', '') as tool,
    count() as total_calls,
    countDistinctIf(properties.$ai_trace_id, properties.$ai_trace_id != '') as traces,
    uniq(distinct_id) as users,
    countDistinctIf(properties.$ai_session_id, properties.$ai_session_id != '') as sessions,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM events
ARRAY JOIN JSONExtractArrayRaw(ifNull(properties.$ai_tools_called, '[]')) as tool_name
WHERE event = '$ai_generation'
    AND properties.$ai_tool_call_count > 0
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
