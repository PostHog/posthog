# On-demand cluster metrics SQL

Use this when the `metrics` field is missing from cluster objects (older runs
that predate the aggregates activity) or when you want to compute metrics with
a different definition than the baked-in one.

The frontend uses the same queries when falling back from baked-in metrics. See
`products/llm_analytics/frontend/clusters/clusterMetricsLoader.ts` for the
canonical source.

## Trace-level clusters

Aggregate cost/latency/tokens/errors across every AI event in each trace.

```sql
SELECT
    JSONExtractString(properties, '$ai_trace_id') AS item_id,
    sum(toFloat(properties.$ai_total_cost_usd))  AS total_cost,
    max(toFloat(properties.$ai_latency))         AS latency,
    sum(toInt(properties.$ai_input_tokens))      AS input_tokens,
    sum(toInt(properties.$ai_output_tokens))     AS output_tokens,
    countIf(properties.$ai_is_error = 'true')    AS error_count
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding', '$ai_span')
    AND timestamp >= parseDateTimeBestEffort('<window_start>')
    AND timestamp <= parseDateTimeBestEffort('<window_end>')
    AND JSONExtractString(properties, '$ai_trace_id') IN (<trace_ids>)
GROUP BY item_id
```

## Generation-level clusters

Match each `$ai_generation` event directly by its UUID — no aggregation needed.

```sql
SELECT
    toString(uuid)                          AS item_id,
    toFloat(properties.$ai_total_cost_usd)  AS cost,
    toFloat(properties.$ai_latency)         AS latency,
    toInt(properties.$ai_input_tokens)      AS input_tokens,
    toInt(properties.$ai_output_tokens)     AS output_tokens,
    if(properties.$ai_is_error = 'true', 1, 0) AS error_count
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= parseDateTimeBestEffort('<window_start>')
    AND timestamp <= parseDateTimeBestEffort('<window_end>')
    AND toString(uuid) IN (<generation_uuids>)
```

## Aggregating per cluster

Once you have per-item metrics, aggregate as follows (matches the backend in
`posthog/temporal/llm_analytics/trace_clustering/aggregates.py`):

- `avg_cost` = mean of non-null, positive `cost` values within the cluster
- `avg_latency` = mean of non-null, positive `latency` values within the cluster
- `avg_tokens` = mean of `input_tokens + output_tokens` for items with tokens > 0
- `total_cost` = sum of cost values
- `error_rate` = `items_with_errors / items_with_any_data`
- `item_count` = items with any metrics data

Items with no AI events in the window are skipped (they don't count toward the
denominator) — otherwise old items could drag down averages.

## Cluster-level rollup query (trace-level, one SQL hop)

If you want to do everything in one query (no script), unnest the cluster JSON
and join against metrics:

```sql
WITH run AS (
    SELECT
        JSONExtractRaw(properties, '$ai_clusters') AS clusters_json,
        JSONExtractString(properties, '$ai_window_start') AS window_start,
        JSONExtractString(properties, '$ai_window_end')   AS window_end
    FROM events
    WHERE event = '$ai_trace_clusters'
      AND JSONExtractString(properties, '$ai_clustering_run_id') = '<run_id>'
      AND timestamp >= parseDateTimeBestEffort('<day_start_utc>')
      AND timestamp <= parseDateTimeBestEffort('<day_end_utc>')
    LIMIT 1
)
SELECT
    c.cluster_id,
    c.title,
    c.size,
    avg(m.total_cost)  AS avg_cost_per_trace,
    sum(m.total_cost)  AS total_cost,
    avg(m.latency)     AS avg_latency,
    sum(m.error_count) AS total_errors
FROM run
ARRAY JOIN arrayMap(x -> tuple(
    JSONExtractInt(x, 'cluster_id'),
    JSONExtractString(x, 'title'),
    JSONExtractInt(x, 'size'),
    JSONExtractKeys(JSONExtractRaw(x, 'traces'))
), JSONExtractArrayRaw(clusters_json)) AS c
-- ... join to per-trace metrics ...
```

In practice it's usually easier to use the two-step approach (pull the cluster
event, run `print_cluster_metrics.py` or `extract_cluster_items.py`, then query
metrics for specific trace IDs).
