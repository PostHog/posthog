# PostHog Metrics Capture Service

Receives OTLP metrics (`/i/v1/metrics`) and Prometheus remote-write (`/i/v1/prometheus/write`) and writes them to Kafka.

This binary is the metrics half of [`capture-logs`](../capture-logs/README.md). It links the `capture-logs` library and mounts only the metrics routes, so metrics traffic can scale and deploy on its own. Configuration, authentication, response codes, and the Kafka sink are the ones documented for `capture-logs`.

## Running the service

```bash
cargo run --bin capture-apm-metrics
```

Local dev: `bin/start-rust-service capture-apm-metrics` (HTTP on `4321`, management on `3312`).
