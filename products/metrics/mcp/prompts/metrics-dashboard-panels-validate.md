Check up to 20 dashboard panel queries before they go on a dashboard, the way a dashboard import checks them.

Each panel has a `key` and a `language`:

- `promql`: a PromQL expression for metrics. The check confirms that every metric exists and that the expression runs over the last 15 minutes.
- `builder`: builder clauses for metrics, the same shape as `query-metrics`. The check confirms that every metric exists and that the clauses and the formula are valid.
- `histogram`: the name of a histogram metric, for a latency heatmap.
- `hogql`: a SQL SELECT over `logs` or `posthog.trace_spans`. It must put `{filters}` in the WHERE clause, so that the dashboard date range applies.

The result for each panel has `valid`, an `error` that tells you what to fix, and `notes` for warnings that do not block the query, such as no data in the last 15 minutes.
Fix a query and check it again until it is valid.
