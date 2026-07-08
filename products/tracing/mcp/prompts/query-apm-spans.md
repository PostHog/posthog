Query trace spans with filtering by service name, status code, date range, and structured attribute filters. Supports cursor-based pagination. Returns spans with uuid, trace_id, span_id, parent_span_id, name, kind, service_name, status_code, timestamp, end_time, duration_nano, is_root_span, matched_filter, and attributes (the span-level OTel attribute map, e.g. db.statement, http.url).

Use 'apm-attributes-list' and 'apm-attribute-values-list' to discover available attributes before building filters. Use 'apm-services-list' to discover available services.

# Return shape

Results are **grouped by trace**, not a flat list of matching spans. For each trace that contains at least one span matching your filters, the response includes spans from that trace (up to `prefetchSpans` per trace, root span first). Two fields tell you which spans actually matched:

- `matched_filter` — `1` if **this span** satisfies your `filterGroup`/`serviceNames`/`statusCodes`, `0` if it's only included because it shares a trace with a match (e.g. a prefetched sibling or the trace's root). When you filter by a child span's name, the matching child has `matched_filter: 1` and its root/siblings have `matched_filter: 0`.
- `is_root_span` — `true` for the trace's entry span.

To collapse each matching trace to a **single row — its root span**, set `rootSpans: true` — see below. (The row is the trace's entry span, which may itself carry `matched_filter: 0` when the match was on a child.) To inspect a single trace's full tree, take a `trace_id` from the results and call `apm-trace-get`.

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

All parameters must be nested inside a `query` object.

# Data narrowing

## Property filters

Use property filters via the `query.filterGroup` field to narrow results. Only include property filters when they are essential to directly answer the user's question.

When using a property filter, you should:

- **Choose the right type.** Span property types are:
  - `span` — filters built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span).
  - `span_attribute` — filters span-level attributes (e.g. "http.method", "http.status_code").
  - `span_resource_attribute` — filters resource-level attributes (e.g. k8s labels, deployment info).
- **Use `apm-attributes-list` to discover available attribute keys** before building filters.
- **Use `apm-attribute-values-list` to discover valid values** for a specific attribute key.
- **Find the suitable operator for the value type** (see supported operators below).

Supported operators:

- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`
- Numeric: `exact`, `gt`, `lt`
- Existence (no value needed): `is_set`, `is_not_set`

The `value` field accepts a string, number, or array of strings depending on the operator. Omit `value` for `is_set`/`is_not_set`.

## Time period

Use the `query.dateRange` field to control the time window. If the question doesn't mention time, the default is the last hour (`-1h`). Examples of relative dates: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.

# Parameters

All parameters go inside `query`.

## query.serviceNames

Filter by service names. Use `apm-services-list` to discover available services.

## query.statusCodes

Filter by OTel span status codes (list of integers: `0` Unset, `1` OK, `2` Error) — **not** HTTP status codes. Use `[2]` to select error spans.

## query.orderBy

Sort by timestamp: `latest` (default) or `earliest`.

## query.filterGroup

A list of property filters to narrow results. Each filter specifies `key`, `operator`, `type` (span/span_attribute/span_resource_attribute), and optionally `value`. See the "Property filters" section above.

## query.dateRange

Date range to filter results. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.traceId

Filter to a specific trace ID (hex string). Use this when you already know the trace ID.

## query.rootSpans

Set `true` to return **only root spans** — one entry span per matching trace, which collapses each trace to a single row. Useful for "list the traces matching X" without sifting through `matched_filter`. Leave unset (or `false`) to get all spans of matching traces, where you read `matched_filter` to find the ones that matched. The frontend leaves this unset.

## query.flatSpans

Set `true` to return **the matching spans themselves, one row per span** (root and child), rather than collapsing to traces. This is the way to search by a child-span attribute (e.g. `code.filepath`) — the result is the matching child spans directly, not the traces that contain them. Streams under `ORDER BY … LIMIT`, so it stays bounded on hot child attributes where the whole-trace grouping would not. Distinct from `rootSpans` (which scopes whole-trace selection); `prefetchSpans` is ignored. Defaults to false.

## query.limit

Maximum number of results (1-1000). Defaults to 100.

## query.after

Cursor for pagination. Use the `nextCursor` value from the previous response.

## query.prefetchSpans

Number of spans to return per matching trace (1-100), root span first. Useful to preview trace structure without a separate `apm-trace-get`. With the default (1) you get one span per trace (the root); raise it to also pull the matching children and their siblings (check `matched_filter` to tell them apart). Ignored when `rootSpans: true`, which always returns just the root.

## query.excludeAttributes

Set `true` to drop the per-span `attributes` map from results (the map stays present but empty). The attribute map holds multi-KB values like `db.statement`, so excluding it keeps large result sets compact — set it when you only need span structure/timing (`name`, `service_name`, `duration_nano`, `parent_span_id`) and not the OTel attributes. Defaults to false.

# Examples

## List recent error spans

```json
{
  "query": {
    "statusCodes": [2]
  }
}
```

## Search spans from a specific service

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Filter by a span attribute

```json
{
  "query": {
    "filterGroup": [{ "key": "http.method", "operator": "exact", "type": "span_attribute", "value": "POST" }],
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Find slow spans

```json
{
  "query": {
    "filterGroup": [{ "key": "duration", "operator": "gt", "type": "span", "value": "1000000000" }],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Combine service and attribute filters

```json
{
  "query": {
    "serviceNames": ["web-server"],
    "filterGroup": [{ "key": "http.status_code", "operator": "gt", "type": "span_attribute", "value": "399" }],
    "dateRange": { "date_from": "-12h" }
  }
}
```

## Check if a resource attribute exists

```json
{
  "query": {
    "filterGroup": [{ "key": "k8s.pod.name", "operator": "is_set", "type": "span_resource_attribute" }]
  }
}
```

# Reminders

- Ensure that any property filters are directly relevant to the user's question. Avoid unnecessary filtering.
- Use `apm-attributes-list` and `apm-attribute-values-list` to discover attributes before guessing filter keys/values.
- Use `apm-services-list` to discover available services before filtering by service name.
- Duration values are in nanoseconds (1 second = 1,000,000,000 nanoseconds).
