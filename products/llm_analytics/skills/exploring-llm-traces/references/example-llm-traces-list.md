# LLM Traces list query

List multiple LLM traces with aggregated latency, token usage, costs, and error counts.
This is a two-phase query for performance: first find matching trace IDs, then fetch full trace data.
Time ranges are always required. Results can be large — dump to a file if needed.

This query intentionally omits large content fields (`$ai_input`, `$ai_output`, `$ai_output_choices`, `$ai_input_state`, `$ai_output_state`, `$ai_tools`).
Use the [single trace query](./example-llm-trace.md) (or the `query-llm-trace` wrapper) to retrieve those for a specific trace; both read from a dedicated table that retains the full payload for ~30 days.

## Phase 1 — Find trace IDs

Use this subquery to find trace IDs matching your criteria. Add property filters here for efficiency.

```sql
SELECT
    properties.$ai_trace_id AS trace_id,
    min(timestamp) AS first_ts,
    max(timestamp) AS last_ts
FROM events
WHERE
    event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
    AND isNotNull(properties.$ai_trace_id)
    AND properties.$ai_trace_id != ''
    AND timestamp >= now() - INTERVAL 1 HOUR
    AND timestamp <= now()
    -- Add property filters here, e.g.:
    -- AND properties.$ai_model = 'gpt-4o'
    -- AND properties.$ai_is_error = 'true'
GROUP BY trace_id
ORDER BY min(timestamp) DESC
LIMIT 20
```

## Phase 2 — Fetch trace data

Use the trace IDs from phase 1 to fetch aggregated metrics. Replace the `IN (...)` clause with the IDs found above.

```sql
SELECT
    properties.$ai_trace_id AS id,
    any(properties.$ai_session_id) AS ai_session_id,
    min(timestamp) AS first_timestamp,
    ifNull(
        nullIf(argMinIf(distinct_id, timestamp, event = '$ai_trace'), ''),
        argMin(distinct_id, timestamp)
    ) AS first_distinct_id,
    round(
        CASE
            WHEN countIf(toFloat(properties.$ai_latency) > 0 AND event != '$ai_generation') = 0
                 AND countIf(toFloat(properties.$ai_latency) > 0 AND event = '$ai_generation') > 0
            THEN sumIf(toFloat(properties.$ai_latency),
                       event = '$ai_generation' AND toFloat(properties.$ai_latency) > 0)
            ELSE sumIf(toFloat(properties.$ai_latency),
                       properties.$ai_parent_id IS NULL
                       OR toString(properties.$ai_parent_id) = toString(properties.$ai_trace_id))
        END, 2
    ) AS total_latency,
    sumIf(toFloat(properties.$ai_input_tokens),
          event IN ('$ai_generation', '$ai_embedding')) AS input_tokens,
    sumIf(toFloat(properties.$ai_output_tokens),
          event IN ('$ai_generation', '$ai_embedding')) AS output_tokens,
    round(sumIf(toFloat(properties.$ai_input_cost_usd),
          event IN ('$ai_generation', '$ai_embedding')), 10) AS input_cost,
    round(sumIf(toFloat(properties.$ai_output_cost_usd),
          event IN ('$ai_generation', '$ai_embedding')), 10) AS output_cost,
    round(sumIf(toFloat(properties.$ai_total_cost_usd),
          event IN ('$ai_generation', '$ai_embedding')), 10) AS total_cost,
    ifNull(
        argMinIf(
            ifNull(properties.$ai_span_name, properties.$ai_trace_name),
            timestamp, event = '$ai_trace'
        ),
        argMin(
            ifNull(properties.$ai_span_name, properties.$ai_trace_name),
            timestamp
        )
    ) AS trace_name,
    countIf(
        isNotNull(properties.$ai_error) OR properties.$ai_is_error = 'true'
    ) AS error_count
FROM events
WHERE
    event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
    AND timestamp >= now() - INTERVAL 1 HOUR
    AND timestamp <= now()
    AND properties.$ai_trace_id IN ('trace-id-1', 'trace-id-2')
GROUP BY properties.$ai_trace_id
ORDER BY first_timestamp DESC
```
