Get a time-bucketed sparkline of log volume, broken down by severity or service. Use this to understand log volume patterns before querying individual log entries — it is much cheaper than a full log query.

All parameters must be nested inside a `query` object.

# Parameters

## query.dateRange

Date range for the sparkline. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

Filter by service names.

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels.

## query.searchTerm

Full-text search across log bodies.

## query.filterGroup

Property filters to narrow results. Same format as `query-logs` filters.

## query.sparklineBreakdownBy

Break down the sparkline by `"severity"` (default) or `"service"`. Use `"service"` to see which services are producing the most logs.

# Examples

## Error volume over the last day

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "severityLevels": ["error", "fatal"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Log volume by service

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "sparklineBreakdownBy": "service",
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Log volume by severity

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "sparklineBreakdownBy": "severity",
    "dateRange": { "date_from": "-1d" }
  }
}
```
