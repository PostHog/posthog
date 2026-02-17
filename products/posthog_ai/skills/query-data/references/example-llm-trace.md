# LLM Trace query

This query might return a very large blob of JSON data. You should either only include data you need in case it's minimal or dump the results to a file and use bash commands to explore it.
This query must always have time ranges set. You can calculate the time range as -30 to +30 minutes from the source event.
The typical order of event capture for a trace is: $ai_span -> $ai_generation/$ai_embedding -> $ai_trace.
Explore `$ai\_\*`-prefixed properties to find data related to traces, generations, embeddings, spans, feedback, and metric.
Key properties of the $ai_generation event: $ai_input and $ai_output_choices.

```sql
SELECT
    properties.$ai_trace_id AS id,
    any(properties.$ai_session_id) AS ai_session_id,
    min(timestamp) AS first_timestamp,
    tuple(argMin(person.id, timestamp), argMin(distinct_id, timestamp), argMin(person.created_at, timestamp), argMin(person.properties, timestamp)) AS first_person,
    round(if(and(equals(countIf(and(greater(toFloat(properties.$ai_latency), 0), notEquals(event, '$ai_generation'))), 0), greater(countIf(and(greater(toFloat(properties.$ai_latency), 0), equals(event, '$ai_generation'))), 0)), sumIf(toFloat(properties.$ai_latency), and(equals(event, '$ai_generation'), greater(toFloat(properties.$ai_latency), 0))), sumIf(toFloat(properties.$ai_latency), or(equals(properties.$ai_parent_id, NULL), equals(toString(properties.$ai_parent_id), toString(properties.$ai_trace_id))))), 2) AS total_latency,
    sumIf(toFloat(properties.$ai_input_tokens), in(event, tuple('$ai_generation', '$ai_embedding'))) AS input_tokens,
    sumIf(toFloat(properties.$ai_output_tokens), in(event, tuple('$ai_generation', '$ai_embedding'))) AS output_tokens,
    round(sumIf(toFloat(properties.$ai_input_cost_usd), in(event, tuple('$ai_generation', '$ai_embedding'))), 4) AS input_cost,
    round(sumIf(toFloat(properties.$ai_output_cost_usd), in(event, tuple('$ai_generation', '$ai_embedding'))), 4) AS output_cost,
    round(sumIf(toFloat(properties.$ai_total_cost_usd), in(event, tuple('$ai_generation', '$ai_embedding'))), 4) AS total_cost,
    arrayDistinct(arraySort(x -> x.3, groupArrayIf(tuple(uuid, event, timestamp, properties), notEquals(event, '$ai_trace')))) AS events,
    argMinIf(properties.$ai_input_state, timestamp, equals(event, '$ai_trace')) AS input_state,
    argMinIf(properties.$ai_output_state, timestamp, equals(event, '$ai_trace')) AS output_state,
    ifNull(argMinIf(ifNull(properties.$ai_span_name, properties.$ai_trace_name), timestamp, equals(event, '$ai_trace')), argMin(ifNull(properties.$ai_span_name, properties.$ai_trace_name), timestamp)) AS trace_name
FROM
    events
WHERE
    and(in(event, tuple('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')), and(greaterOrEquals(events.timestamp, assumeNotNull(toDateTime('2026-01-27 23:45:41'))), lessOrEquals(events.timestamp, assumeNotNull(toDateTime('2026-01-28 00:15:41'))), equals(properties.$ai_trace_id, '79955c94-7453-488f-a84a-eabb6f084e4c')))
GROUP BY
    properties.$ai_trace_id
LIMIT 1
```
