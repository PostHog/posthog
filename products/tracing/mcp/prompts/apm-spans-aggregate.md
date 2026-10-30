Aggregate trace span statistics grouped by `(service_name, name)` over a date window.

All parameters go inside `query` — top-level fields are rejected:

```json
{ "query": { "serviceNames": ["api"], "dateRange": { "date_from": "-1h" } } }
```

Returns one row per `(service_name, name)` pair with the following metrics:

- `count` — number of spans matched
- `total_duration_nano`, `avg_duration_nano`, `p50_duration_nano`, `p95_duration_nano`, `p99_duration_nano`, `p999_duration_nano` — duration stats in nanoseconds (1 second = 1,000,000,000 ns). `p999_duration_nano` is the 99.9th percentile and is only meaningful for `(service, name)` groups with enough spans; on low-volume operations it collapses to the max
- `error_count` — spans with OTel status code `Error` (status_code = 2)

Rows are ordered by `total_duration_nano` DESC. By default only the top 100 rows are returned — this keeps the response small, which matters because high span-name cardinality (e.g. untemplated URL paths) can otherwise produce an enormous payload. The top rows already surface the heaviest operations. When more rows genuinely exist the response sets `has_more: true` and `next_offset`; page through with `offset`, or raise `limit` (hard max 5000). Prefer narrowing with `serviceNames`/`filterGroup` over pulling a large page.

Use to answer:

- "Which services/operations consume the most time?"
- "What's the p95 or p99 latency of `GET /users`?"
- "How many errors did the checkout service emit in the last day?"
- "Did `POST /orders` get slower this week vs last week?" (with `compareFilter`)

For per-call-tree breakdowns (parent → child relationships), use `apm-spans-tree` instead. For time-bucketed trends ("when did it change?"), use `apm-spans-sparkline` instead — `compareFilter` only contrasts two static windows.

# Comparison window

Set `query.compareFilter.compare: true` to also fetch a comparison window. The response then includes a `compare` array of the same shape as `results`.

- Omit `compare_to` (or set null) to compare against the immediately previous period of equal length (e.g. `dateRange: -1d` → compares vs the day before).
- Set `compare_to: "-7d"` to compare against the window 7 days earlier (same length as the primary window).

When `compare` is true, `compare` is always an array — empty (`[]`) if the comparison window matched no spans (for example an operation that didn't exist yet), not null. `compare` is `null` only when no comparison was requested. So an empty array is a real answer ("nothing in the prior window"), not a failure.

# Data narrowing

## Property filters

Use `query.filterGroup` to narrow results to spans matching specific attributes. Only include filters that are essential to the user's question.

Filter `type` values:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span). A `duration` filter value is in milliseconds (1 second = `1000`).
- `span_attribute` — span-level attributes (e.g. "http.method", "http.status_code")
- `span_resource_attribute` — resource-level attributes (e.g. k8s labels, deployment info)

Use `apm-attributes-list` and `apm-attribute-values-list` to discover available attribute keys/values before guessing.

Supported operators:

- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`
- Numeric: `exact`, `gt`, `lt`
- Existence (no value needed): `is_set`, `is_not_set`

An attribute filter (`span_attribute` or `span_resource_attribute`) matches only spans that have the attribute, also for negated operators such as `is_not` and `not_icontains`. To find spans without the attribute, use `is_not_set`.

## Time period

Use `query.dateRange` to control the time window. Default is the last hour (`-1h`). Examples: `-1h`, `-6h`, `-1d`, `-7d`.

# Parameters

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

## query.limit

Max rows to return, ordered by `total_duration_nano` DESC. Defaults to 100; hard max 5000. Keep this small — a high value on high-cardinality span names returns a very large response. Narrow with `serviceNames`/`filterGroup` instead of raising it when you can.

## query.offset

Row offset for pagination. Combine with `limit` and the `next_offset` from a previous response to page through results beyond the first page.

## query.groupByEndpoint

Set to `true` to get per-endpoint health for HTTP servers. Rows then group by `METHOD route` (for example `GET /users/{id}`) from the `http.route` attribute, in place of the span name.

- Only HTTP server spans (span kind server with an HTTP method) are counted. Queue consumers, workflow activities and client spans are left out.
- A span without `http.route` keeps its span name as the row key.
- Use it when span names are raw paths (`/users/1`, `/users/2`) or a bare method (`GET`), which split or merge routes.

## query.includeHealth

Set to `true` to get `health_status` and `health_reason` on every row. Each row is compared with the same row in the `compareFilter` window, or in the previous period of the same length when `compareFilter` is off.

- `regressed`: the error rate or p95 jumped against the baseline.
- `degraded`: the error rate is high, with no clear jump.
- `new`: the row has no spans in the baseline.
- `recovered` and `improved`: the error rate or p95 went down.
- `ok`: none of the above.

It runs a second window query for the routes on the current page. Without `compareFilter`, the response `compare` stays null. With `compareFilter`, `compare` holds the baseline rows for those same routes.

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

## Endpoint health for one service

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "groupByEndpoint": true,
    "includeHealth": true,
    "dateRange": { "date_from": "-1d" }
  }
}
```

Each row is one route. Start with the rows whose `health_status` is `regressed` or `degraded`, and read `health_reason` for the cause.

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

- Duration values in results are in nanoseconds. Divide by 1,000,000 for ms, 1,000,000,000 for seconds. A `duration` filter value is in milliseconds.
- Results are ordered by `total_duration_nano` DESC and default to the top 100 rows. Check `has_more`/`next_offset` to page; raise `limit` (max 5000) only when you truly need the long tail.
- Use `apm-attributes-list` and `apm-attribute-values-list` to discover attribute keys/values before filtering.
- Use `apm-services-list` to discover services before filtering by service name.
- For parent → child breakdowns, use `apm-spans-tree` instead.
