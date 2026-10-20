Count logs in time buckets. With `detect: "onset"` it also answers "when did this spike start" in one call. All parameters go inside `query`:

```json
{ "query": { "dateRange": { "date_from": "-6h" }, "serviceNames": ["api"], "detect": "onset" } }
```

Each bucket has `date_from`, `date_to` (exclusive) and `count`. Empty buckets are left out. `interval` is the bucket width.

`onset` gives `start`, `end`, `peak_at`, `baseline_per_min`, `peak_per_min` and `confidence`. The server finds the first sustained spike with the APM anomaly band, then counts the onset bucket again at a finer grid, so `start` is close to the minute. `onset` is null when no spike was found, and `end` is null while the spike lasts to the window end.

Use `logs-count` for one total, `logs-services-create` for which services changed, and `query-logs` to read the rows once you know the window.

`targetBuckets` sets the approximate bucket count (default 10, max 100). With `detect`, use 30 or more. To drill in without `detect`, pass a bucket's `date_from` and `date_to` as the next `dateRange`. Always scope with `serviceNames` or a filter. `severityLevels`, `searchTerm` and `filterGroup` have the same shape as in `query-logs`.
