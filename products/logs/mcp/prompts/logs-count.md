Return a scalar count of log entries matching a filter set. Use this as a cheap pre-flight before `query-logs` — if the count exceeds `query-logs`'s max `limit` of 1000, narrow the filters before pulling rows.

All parameters must be nested inside a `query` object.

# When to use

- Before `query-logs`, to confirm the filter set returns a tractable number of rows. If the count is above `query-logs`'s max `limit` of 1000, narrow the filters.
- When the user asks "how many X logs are there?" and you don't need to see individual rows.
- To check whether a filter combination matches anything at all before committing to a full query.

# Parameters

## query.dateRange

Date range for the count. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

Filter by service names. Unlike `query-logs`, this tool does NOT require `serviceNames` — an unfiltered count is cheap and often useful for sizing up a filter before narrowing.

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels.

## query.searchTerm

Full-text search across log bodies.

## query.filterGroup

Property filters to narrow results. Same format as `query-logs` filters.

# Examples

## Count errors in a service over the last day

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "severityLevels": ["error", "fatal"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Confirm a k8s namespace is producing logs at all

```json
{
  "query": {
    "dateRange": { "date_from": "-1h" },
    "filterGroup": [
      { "key": "k8s.namespace.name", "operator": "exact", "type": "log_resource_attribute", "value": "payments" }
    ]
  }
}
```
