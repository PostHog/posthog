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
    argMax(uuid, ts) as uuid,
    trace_id,
    argMax(ai_input, ts) as ai_input,
    argMax(model, ts) as model,
    argMax(did, ts) as distinct_id,
    max(ts) as timestamp
FROM (
    SELECT
        uuid,
        properties.$ai_trace_id as trace_id,
        properties.$ai_input as ai_input,
        properties.$ai_model as model,
        distinct_id as did,
        timestamp as ts
    FROM events
    WHERE event = '$ai_generation'
        AND properties.$ai_input != ''
        AND properties.$ai_trace_id != ''
        AND {filters}
)
GROUP BY trace_id
ORDER BY timestamp DESC, trace_id DESC
LIMIT 200
