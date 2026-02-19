/*
-- Tool call extraction is done at ingestion time.
-- The $ai_tools_called property contains comma-separated tool names.
-- See: nodejs/src/ingestion/ai/tools/extract-tool-calls.ts
*/

SELECT
    arrayJoin(splitByChar(',', assumeNotNull(properties.$ai_tools_called))) as tool,
    count() as total_calls,
    countDistinctIf(properties.$ai_trace_id, properties.$ai_trace_id != '') as traces,
    uniq(distinct_id) as users,
    countDistinctIf(properties.$ai_session_id, properties.$ai_session_id != '') as sessions,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM events
WHERE event = '$ai_generation'
    AND properties.$ai_tool_call_count > 0
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
