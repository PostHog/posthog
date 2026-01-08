/*
-- Error normalization is now done at ingestion time.
-- The $ai_error_normalized property contains the pre-computed normalized error message.
-- See: nodejs/src/ingestion/ai/errors/normalize-error.ts
*/

WITH

normalized_errors AS (
    SELECT
        distinct_id,
        timestamp,
        event,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$ai_trace_id'), ''), 'null'), '^"|"$', '') as ai_trace_id,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$ai_session_id'), ''), 'null'), '^"|"$', '') as ai_session_id,
        JSONExtractString(properties, '$ai_error_normalized') as normalized_error
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
        AND properties.$ai_is_error = 'true'
        AND {filters}
)

SELECT
    normalized_error as error,
    countDistinctIf(ai_trace_id, isNotNull(ai_trace_id) AND ai_trace_id != '') as traces,
    countIf(event = '$ai_generation') as generations,
    countIf(event = '$ai_span') as spans,
    countIf(event = '$ai_embedding') as embeddings,
    countDistinctIf(ai_session_id, isNotNull(ai_session_id) AND ai_session_id != '') as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM normalized_errors
GROUP BY normalized_error
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
