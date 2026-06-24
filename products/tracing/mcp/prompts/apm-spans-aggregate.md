Aggregate trace span statistics grouped by `(service_name, name)` over a date window.

Returns one row per `(service_name, name)` pair with the following metrics:

- `count` — number of spans matched
- `total_duration_nano`, `avg_duration_nano`, `p50_duration_nano`, `p95_duration_nano`, `p99_duration_nano`, `p999_duration_nano` — duration stats in nanoseconds (1 second = 1,000,000,000 ns). `p999_duration_nano` is the 99.9th percentile and is only meaningful for `(service, name)` groups with enough spans; on low-volume operations it collapses to the max
- `error_count` — spans with OTel status code `Error` (status_code = 2)

Rows are ordered by `total_duration_nano` DESC and capped at 5000.

Use to answer:

- "Which services/operations consume the most time?"
- "What's the p95 or p99 latency of `GET /users`?"
- "How many errors did the checkout service emit in the last day?"
- "Did `POST /orders` get slower this week vs last week?" (with `compareFilter`)

For per-call-tree breakdowns (parent → child relationships), use `apm-spans-tree` instead. For time-bucketed trends ("when did it change?"), use `apm-spans-sparkline` instead — `compareFilter` only contrasts two static windows.

All parameters must be nested inside a `query` object.

# Comparison window

Set `query.compareFilter.compare: true` to also fetch a comparison window. The response then includes a `compare` array of the same shape as `results`.

- Omit `compare_to` (or set null) to compare against the immediately previous period of equal length (e.g. `dateRange: -1d` → compares vs the day before).
- Set `compare_to: "-7d"` to compare against the window 7 days earlier (same length as the primary window).

# Data narrowing

## Property filters

Use `query.filterGroup` to narrow results to spans matching specific attributes. Only include filters that are essential to the user's question.

Filter `type` values:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes (e.g. "http.method", "http.status_code")
- `span_resource_attribute` — resource-level attributes (e.g. k8s labels, deployment info)

Use `apm-attributes-list` and `apm-attribute-values-list` to discover available attribute keys/values before guessing.

Supported operators:

- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`
- Numeric: `exact`, `gt`, `lt`
- Existence (no value needed): `is_set`, `is_not_set`

## Time period

Use `query.dateRange` to control the time window. Default is the last hour (`-1h`). Examples: `-1h`, `-6h`, `-1d`, `-7d`.

# Parameters

All parameters go inside `query`.

## query.dateRange

Date range for the primary window. Defaults to the last hour.

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.compareFilter

Optional comparison-window configuration. Omit when you only need the primary window.

- `compare` (boolean): set to true to enable comparison.
- `compare_to` (string, optional): relative offset for the comparison window (e.g. `-1d`, `-7d`). Defaults to the immediately previous period of equal length.

## query.serviceNames

List of service names to restrict the aggregation to. Use `apm-services-list` to discover available services.

## query.filterGroup

A flat list of property filters applied to both the primary and comparison windows. See the "Property filters" section.

# Examples

## Top operations by total time in the last hour

```json
{
  "query": {}
}
```

## p95 latency by operation in the last day

```json
{
  "query": {
    "dateRange": { "date_from": "-1d" }
  }
}
```

Inspect the `p95_duration_nano` field on each result.

## Compare this hour vs the previous hour

```json
{
  "query": {
    "compareFilter": { "compare": true }
  }
}
```

Returns `results` for the last hour and `compare` for the hour before. Diff `total_duration_nano`, `avg_duration_nano`, etc. to find regressions.

## Compare today vs same time last week

```json
{
  "query": {
    "dateRange": { "date_from": "-1d" },
    "compareFilter": { "compare": true, "compare_to": "-7d" }
  }
}
```

## Aggregate only error spans

```json
{
  "query": {
    "filterGroup": [{ "key": "status_code", "operator": "exact", "type": "span", "value": 2 }],
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Aggregate within one service

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

# Reminders

- Duration values are in nanoseconds. Divide by 1,000,000 for ms, 1,000,000,000 for seconds.
- Results are ordered by `total_duration_nano` DESC and capped at 5000 rows.
- Use `apm-attributes-list` and `apm-attribute-values-list` to discover attribute keys/values before filtering.
- Use `apm-services-list` to discover services before filtering by service name.
- For parent → child breakdowns, use `apm-spans-tree` instead.
