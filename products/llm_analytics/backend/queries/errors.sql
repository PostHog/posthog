/*
-- Error normalization is done at ingestion time.
-- The error_normalized column contains the pre-computed normalized error message.
-- See: nodejs/src/ingestion/ai/errors/normalize-error.ts
*/

SELECT
    error_normalized as error,
    countDistinctIf(trace_id, trace_id != '') as traces,
    countIf(event = '$ai_generation') as generations,
    countIf(event = '$ai_span') as spans,
    countIf(event = '$ai_embedding') as embeddings,
    countDistinctIf(session_id, session_id != '') as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM ai_events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
    AND is_error = 1
    AND {filters}
GROUP BY error
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
