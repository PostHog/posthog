/*
-- Sentiment tab: fetch recent generations with user input for on-demand sentiment analysis.
--
-- Performance notes (learned from PR #50634 benchmarks on teams with 1B+ events):
-- - DO NOT use length(properties.$ai_input) in WHERE — it forces JSONExtractRaw on every
--   scanned row (benchmarked 2.4x slower). Size filtering done post-fetch if needed.
-- - properties.$ai_trace_id uses materialized column mat_$ai_trace_id with bloom filter index.
-- - properties.$ai_model uses materialized column.
-- - Sort key is (team_id, toDate(timestamp), event) so event + date range filtering is efficient.
-- - {filters} handles date range, property filters, and test account filtering via HogQL.
-- - Selecting properties.$ai_input is fine (only reads for matched rows, not in WHERE).
*/
SELECT
    uuid,
    properties.$ai_trace_id as trace_id,
    properties.$ai_input as ai_input,
    properties.$ai_model as model,
    distinct_id,
    timestamp
FROM events
WHERE event = '$ai_generation'
    AND properties.$ai_input != ''
    AND {filters}
ORDER BY timestamp DESC
LIMIT 200
