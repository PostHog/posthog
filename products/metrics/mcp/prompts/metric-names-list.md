List the distinct metric names this project has ingested, with each metric's OTel type (`gauge`, `sum`, `histogram`, `summary`, `exponential_histogram`). Names are ordered by recent activity and exact matches float to the top.

ALWAYS call this before `query-metrics` unless you already know the exact metric name — metric queries match names exactly, so a guessed name silently returns no data.

Use `value` for a case-insensitive substring search (e.g. `value: "lag"` finds `metrics_rate_limiter_message_lag_seconds`). The metric's type tells you which aggregations make sense:

- `sum` (counters, usually `_total`-suffixed): use `rate` or `increase`
- `gauge`: use `avg`, `p95`, or `sum`
- `histogram`: use `histogram_quantile` with a `quantile`
