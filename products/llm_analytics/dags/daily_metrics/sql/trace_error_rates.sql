/*
Trace Error Rates - Proportion of traces with any error

Calculates the proportion of unique traces that had at least one error event (0.0 to 1.0).
A trace is considered errored if ANY event within it has $ai_error set or $ai_is_error is true.

Produces metric: ai_trace_id_has_error_rate

Example: If 2 out of 8 unique traces had any error event, this reports 0.25.
Compare with error_rates.sql which reports proportion of individual events with errors.

Note: A single erroring event in a trace makes the entire trace count as errored.
*/

SELECT
    date(timestamp) as date,
    team_id,
    'ai_trace_id_has_error_rate' as metric_name,
    round(
        countDistinctIf(
            JSONExtractString(properties, '$ai_trace_id'),
            (JSONExtractRaw(properties, '$ai_error') != '' AND JSONExtractRaw(properties, '$ai_error') != 'null')
            OR JSONExtractBool(properties, '$ai_is_error') = true
        ) / count(DISTINCT JSONExtractString(properties, '$ai_trace_id')),
        4
    ) as metric_value
FROM llma_events
WHERE JSONExtractString(properties, '$ai_trace_id') != ''
GROUP BY date, team_id
