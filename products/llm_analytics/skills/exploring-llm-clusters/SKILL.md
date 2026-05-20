---
name: exploring-llm-clusters
description: 'Investigate LLM analytics clusters — understand usage patterns in AI/LLM traffic, compare cluster behavior, compute cost/latency metrics, and drill into individual traces within clusters.'
---

# Exploring LLM clusters

Use this skill when investigating LLM analytics clusters —
understanding what patterns exist in your AI/LLM traffic,
comparing cluster behavior, and drilling into individual clusters.

## Tools

| Tool                               | Purpose                                         |
| ---------------------------------- | ----------------------------------------------- |
| `posthog:llma-clustering-job-list` | List clustering job configurations for the team |
| `posthog:llma-clustering-job-get`  | Get a specific clustering job by ID             |
| `posthog:execute-sql`              | Query cluster run events and compute metrics    |
| `posthog:query-llm-traces-list`    | Find traces belonging to a cluster              |
| `posthog:query-llm-trace`          | Inspect a specific trace in detail              |

## How clustering works

PostHog clusters LLM traces (or individual generations) by embedding similarity.
A Temporal workflow runs periodically or on-demand, producing cluster events stored as
`$ai_trace_clusters` (trace-level) or `$ai_generation_clusters` (generation-level).

Each cluster event contains:

- `$ai_clustering_run_id` — unique run identifier (format: `<team_id>_<level>_<YYYYMMDD>_<HHMMSS>[_<job_id>]`)
- `$ai_clustering_level` — `"trace"` or `"generation"`
- `$ai_window_start` / `$ai_window_end` — time window analyzed
- `$ai_total_items_analyzed` — number of traces/generations processed
- `$ai_clusters` — JSON array of cluster objects
- `$ai_clustering_params` — algorithm parameters used

### Cluster object shape (inside `$ai_clusters`)

```json
{
  "cluster_id": 0,
  "size": 42,
  "title": "User authentication flows",
  "description": "Traces involving login, signup, and token refresh operations",
  "traces": {
    "<trace_or_generation_id>": {
      "distance_to_centroid": 0.123,
      "rank": 0,
      "x": -2.34,
      "y": 1.56,
      "timestamp": "2026-03-28T10:00:00Z",
      "trace_id": "abc-123",
      "generation_id": "gen-456"
    }
  },
  "centroid_x": -2.1,
  "centroid_y": 1.4
}
```

