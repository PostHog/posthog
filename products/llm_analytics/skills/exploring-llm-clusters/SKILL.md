---
name: exploring-llm-clusters
description: >
  Investigate LLM analytics clusters — discover usage patterns in AI/LLM traffic,
  compare cluster cost/latency/errors/sentiment, track clusters across runs,
  inspect outliers, and drill into representative traces. Use when the user asks
  "what kinds of LLM usage do we have?", "which cluster is most expensive?",
  "what are the error-heavy patterns?", pastes a `/llm-analytics/clusters/...`
  URL, or wants to understand clustering run results.
---

# Exploring LLM clusters with MCP tools

PostHog clusters LLM traces (or individual generations) by embedding similarity.
A Temporal workflow (`llma-trace-clustering`) runs daily per team: it fetches
recent trace summary embeddings, reduces dimensions, clusters with HDBSCAN,
labels each cluster with an LLM agent, and emits **one event per run** to
ClickHouse containing the full cluster structure.

## Available tools

| Tool                                             | Purpose                                                |
| ------------------------------------------------ | ------------------------------------------------------ |
| `posthog:execute-sql`                            | Query cluster run events and join to traces/metrics    |
| `posthog:llm-analytics-clustering-jobs-list`     | List clustering job configurations for the team        |
| `posthog:llm-analytics-clustering-jobs-retrieve` | Get a specific clustering job by ID                    |
| `posthog:query-llm-traces-list`                  | Search traces in the window, e.g. to sanity-check      |
| `posthog:query-llm-trace`                        | Inspect a specific trace (use for representative ones) |
| `posthog:read-data-schema`                       | Discover custom properties before filtering            |

## How clustering works

See the [event reference](./references/cluster-events.md) for the full property schema.

### Pipeline (per team, per run)

```text
  1. Fetch trace/generation summary embeddings from raw_document_embeddings
       (filtered by document_type + optional job_id suffix on `rendering`)
  2. Optional L2-normalize embeddings
  3. Dimensionality reduction (UMAP→100d, PCA, or none) for clustering
  4. Cluster (HDBSCAN default — auto-k, identifies outliers as cluster_id=-1;
             or k-means with silhouette-optimized k)
  5. Compute distance matrix + 2D projection (UMAP/PCA/t-SNE) for scatter plot
  6. Label clusters with an LLM agent (gpt-5.4 via LangGraph, 10-min budget)
  7. Aggregate per-cluster metrics (cost, latency, tokens, error_rate, sentiment)
  8. Emit single $ai_trace_clusters or $ai_generation_clusters event
```

### Two levels

- **Trace-level** (`$ai_trace_clusters`) — clusters whole traces; items keyed by `trace_id`
- **Generation-level** (`$ai_generation_clusters`) — clusters individual LLM calls; items keyed by `$ai_generation` event UUID, and each item also carries its parent `trace_id`

### Run ID format

```text
<team_id>_<level>_<YYYYMMDD>_<HHMMSS>[_<job_id>][_<run_label>]
```

- `level` is `trace` or `generation`
- `job_id` is a UUID when the run was triggered by a saved `ClusteringJob`
- `run_label` is a free-form experiment tag (rare — mostly for manual runs)
- Example: `1_trace_20250123_000000_019cb7f3-a126-7809-bffc-7f13bffe1325`

Use helpers from [`scripts/parse_run_id.py`](./scripts/parse_run_id.py) to decode.

### Noise / outlier cluster (HDBSCAN only)

- `cluster_id: -1` contains items HDBSCAN couldn't fit anywhere
- Items are sorted by **max** distance-to-any-centroid (most anomalous first, rank 0)
- Noise cluster has no real `centroid` (empty list); `centroid_x`/`centroid_y` is the mean of its points' 2D coords
- k-means runs don't produce a noise cluster

## Workflow: explore clusters

### Step 1 — List recent runs

```sql
SELECT
    JSONExtractString(properties, '$ai_clustering_run_id') as run_id,
    JSONExtractString(properties, '$ai_clustering_level') as level,
    JSONExtractString(properties, '$ai_clustering_job_name') as job_name,
    JSONExtractString(properties, '$ai_window_start') as window_start,
    JSONExtractString(properties, '$ai_window_end') as window_end,
    JSONExtractInt(properties, '$ai_total_items_analyzed') as total_items,
    timestamp
FROM events
WHERE event IN ('$ai_trace_clusters', '$ai_generation_clusters')
    AND timestamp >= now() - INTERVAL 30 DAY
ORDER BY timestamp DESC
LIMIT 20
```

