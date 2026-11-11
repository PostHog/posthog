List the distinct metric names this project has ingested in the last 24 hours, with each metric's OTel type (`gauge`, `sum`, `histogram`, `summary`, `exponential_histogram`), unit, `last_seen` and `first_seen`. Names are ordered by how many services report them, and the closest matches to `value` come first.

ALWAYS call this before `query-metrics` unless you already know the exact metric name — metric queries match names exactly, so a guessed name silently returns no data.

Searching with `value`, and `match` to decide how it matches:

- `substring` (default, case-insensitive): `value: "lag"` finds `kafka_consumer_lag` but also every `flag` metric.
- `prefix` (case-insensitive): `value: "kminion_"` finds the names a single exporter sends.
- `regex`: an RE2 pattern run with ClickHouse `match()`. It is case-sensitive and unanchored, so anchor with `^`/`$` and add `(?i)` to ignore case. `value: "(^|_)lag(_|$)"` finds `lag` as a whole word only.

Use `limit` (default 50) to cap the list. Sparklines are off by default; set `sparklines: true` only when you need each metric's recent shape.

`first_seen` is the start of the earliest hour the metric arrived in, within retention. If it falls inside the window you are about to query, the metric did not exist before then: a gap before `first_seen` is missing data, not a drop to zero.

Prometheus classic histograms arrive as three names: `<name>_bucket` (with an `le` label), `<name>_sum` and `<name>_count`. When all three are listed, they are folded into one `<name>_bucket` entry with `classic_histogram: {base_name, bucket, sum, count}`. Set `fold_histograms: false` to list them separately. In `query-metrics` PromQL, query the `_bucket` name: `histogram_quantile(0.95, sum by (le) (rate(<name>_bucket[5m])))`, and `rate(<name>_sum[5m]) / rate(<name>_count[5m])` for the mean.

The metric's type tells you which aggregations make sense:

- `sum` (counters, usually `_total`-suffixed): use `rate` or `increase`
- `gauge`: use `avg`, `p95`, or `sum`
- `histogram`: use `histogram_quantile` with a `quantile`
