Query server/infrastructure metrics and return each series in the shape of a Prometheus range result, for a client that draws a chart from that shape.

All parameters go inside `query`, the same as `query-metrics`:

```json
{ "query": { "promql": "sum by (job) (rate(http_requests_total[5m]))", "dateFrom": "-3h" } }
```

Use it when the person wants to see a metric over time as a chart. For every other question use `query-metrics`, which returns a smaller response.

`query` takes `metricName`, `clauses` or `promql`. Run `info query-metrics` for the fields and the workflow.

A range query returns JSON in this shape:

```text
{ "results": [{ "metric": { "service_name": "api" }, "values": [["2026-01-01T00:00:00Z", 12.5]] }] }
```

`metric` holds the series labels, with the metric or clause name under `__name__` when there is one. `values` holds one `[time, value]` pair per bucket, and a bucket that a series did not report is `null`.

An instant query (`instant` or `time`) or `"output": "summary"` has no points to draw, so it returns the same response as `query-metrics`.
