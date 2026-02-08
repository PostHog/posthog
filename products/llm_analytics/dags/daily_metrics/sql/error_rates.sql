/*
Event Error Rates - Proportion of events with errors by type

Calculates the proportion of events of each type that had an error (0.0 to 1.0).
An event is considered errored if $ai_error is set or $ai_is_error is true.

Produces metrics: ai_generation_error_rate, ai_embedding_error_rate, etc.

Example: If 2 out of 10 generation events had errors, this reports 0.20.
Compare with trace_error_rates.sql which reports proportion of traces with any error.
*/

SELECT
    date(timestamp) as date,
    team_id,
    concat(substring(event, 2), '_error_rate') as metric_name,
    round(
        countIf(
            (JSONExtractRaw(properties, '$ai_error') != '' AND JSONExtractRaw(properties, '$ai_error') != 'null')
            OR JSONExtractBool(properties, '$ai_is_error') = true
        ) / count(*),
        4
    ) as metric_value
FROM llma_events
GROUP BY date, team_id, event
