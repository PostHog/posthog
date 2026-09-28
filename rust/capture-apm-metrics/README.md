# PostHog Metrics Capture Service

Receives OTLP metrics (`/i/v1/metrics`) and Prometheus remote-write (`/i/v1/prometheus/write`) and writes them to Kafka.

The remote-write route accepts two body encodings. `Content-Encoding: snappy` (or no header) is the Prometheus remote-write v1 protocol. `Content-Encoding: zstd` is the VictoriaMetrics remote-write protocol, which `vmagent` sends by default. Both carry the same protobuf and produce the same rows.

This binary is the metrics half of [`capture-logs`](../capture-logs/README.md). It links the `capture-logs` library for parsing, authentication, and the Kafka sink, so metrics traffic can scale and deploy on its own. The base configuration, authentication, and response codes are the ones documented for `capture-logs`. The settings below are specific to this service.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_URL | (none) | Redis that shares the set of recently labelled metric series between pods. Unset means local cache only |
| METRICS_SERIES_LABEL_GATE_ENABLED | false | Strip label maps from repeat metric rows (see below). When false the gate only reports metrics |
| METRICS_SERIES_LABEL_INTERVAL_SECS | 1800 | How often the labels of one metric series go out |
| METRICS_SERIES_REDIS_TIMEOUT_MS | 250 | Budget for one Redis write batch |
| METRICS_SERIES_REDIS_SEED_TIMEOUT_MS | 15000 | Longest the service waits at startup for the cache seed. After that it starts with a partial cache |
| METRICS_SERIES_REDIS_PULL_TIMEOUT_MS | 5000 | Budget for one periodic pull from Redis |
| METRICS_SERIES_REDIS_PULL_INTERVAL_SECS | 60 | How often the local cache pulls new series from Redis |
| METRICS_SERIES_CACHE_MAX_ENTRIES | 20000000 | Most series one pod remembers, across all tokens |
| METRICS_SERIES_CACHE_MAX_ENTRIES_PER_TOKEN | 2000000 | Most series one pod remembers for one token |

### Metric series label gate

Every metric row carries `series_fingerprint`. The label maps (`attributes`, `resource_attributes`) of a series go out on one row per `METRICS_SERIES_LABEL_INTERVAL_SECS`, with `has_labels = true`. All other rows of that series in the window have empty label maps and `has_labels = false`. The ClickHouse rollups build the series and attribute tables from labelled rows only.

The decision uses a local in-memory cache and never waits on Redis. Redis holds the set of series any pod has labelled: new series are pushed from a background task, and the cache pulls from Redis at startup and every `METRICS_SERIES_REDIS_PULL_INTERVAL_SECS`. Pulls read the set in pages of 50,000 members and merge each page as it arrives; the startup seed stops at `METRICS_SERIES_REDIS_SEED_TIMEOUT_MS` and keeps what it has. A Redis failure only makes labels go out more often.

Pull metrics, all with a `kind` label of `seed` or `periodic`: `capture_metrics_series_redis_pulls` (with `outcome` = `ok`, `timeout`, or `error`), `capture_metrics_series_redis_pull_duration_seconds` (same labels), `capture_metrics_series_redis_pull_pages`, `capture_metrics_series_redis_pull_members_read`, `capture_metrics_series_redis_pull_bytes` (member payload, without protocol framing), and `capture_metrics_series_redis_pulled` (members new to this pod).

The cache is bounded. When the global or the per-token cap is full, a new series keeps its labels on every row and is not cached or pushed to Redis, until pruning frees a slot. `capture_metrics_series_cache_full` counts those rows.

## Classic Prometheus histograms on remote write

Prometheus sends a classic histogram as one `_bucket` series for each bucket. Each bucket has an `le` label. Prometheus also sends `_count` and `_sum` series.

The service converts these component samples to one native histogram row when a request contains `_sum` and the `+Inf` bucket for the same label set and timestamp. The native row has `histogram_bounds` and `histogram_counts`. Its series fingerprint is the label fingerprint of an equivalent OTLP histogram, combined with the bound set. The storage keeps one bound set for each series and hour, so a partial bucket set and the complete bucket set of one histogram get separate series. Queries combine them by label set.

Conversion requires cumulative bucket values that are non-negative integers and do not decrease. If `_count` is present, it must equal the `+Inf` bucket. The service does not convert a family that metadata defines as a summary, counter, or gauge. Other component samples stay as normal rows. This preserves data when a sender divides a histogram across requests. Queries must combine native and normal rows by label set.

The service converts `le` and `quantile` label values to Go's shortest float format on every row. For example, `1.0` becomes `1` and `1000000` becomes `1e+06`. The series fingerprint uses the converted label value.

Metrics: `capture_metrics_remote_write_histograms_assembled` counts native rows. `capture_metrics_remote_write_histogram_samples_folded` counts converted component samples. `capture_metrics_remote_write_histogram_components_passed_through` counts component samples that stay as normal rows.

## Running the service

```bash
cargo run --bin capture-apm-metrics
```

Local dev: `bin/start-rust-service capture-apm-metrics` (HTTP on `4321`, management on `3312`).