### Step 2 — Load a specific run's cluster payload

```sql
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
    AND timestamp >= parseDateTimeBestEffort('<day_start_utc>')
    AND timestamp <= parseDateTimeBestEffort('<day_end_utc>')
LIMIT 1
```

**Always include a tight timestamp window** — the run ID is in UTC and encodes
the window end date. Use `parse_run_id.py` to derive day bounds, otherwise the
query scans ClickHouse unnecessarily.

The `clusters` JSON can be large (thousands of trace IDs with 2D coords and
metrics per cluster). When the result is persisted to a file, use the helper
scripts in [`scripts/`](./scripts/) to parse it.

### Step 3 — Summarize the run

```bash
# Overview: metadata, cluster sizes, titles, top traces per cluster
python3 scripts/print_clusters.py /path/to/persisted-file.json

# Cluster metrics (pre-aggregated) — cost, latency, error_rate, sentiment
python3 scripts/print_cluster_metrics.py /path/to/persisted-file.json

# Extract trace IDs from one cluster for drill-down
CLUSTER_ID=0 python3 scripts/extract_cluster_items.py /path/to/persisted-file.json

# Decode a run ID
python3 scripts/parse_run_id.py '1_trace_20250123_000000_019cb7f3-...'
```

### Step 4 — Drill into representative traces

Each cluster's `traces` map is keyed by item ID with a `rank` field (0 = closest
to centroid = most representative). Pick the top 3–5 ranked items and inspect:

```json
posthog:query-llm-trace
{
  "traceId": "<trace_id_from_cluster>",
  "dateRange": {"date_from": "<window_start>", "date_to": "<window_end>"}
}
```

For generation-level clusters the item key is a `$ai_generation` event UUID —
use the sibling `trace_id` field inside the item info to call `query-llm-trace`
with the parent trace.

### Step 5 — Read cluster metrics

Recent clusters have **pre-aggregated** metrics baked in under a `metrics` field
per cluster object:

```json
"metrics": {
  "avg_cost": 0.0123,
  "avg_latency": 2.45,
  "avg_tokens": 1250.0,
  "total_cost": 4.321,
  "error_rate": 0.05,
  "error_count": 2,
  "item_count": 37,
  "sentiment": {"label": "positive", "score": 0.7,
                "counts": {"positive": 20, "neutral": 5, "negative": 2}, "total": 27}
}
```

Older runs (before the aggregates activity was added) may not have this field.
If missing, compute on-demand with the SQL in
[`references/cluster-metrics-sql.md`](./references/cluster-metrics-sql.md) — it
mirrors what the frontend does when the baked-in metrics are absent.

## Investigation patterns

### "What kinds of LLM usage do we have?"

1. List recent runs (Step 1), pick the most recent trace-level one
2. Load its clusters (Step 2) and run `print_clusters.py`
3. Review cluster `title` + `description` — each is a distinct usage pattern
4. Compare cluster `size` fields to understand traffic distribution
5. Don't forget cluster -1 (outliers) — this is where novel/rare patterns hide

### "Which cluster is most expensive / slowest / errors the most?"

1. Load the run (Step 2), run `print_cluster_metrics.py`
2. It sorts clusters by `total_cost` desc, shows averages, error rate, and sentiment
3. If the run predates baked-in metrics, fall back to the on-demand SQL in
   [`references/cluster-metrics-sql.md`](./references/cluster-metrics-sql.md)
4. Drill into the top 3 ranked traces of the offending cluster to see why

### "What's in this cluster?"

1. `CLUSTER_ID=<id> python3 scripts/extract_cluster_items.py FILE` dumps item IDs in rank order
2. Inspect the top 3–5 ranked items via `query-llm-trace` (rank 0 = closest to centroid)
3. The cluster `title`/`description` is an LLM-generated summary — treat as a hypothesis and verify against real traces

### "Are there error-heavy clusters?"

1. From the metrics: sort clusters by `error_rate` descending, filter `item_count >= 5` to avoid tiny-sample noise
2. For high-error clusters, drill into items ranked lowest (furthest from centroid) —
   these are where the cluster's "edge" is, often where errors cluster
3. Cross-reference with `$ai_generation` `$ai_is_error = 'true'` events in the window

### "What's new or weird?" (outliers)

1. Load the run, filter the clusters array to `cluster_id = -1`
2. Noise items are sorted by `rank` ascending where rank 0 has the **highest** min-distance-to-any-centroid (most anomalous)
3. Inspect the top-ranked noise items via `query-llm-trace` — these are candidate new usage patterns

### "How do clusters compare across runs?"

