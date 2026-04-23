Query log entries with filtering by severity, service name, date range, search term, and structured attribute filters. Supports cursor-based pagination. The response schema (see the tool's typed output) lists every returned field — prefer `severity_text` over `severity_number` / `level`, and be aware that `trace_id` and `span_id` return zero-padded strings rather than null when unset.

Use `logs-attributes-list` and `logs-attribute-values-list` to discover available attributes before building filters.

# Workflow — follow this order every time

1. **Discover services first.** Call `logs-attribute-values-list` with `key: "service.name"` and `attribute_type: "resource"` to see available services.
2. **Explore resource attributes.** Call `logs-attributes-list` with `attribute_type: "resource"` to discover resource-level attributes (e.g. `k8s.pod.name`, `k8s.namespace.name`). Then call `logs-attribute-values-list` with `attribute_type: "resource"` for relevant attributes to validate what data exists.
3. **Explore log attributes if needed.** Call `logs-attributes-list` (defaults to log attributes) and `logs-attribute-values-list` to discover log-level attributes.
4. **Check volume with a sparkline.** Call `logs-sparkline-query` with the discovered `serviceNames` and filters to see log volume over time. This confirms there is data and shows patterns before you pull individual entries.
5. **Only then query logs.** Once you have confirmed the service name, volume looks right, and relevant filters are set, call `query-logs` with `serviceNames` and any additional filters.

10 attribute/value queries and 1 sparkline query are cheaper than 1 log query. Prefer thorough exploration over speculative log searches.

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

MANDATORY: Never call query-logs without setting `serviceNames` or at least one `log_resource_attribute` filter. Unfiltered log queries are too broad, expensive, and noisy. If the user hasn't specified a service, use the workflow above to discover services first, then ask or infer.

All parameters must be nested inside a `query` object.

# Data narrowing

## Property filters

Use property filters via the `query.filterGroup` field to narrow results. Only include property filters when they are essential to directly answer the user's question.

When using a property filter, you should:

- **Choose the right type.** Log property types are:
  - `log` — filters the log body/message. Use key "message" for this type.
  - `log_attribute` — filters log-level attributes (e.g. "k8s.container.name", "http.method").
  - `log_resource_attribute` — filters resource-level attributes (e.g. k8s labels, deployment info).
- **Use `logs-attributes-list` to discover available attribute keys** before building filters.
- **Use `logs-attribute-values-list` to discover valid values** for a specific attribute key.
- **Find the suitable operator for the value type** (see supported operators below).

**Important:** The `logs-attributes-list` and `logs-attribute-values-list` tools default to `attribute_type: "log"` (log-level attributes). To search resource-level attributes (e.g. `k8s.pod.name`, `k8s.namespace.name`), you must explicitly pass `attribute_type: "resource"`. Forgetting this will return log-level attributes when you intended resource-level ones.

Supported operators:

- String: `exact`, `is_not`, `icontains`, `not_icontains`, `regex`, `not_regex`
- Numeric: `exact`, `gt`, `lt`
- Date: `is_date_exact`, `is_date_before`, `is_date_after`
- Existence (no value needed): `is_set`, `is_not_set`

The `value` field accepts a string, number, or array of strings depending on the operator. Omit `value` for `is_set`/`is_not_set`.

## Time period

Use the `query.dateRange` field to control the time window. If the question doesn't mention time, the default is the last hour (`-1h`). Examples of relative dates: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.

# Parameters

All parameters go inside `query`.

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels.

## query.serviceNames

Filter by service names. Use `logs-attribute-values-list` with `key: "service.name"` and `attribute_type: "resource"` to discover available services.

## query.searchTerm

Full-text search across log bodies. Use this when the user is looking for specific text in log messages.

## query.orderBy

Sort by timestamp: `latest` (default) or `earliest`.

## query.filterGroup

A list of property filters to narrow results. Each filter specifies `key`, `operator`, `type` (log/log_attribute/log_resource_attribute), and optionally `value`. See the "Property filters" section above.

## query.dateRange

Date range to filter results. Defaults to the last hour (`-1h`).

- `date_from`: Start of the range. Accepts ISO 8601 timestamps or relative formats: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.limit

Maximum number of results (1-1000). Defaults to 100.

## query.after

Cursor for pagination. Use the `nextCursor` value from the previous response.

# Examples

## List recent error logs

```json
{
  "query": {
    "severityLevels": ["error", "fatal"],
    "serviceNames": ["<service>"]
  }
}
```

## Search for a specific log message

```json
{
  "query": {
    "searchTerm": "connection refused",
    "serviceNames": ["<service>"],
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Filter logs from a specific service

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Filter by a log attribute

```json
{
  "query": {
    "serviceNames": ["<service>"],
    "filterGroup": [{ "key": "http.status_code", "operator": "exact", "type": "log_attribute", "value": "500" }],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Combine severity and attribute filters

```json
{
  "query": {
    "severityLevels": ["error"],
    "filterGroup": [
      { "key": "k8s.container.name", "operator": "exact", "type": "log_resource_attribute", "value": "web" }
    ],
    "dateRange": { "date_from": "-12h" }
  }
}
```

## Filter by log body content using property filter

```json
{
  "query": {
    "serviceNames": ["<service>"],
    "filterGroup": [{ "key": "message", "operator": "icontains", "type": "log", "value": "timeout" }]
  }
}
```

## Check if an attribute exists

```json
{
  "query": {
    "serviceNames": ["<service>"],
    "filterGroup": [{ "key": "trace_id", "operator": "is_set", "type": "log_attribute" }]
  }
}
```

# Reminders

- Always set `serviceNames` or a resource attribute filter. Never run a broad unfiltered log query.
- Limit `dateRange` to at most `-1d` (24 hours) unless the user explicitly requests a longer range.
- When using `logs-attributes-list` or `logs-attribute-values-list`, remember they default to `attribute_type: "log"`. Pass `attribute_type: "resource"` to search resource-level attributes.
- Ensure that any property filters are directly relevant to the user's question. Avoid unnecessary filtering.
- Use `logs-attributes-list` and `logs-attribute-values-list` to discover attributes before guessing filter keys/values.
- Prefer `searchTerm` for simple text matching; use `filterGroup` with type `log` and key `message` for regex or exact matching.
