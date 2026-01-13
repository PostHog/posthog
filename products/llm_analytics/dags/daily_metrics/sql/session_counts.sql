/*
Session Counts - Unique sessions (distinct $ai_session_id)

Counts the number of unique sessions by counting distinct $ai_session_id values
across all AI event types. A session can link multiple related traces together.

Produces metric: ai_session_id_count

Example: If there are 10 traces belonging to 3 unique session_ids, this counts 3.
Compare with trace_counts.sql which would count all 10 unique traces.
*/

SELECT
    date(timestamp) as date,
    team_id,
    'ai_session_id_count' as metric_name,
    toFloat64(count(DISTINCT JSONExtractString(properties, '$ai_session_id'))) as metric_value
FROM llma_events
WHERE JSONExtractString(properties, '$ai_session_id') != ''
GROUP BY date, team_id
