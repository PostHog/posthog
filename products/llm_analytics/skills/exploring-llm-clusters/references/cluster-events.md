# Clustering event and property reference

Clustering results are written to the regular `events` table as one event per
clustering run. The cluster payload is stored as **native JSON** on the event
(not a JSON string).

## Event types

### `$ai_trace_clusters`

Emitted by the trace-level clustering workflow. One event per run.

### `$ai_generation_clusters`

Emitted by the generation-level clustering workflow. Same shape as
`$ai_trace_clusters` — the only difference is that item keys inside
`cluster.traces` are `$ai_generation` event UUIDs, and each item carries its
parent `trace_id`.

## Event properties

| Property                   | Type        | Description                                                                   |
| -------------------------- | ----------- | ----------------------------------------------------------------------------- |
| `$ai_clustering_run_id`    | string      | Unique run ID: `<team_id>_<level>_<YYYYMMDD>_<HHMMSS>[_<job_id>][_<label>]`   |
| `$ai_clustering_level`     | string      | `"trace"` or `"generation"`                                                   |
| `$ai_clustering_job_id`    | string      | `ClusteringJob` UUID (empty for legacy/manual runs without a job)             |
| `$ai_clustering_job_name`  | string      | Friendly job name                                                             |
| `$ai_window_start`         | string      | Inclusive window start, ISO 8601 UTC                                          |
| `$ai_window_end`           | string      | Exclusive window end, ISO 8601 UTC                                            |
| `$ai_total_items_analyzed` | int         | Number of traces/generations actually clustered after the item-minimum filter |
| `$ai_clusters`             | JSON array  | Array of cluster objects (see below)                                          |
| `$ai_clustering_params`    | JSON object | Algorithm parameters used (see below)                                         |

## Cluster object (inside `$ai_clusters`)

```json
{
  "cluster_id": 0,
  "size": 42,
  "title": "User authentication flows",
  "description": "- Customer login and signup operations\n- Token refresh flows\n...",
  "traces": {
    "<item_key>": {
      "distance_to_centroid": 0.123,
      "rank": 0,
      "x": -2.34,
      "y": 1.56,
      "timestamp": "2026-03-28T10:00:00Z",
      "trace_id": "abc-123",
      "generation_id": null
    }
  },
  "centroid": [0.12, -0.45, ...],
  "centroid_x": -2.2,
  "centroid_y": 1.4,
  "metrics": {
    "avg_cost": 0.0123,
    "avg_latency": 2.45,
    "avg_tokens": 1250.0,
    "total_cost": 4.321,
    "error_rate": 0.05,
    "error_count": 2,
    "item_count": 37,
    "sentiment": {
      "label": "positive",
      "score": 0.7,
      "counts": {"positive": 20, "neutral": 5, "negative": 2},
      "total": 27
    }
  }
}
```

### Fields

| Field         | Type        | Notes                                                                                                                 |
| ------------- | ----------- | --------------------------------------------------------------------------------------------------------------------- |
| `cluster_id`  | int         | `-1` for the noise/outlier cluster (HDBSCAN only)                                                                     |
| `size`        | int         | Number of items in this cluster                                                                                       |
| `title`       | string      | LLM-generated cluster title                                                                                           |
| `description` | string      | LLM-generated description (often markdown bullets)                                                                    |
| `traces`      | object      | Map of item key → item info. Item key is `trace_id` for trace-level, `$ai_generation` event UUID for generation-level |
| `centroid`    | float array | Cluster centroid in reduced embedding space (empty for noise)                                                         |
| `centroid_x`  | float       | 2D x coord for the scatter plot                                                                                       |
| `centroid_y`  | float       | 2D y coord for the scatter plot                                                                                       |
| `metrics`     | object      | Pre-aggregated cost/latency/tokens/errors/sentiment (may be missing on older runs)                                    |

### Item info (inside `cluster.traces`)

| Field                  | Type           | Notes                                                                                                             |
| ---------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------- |
| `distance_to_centroid` | float          | Distance from this item to its cluster's centroid. For noise items, it's the **min** distance to **any** centroid |
| `rank`                 | int            | 0 = closest to centroid (most representative). For noise: 0 = most anomalous                                      |
| `x`, `y`               | float          | 2D scatter plot coordinates (from UMAP/PCA/t-SNE visualization reduction)                                         |
| `timestamp`            | string         | First event timestamp of the trace/generation, ISO 8601 (used for efficient lookup)                               |
| `trace_id`             | string         | Always set — trace ID (or parent trace for generations)                                                           |
| `generation_id`        | string \| null | Only set for generation-level clustering                                                                          |

