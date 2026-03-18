/*
Event Counts - Individual AI events by type

Counts the total number of individual AI events ($ai_generation, $ai_embedding, etc).
Each event is counted separately, even if multiple events share the same trace_id.

Produces metrics: ai_generation_count, ai_embedding_count, ai_span_count, ai_trace_count

Example: If a trace contains 3 span events, this counts all 3 individually.
Compare with trace_counts.sql which would count this as 1 unique trace.
*/

SELECT
    date(timestamp) as date,
    team_id,
    concat(substring(event, 2), '_count') as metric_name,
    toFloat64(count(*)) as metric_value
FROM llma_events
GROUP BY date, team_id, event
