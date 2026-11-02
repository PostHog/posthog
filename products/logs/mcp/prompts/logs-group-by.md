Count logs grouped by up to 4 dimensions in one call. All parameters go inside `query`:

```json
{ "query": { "dateRange": { "date_from": "-24h" }, "groupBys": [{ "key": "pattern", "source": "column" }] } }
```

Each group has `values` (one per dimension, in request order), `log_count`, `error_count`, `first_seen` and `last_seen`. `truncated` is true when more groups matched than `limit`.

Use it instead of SQL for "top errors by service", "which patterns fail most" or "which sessions are noisiest". Use `logs-services-create` for a per-service health summary against a baseline, `logs-patterns-diff` for new or growing patterns, and `query-logs` to read the rows of one group.

Dimensions in `groupBys`:

- `source: "column"`: `service_name`, `severity_level`, `pattern` (the masked message template), `trace_id`, `span_id`.
- `source: "log"`: a log attribute key, for example `session_id`.
- `source: "resource"`: a resource attribute key, for example `k8s.pod.name`.

Rows without a value for a dimension are not counted. `orderGroupsBy` is `log_count`, `error_count` or `last_seen` (descending). Filter with `severityLevels`, `serviceNames`, `searchTerm` and `filterGroup`. Results are cached for 60 seconds.
