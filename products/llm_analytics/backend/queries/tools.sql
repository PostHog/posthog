/*
-- Tool call extraction is done at ingestion time.
-- The $ai_tools_called property contains comma-separated tool names.
-- See: nodejs/src/ingestion/ai/tools/extract-tool-calls.ts
--
-- $ai_tools_called is still read from properties since it doesn't have a dedicated column.
-- solo_pct uses position() to check for commas instead of reading $ai_tool_call_count,
-- avoiding a second JSONExtractRaw + numeric cast per row.
*/

SELECT
    arrayJoin(splitByChar(',', assumeNotNull(properties.$ai_tools_called))) as tool,
    count() as total_calls,
    countDistinctIf(trace_id, trace_id != '') as traces,
    uniq(distinct_id) as users,
    countDistinctIf(session_id, session_id != '') as sessions,
    uniq(toDate(timestamp)) as days_seen,
    round(countIf(position(properties.$ai_tools_called, ',') = 0) * 100 / count()) as single_pct,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM ai_events
WHERE event = '$ai_generation'
    AND properties.$ai_tools_called != ''
    AND tool != ''
    AND {filters}
GROUP BY tool
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
