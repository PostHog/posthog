Query trace spans with filtering by service name, status code, date range, and structured attribute filters. Supports cursor-based pagination. Returns spans with uuid, trace_id, span_id, parent_span_id, name, kind, service_name, status_code, timestamp, end_time, duration_nano, and is_root_span.

Use 'apm-attributes-list' and 'apm-attribute-values-list' to discover available attributes before building filters. Use 'apm-services-list' to discover available services.

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

All parameters must be nested inside a `query` object.

# Data narrowing

## Property filters

Use property filters via the `query.filterGroup` field to narrow results. Only include property filters when they are essential to directly answer the user's question.

When using a property filter, you should:

- **Choose the right type.** Span property types are:
  - `span` — filters built-in span fields (trace_id, span_id, duration, name, kind, status_code).
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

Filter by HTTP status codes (list of integers).

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

Filter to root spans only. Defaults to true. Set to false to include all spans in the trace tree.

## query.limit

Maximum number of results (1-1000). Defaults to 100.

## query.after

Cursor for pagination. Use the `nextCursor` value from the previous response.

## query.prefetchSpans

Number of child spans to prefetch per trace (1-100). Useful to get a preview of trace structure without fetching the full trace.

# Examples

## List recent error spans

```json
{
  "query": {
    "statusCodes": [500, 503]
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