## `$ai_clustering_params` shape

```json
{
  "clustering_method": "hdbscan",
  "clustering_method_params": {
    "min_cluster_size_fraction": 0.02,
    "min_samples": 5
  },
  "embedding_normalization": "l2",
  "dimensionality_reduction_method": "umap",
  "dimensionality_reduction_ndims": 100,
  "visualization_method": "umap",
  "max_samples": 1500
}
```

| Field                                                | Values                          | Notes                                                    |
| ---------------------------------------------------- | ------------------------------- | -------------------------------------------------------- |
| `clustering_method`                                  | `"hdbscan"` \| `"kmeans"`       | HDBSCAN auto-picks k and produces noise; k-means doesn't |
| `clustering_method_params.min_cluster_size_fraction` | float (0.02–0.5)                | HDBSCAN: min cluster size as fraction of samples         |
| `clustering_method_params.min_samples`               | int                             | HDBSCAN: min samples in neighborhood for core points     |
| `clustering_method_params.min_k` / `max_k`           | int                             | k-means: silhouette-score search range                   |
| `embedding_normalization`                            | `"none"` \| `"l2"`              | L2 = unit-length normalization (cosine-ish similarity)   |
| `dimensionality_reduction_method`                    | `"none"` \| `"umap"` \| `"pca"` | Reduction for clustering, not visualization              |
| `dimensionality_reduction_ndims`                     | int (default 100)               | Target dims for clustering                               |
| `visualization_method`                               | `"umap"` \| `"pca"` \| `"tsne"` | 2D projection for the scatter plot                       |
| `max_samples`                                        | int                             | Upper bound on items sampled per run                     |

## Related events

### `$ai_trace_summary` / `$ai_generation_summary`

Emitted by the summarization workflow (`llma-trace-summarization`) that feeds
clustering. Each run produces one summary per trace/generation. These are the
text representations that get embedded and clustered.

| Property                        | Type       | Description                                                           |
| ------------------------------- | ---------- | --------------------------------------------------------------------- |
| `$ai_trace_id`                  | string     | Original trace ID                                                     |
| `$ai_generation_id`             | string     | Only on `$ai_generation_summary`                                      |
| `$ai_batch_run_id`              | string     | Summary batch run ID (`<team>_<iso_ts>`); links summary → cluster run |
| `$ai_summary_mode`              | string     | `"detailed"` by default                                               |
| `$ai_summary_title`             | string     | Short title of the trace                                              |
| `$ai_summary_flow_diagram`      | string     | Mermaid diagram of the trace flow                                     |
| `$ai_summary_bullets`           | JSON array | Bulleted summary with line refs                                       |
| `$ai_summary_interesting_notes` | JSON array | Notable observations                                                  |
| `$ai_text_repr_length`          | int        | Length of the text that was embedded                                  |
| `$ai_event_count`               | int        | Number of underlying events in the trace                              |
| `trace_timestamp`               | string     | First event timestamp of the source trace                             |

The cluster labeling agent reads `$ai_summary_title` and other fields when it
generates cluster titles — so to understand "why did the cluster title say X",
pull the summary events for the cluster's top-ranked items.

## Noise cluster semantics (HDBSCAN)

- Only HDBSCAN produces a noise cluster (`cluster_id: -1`)
- Contains items that HDBSCAN couldn't fit into any dense region
- `centroid` is an empty list; `centroid_x`/`centroid_y` is the mean of the noise points' 2D coordinates (for visualization only)
- Items are sorted by **max** min-distance-to-any-centroid — rank 0 = most anomalous
- The labeling agent usually titles this cluster "Outliers" but wording varies

## Constants

| Value                       | Meaning                                                        |
| --------------------------- | -------------------------------------------------------------- |
| `NOISE_CLUSTER_ID`          | `-1`                                                           |
| `MIN_TRACES_FOR_CLUSTERING` | `20` — fewer than this in the window produces no cluster event |
| `DEFAULT_MAX_SAMPLES`       | `1500`                                                         |
| `DEFAULT_LOOKBACK_DAYS`     | `7`                                                            |
| `LABELING_AGENT_MODEL`      | `gpt-5.4`                                                      |
