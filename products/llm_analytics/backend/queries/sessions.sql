/*
-- Session aggregation query.
-- Groups events by trace_id first (inner query), then by session_id (outer query).
--
-- All AI event types can carry $ai_session_id, but cost/latency data lives
-- on $ai_generation and $ai_embedding events.
-- A single-level GROUP BY session_id would filter out all child events.
--
-- Cost is summed only from $ai_generation and $ai_embedding events (per data model).
-- Latency prefers the trace-level $ai_latency, falling back to summing children.
*/

SELECT
    session_id,
    count() as traces,
    sum(spans) as spans,
    sum(generations) as generations,
    sum(embeddings) as embeddings,
    sum(errors) as errors,
    round(sum(trace_cost), 4) as total_cost,
    round(sum(trace_latency), 2) as total_latency,
    min(first_seen) as first_seen,
    max(last_seen) as last_seen
FROM (
    SELECT
        anyIf(properties.$ai_session_id, isNotNull(properties.$ai_session_id) AND properties.$ai_session_id != '') as session_id,
        countIf(event = '$ai_span') as spans,
        countIf(event = '$ai_generation') as generations,
        countIf(event = '$ai_embedding') as embeddings,
        countIf(properties.$ai_is_error = 'true') as errors,
        sumIf(toFloat(properties.$ai_total_cost_usd), event IN ('$ai_generation', '$ai_embedding')) as trace_cost,
        coalesce(
            anyIf(toFloat(properties.$ai_latency), event = '$ai_trace' AND isNotNull(properties.$ai_latency)),
            sumIf(toFloat(properties.$ai_latency), event IN ('$ai_generation', '$ai_embedding', '$ai_span'))
        ) as trace_latency,
        min(timestamp) as first_seen,
        max(timestamp) as last_seen
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
        AND isNotNull(properties.$ai_trace_id)
        AND properties.$ai_trace_id != ''
        AND {filters}
    GROUP BY properties.$ai_trace_id
    HAVING session_id != '' AND isNotNull(session_id)
)
GROUP BY session_id
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 50