1. List multiple runs for the same level + job_id (Step 1)
2. Load two runs and compare their cluster titles side-by-side — similar titles signal stable patterns
3. Track cluster-size shifts to detect traffic pattern changes week-over-week
4. Use `diff_runs.py` for a side-by-side summary

```bash
python3 scripts/diff_runs.py /path/to/run_a.json /path/to/run_b.json
```

### "Why did this specific trace end up here?"

1. Find the trace ID inside `cluster.traces`; note its `distance_to_centroid` and `rank`
2. High rank (far from centroid) = weakly representative → maybe it should be noise
3. Inspect the `$ai_trace_summary` event for that trace — that's the text the embedding was computed from:

   ```sql
   SELECT properties.$ai_summary_title, properties.$ai_summary_bullets,
          properties.$ai_batch_run_id, timestamp
   FROM events
   WHERE event = '$ai_trace_summary'
     AND JSONExtractString(properties, '$ai_trace_id') = '<trace_id>'
     AND timestamp >= now() - INTERVAL 30 DAY
   ORDER BY timestamp DESC LIMIT 1
   ```

### "What params were used for this run?"

The `$ai_clustering_params` property records the full config:

```json
{
  "clustering_method": "hdbscan",
  "clustering_method_params": { "min_cluster_size_fraction": 0.02, "min_samples": 5 },
  "embedding_normalization": "l2",
  "dimensionality_reduction_method": "umap",
  "dimensionality_reduction_ndims": 100,
  "visualization_method": "umap",
  "max_samples": 1500
}
```

Useful when comparing clustering runs that used different algorithms or samples.

## Clustering jobs

Each team can have up to 5 clustering jobs. A job defines:

- **name** — human-readable label
- **analysis_level** — `"trace"` or `"generation"`
- **event_filters** — PostHog property filters (same shape as feature flags / evaluations) that scope which items are included
- **enabled** — whether the scheduled run picks it up

Defaults named `"Default - trace"` and `"Default - generation"` are auto-created
and auto-disabled as soon as a custom job is created for the same level.

```json
posthog:llm-analytics-clustering-jobs-list {}
posthog:llm-analytics-clustering-jobs-retrieve {"id": "<job_uuid>"}
```

Match a run to its job via the `$ai_clustering_job_id` / `$ai_clustering_job_name`
properties on the cluster event, or decode the run ID with `parse_run_id.py`.

## Trace summaries (what the clustering actually sees)

Clustering does **not** embed raw trace data — it embeds a **summary** produced
by a separate hourly workflow (`llma-trace-summarization`). Each trace gets:

| Event                    | Emitted per | Key properties                                                                                                                              |
| ------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `$ai_trace_summary`      | Trace       | `$ai_trace_id`, `$ai_batch_run_id`, `$ai_summary_title`, `$ai_summary_flow_diagram`, `$ai_summary_bullets`, `$ai_summary_interesting_notes` |
| `$ai_generation_summary` | Generation  | Same as above plus `$ai_generation_id`                                                                                                      |

If a cluster title feels "off", the root cause is often the summary — pull the
summary event for a representative trace and confirm it captured the right
semantic signal.

## Constructing UI links

- **Clusters overview**: `https://app.posthog.com/llm-analytics/clusters`
- **Specific run**: `https://app.posthog.com/llm-analytics/clusters/<url_encoded_run_id>`
- **Cluster detail**: `https://app.posthog.com/llm-analytics/clusters/<url_encoded_run_id>/<cluster_id>`

URL-encode the run ID (it contains `_` and UUIDs). Always surface these links
so the user can verify visually in the PostHog UI.

## Tips

- **Always scope by timestamp** — cluster events exist in the regular `events` table, so unbounded queries are slow. Use `parse_run_id.py` to derive a tight day-window around the run
- **One event per run** — no joins or per-cluster rows; the whole cluster payload is a single JSON blob on a single event
- **Noise cluster items are ranked by anomaly, not proximity** — the most outlying item is rank 0
- **Cluster titles/descriptions are AI-generated** — great starting hypothesis, but always verify by inspecting representative traces
- **`metrics` may be missing on older runs** — check for the field before using; fall back to on-demand SQL
- **For generation-level drill-downs, use `item.trace_id`** (the parent trace) with `query-llm-trace`, not the item key (which is the generation UUID)
- **Minimum 20 items required** — teams with fewer traces in the window produce no cluster event (check with Step 1 and expect gaps)
- **Run in UTC** — run IDs and windows are UTC; set `convertToProjectTimezone: false` if you construct HogQL that compares to them