- `cluster_id: -1` is the **noise/outlier** cluster (items that didn't fit any cluster)
- Items in `traces` are keyed by trace ID (trace-level) or generation event UUID (generation-level)
- `rank` orders items by proximity to centroid (0 = closest)
- `x`, `y` are 2D coordinates for visualization (UMAP/PCA/t-SNE reduced)

## Clustering jobs

Each team can have up to 5 clustering jobs. A job defines:

- **name** — human-readable label
- **analysis_level** — `"trace"` or `"generation"`
- **event_filters** — property filters scoping which traces are included
- **enabled** — whether the job runs on schedule

Default jobs named `"Default - trace"` and `"Default - generation"` are auto-created
and disabled when a custom job is created for the same level.

## Workflow: explore clusters

### Step 1 — List recent clustering runs

```sql
posthog:execute-sql
SELECT
    JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
    JSONExtractString(properties, '$ai_clustering_level') as level,
    JSONExtractString(properties, '$ai_window_start') as window_start,
    JSONExtractString(properties, '$ai_window_end') as window_end,
    JSONExtractInt(properties, '$ai_total_items_analyzed') as total_items,
    timestamp
FROM events
WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters')
    AND timestamp >= now() - INTERVAL 7 DAY
ORDER BY timestamp DESC
LIMIT 10
```

### Step 2 — Get clusters from a specific run

```sql
posthog:execute-sql
SELECT
    JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
    JSONExtractString(properties, '$ai_clustering_level') as level,
    JSONExtractString(properties, '$ai_clustering_job_id') as job_id,
    JSONExtractString(properties, '$ai_clustering_job_name') as job_name,
    JSONExtractString(properties, '$ai_window_start') as window_start,
    JSONExtractString(properties, '$ai_window_end') as window_end,
    JSONExtractInt(properties, '$ai_total_items_analyzed') as total_items,
    JSONExtractRaw(properties, '$ai_clusters') as clusters,
    JSONExtractRaw(properties, '$ai_clustering_params') as params
FROM events
WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters')
    AND JSONExtractString(properties, '$ai_clustering_run_id') = '<run_id>'
LIMIT 1
```

The `clusters` field is a JSON array. Parse it to see cluster titles, sizes, and descriptions.

**Important:** The clusters JSON can be very large (thousands of trace IDs with coordinates).
When the result is too large for inline display, it auto-persists to a file.
Use `print_clusters.py` from [scripts/](./scripts/) to get a readable summary.

### Step 3 — Compute metrics for clusters

For trace-level clusters, compute cost/latency/token metrics:

```sql
posthog:execute-sql
SELECT
    JSONExtractString(properties, '$ai_trace_id') as trace_id,
    sum(toFloat(properties.$ai_total_cost_usd)) as total_cost,
    max(toFloat(properties.$ai_latency)) as latency,
    sum(toInt(properties.$ai_input_tokens)) as input_tokens,
    sum(toInt(properties.$ai_output_tokens)) as output_tokens,
    countIf(properties.$ai_is_error = 'true') as error_count
FROM events
WHERE event IN ('$ai_generation', '$ai_embedding', '$ai_span')
    AND timestamp >= parseDateTimeBestEffort('<window_start>')
    AND timestamp <= parseDateTimeBestEffort('<window_end>')
    AND JSONExtractString(properties, '$ai_trace_id') IN ('<trace_id_1>', '<trace_id_2>', ...)
GROUP BY trace_id
```

For generation-level clusters, match by event UUID:

```sql
posthog:execute-sql
SELECT
    toString(uuid) as generation_id,
    toFloat(properties.$ai_total_cost_usd) as cost,
    toFloat(properties.$ai_latency) as latency,
    toInt(properties.$ai_input_tokens) as input_tokens,
    toInt(properties.$ai_output_tokens) as output_tokens,
    if(properties.$ai_is_error = 'true', 1, 0) as is_error
FROM events
WHERE event = '$ai_generation'
    AND timestamp >= parseDateTimeBestEffort('<window_start>')
    AND timestamp <= parseDateTimeBestEffort('<window_end>')
    AND toString(uuid) IN ('<gen_uuid_1>', '<gen_uuid_2>', ...)
```

### Step 4 — Drill into specific traces

Once you've identified interesting clusters, use the trace tools to inspect individual traces:

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id_from_cluster>",
  "dateRange": {"date_from": "<window_start>", "date_to": "<window_end>"}
}
```

## Investigation patterns

### "What kinds of LLM usage do we have?"

1. List recent clustering runs (Step 1)
2. Load the latest run's clusters (Step 2)
3. Review cluster titles and descriptions — each represents a distinct usage pattern
4. Compare cluster sizes to understand traffic distribution

### "Which cluster is most expensive / slowest?"

1. Load clusters from a run (Step 2)
2. Extract trace IDs from each cluster
3. Compute metrics per cluster (Step 3)
4. Aggregate: `avg(cost)`, `avg(latency)`, `sum(cost)` per cluster
5. Compare across clusters

### "What's in this cluster?"

1. Load the cluster's traces (from the `traces` field)
2. Sort by `rank` (closest to centroid = most representative)
3. Inspect the top 3-5 traces via `query-llm-trace` to understand the pattern
4. Check the cluster `title` and `description` for the AI-generated summary

### "Are there error-heavy clusters?"

1. Compute metrics (Step 3) with `error_count`
2. Calculate error rate per cluster: `items_with_errors / total_items`
3. Focus on clusters with high error rates
4. Drill into errored traces to find root causes

### "How do clusters compare across runs?"

1. List multiple runs (Step 1)
2. Load clusters from each run
3. Compare cluster titles — similar titles across runs indicate stable patterns
4. Track cluster size changes to detect shifts in traffic patterns

## Constructing UI links

- **Clusters overview**: `https://app.posthog.com/llm-analytics/clusters`
- **Specific run**: `https://app.posthog.com/llm-analytics/clusters/<url_encoded_run_id>`
- **Cluster detail**: `https://app.posthog.com/llm-analytics/clusters/<url_encoded_run_id>/<cluster_id>`

Always surface these links so the user can verify visually in the PostHog UI.

## Tips

- Always set a time range in SQL queries — cluster events without time bounds are slow
- Start with run listing to orient, then drill into specific clusters
- Cluster titles and descriptions are AI-generated summaries — verify by inspecting traces
- The noise cluster (`cluster_id: -1`) contains outliers that didn't fit any pattern
- Use `llma-clustering-job-list` to understand what clustering configs are active
- Trace IDs in clusters can be used directly with `query-llm-trace` for deep inspection
- For large clusters, inspect the top-ranked traces (closest to centroid) for representative examples
