Time-bucketed log volume sparkline, broken down by severity or service. Cheap — use to understand patterns before pulling rows.

All params nest in `query` object.

# query.\* params

- `dateRange`: {date_from, date_to?}. Default -1h. Relative: -1h,-6h,-1d,-7d. Omit/null date_to = "now".
- `serviceNames`: list.
- `severityLevels`: subset of {trace,debug,info,warn,error,fatal}. Omit = all.
- `searchTerm`: full-text on body.
- `filterGroup`: same as `query-logs` filters.
- `sparklineBreakdownBy`: "severity" (default) | "service". Use "service" to see which services dominate volume.

# Examples

Error volume, last day:

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "severityLevels": ["error", "fatal"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

By service:

```json
{ "query": { "serviceNames": ["api-gateway"], "sparklineBreakdownBy": "service", "dateRange": { "date_from": "-6h" } } }
```

By severity:

```json
{
  "query": { "serviceNames": ["api-gateway"], "sparklineBreakdownBy": "severity", "dateRange": { "date_from": "-1d" } }
}
```
