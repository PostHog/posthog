# PostHog Metrics Capture Service

Receives OTLP metrics (`/i/v1/metrics`) and Prometheus remote-write (`/i/v1/prometheus/write`) and writes them to Kafka.

This binary is the metrics half of [`capture-logs`](../capture-logs/README.md). It links the `capture-logs` library for parsing, authentication, and the Kafka sink, so metrics traffic can scale and deploy on its own. The base configuration, authentication, and response codes are the ones documented for `capture-logs`. The settings below are specific to this service.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| REDIS_URL | (none) | Redis that shares the set of recently labelled metric series between pods. Unset means local cache only |
| METRICS_SERIES_LABEL_GATE_ENABLED | false | Strip label maps from repeat metric rows (see below). When false the gate only reports metrics |
| METRICS_SERIES_LABEL_INTERVAL_SECS | 1800 | How often the labels of one metric series go out |
| METRICS_SERIES_REDIS_TIMEOUT_MS | 250 | Budget for one Redis write batch |
| METRICS_SERIES_REDIS_SEED_TIMEOUT_MS | 5000 | Budget for the startup pull and each periodic pull from Redis |
| METRICS_SERIES_REDIS_PULL_INTERVAL_SECS | 60 | How often the local cache pulls new series from Redis |

### Metric series label gate

Every metric row carries `series_fingerprint`. The label maps (`attributes`, `resource_attributes`) of a series go out on one row per `METRICS_SERIES_LABEL_INTERVAL_SECS`, with `has_labels = true`. All other rows of that series in the window have empty label maps and `has_labels = false`. The ClickHouse rollups build the series and attribute tables from labelled rows only.

The decision uses a local in-memory cache and never waits on Redis. Redis holds the set of series any pod has labelled: new series are pushed from a background task, and the cache pulls from Redis at startup and every `METRICS_SERIES_REDIS_PULL_INTERVAL_SECS`. A Redis failure only makes labels go out more often.

## Running the service

```bash
cargo run --bin capture-apm-metrics
```

Local dev: `bin/start-rust-service capture-apm-metrics` (HTTP on `4321`, management on `3312`).
