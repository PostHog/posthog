Query log entries with filtering by severity, service name, date range, search term, and structured attribute filters. Supports cursor-based pagination. Returns log entries with timestamp, body, level, service_name, trace_id, and attributes.

Use 'logs-list-attributes' and 'logs-list-attribute-values' to discover available attributes before building filters.

CRITICAL: Be minimalist. Only include filters and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

All parameters must be nested inside a `query` object.

# Data narrowing

## Property filters

Use property filters via the `query.filterGroup` field to narrow results. Only include property filters when they are essential to directly answer the user's question.

When using a property filter, you should:

- **Choose the right type.** Log property types are:
  - `log` — filters the log body/message. Use key "message" for this type.
  - `log_attribute` — filters log-level attributes (e.g. "k8s.container.name", "http.method").
  - `log_resource_attribute` — filters resource-level attributes (e.g. k8s labels, deployment info).
- **Use `logs-list-attributes` to discover available attribute keys** before building filters.
- **Use `logs-list-attribute-values` to discover valid values** for a specific attribute key.
- **Find the suitable operator for the value type** (see supported operators below).

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

Filter by service names. Use `logs-list-attribute-values` with `key: "service.name"` to discover available services.

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
    "severityLevels": ["error", "fatal"]
  }
}
```

## Search for a specific log message

```json
{
  "query": {
    "searchTerm": "connection refused",
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
    "filterGroup": [{ "key": "message", "operator": "icontains", "type": "log", "value": "timeout" }]
  }
}
```

## Check if an attribute exists

```json
{
  "query": {
    "filterGroup": [{ "key": "trace_id", "operator": "is_set", "type": "log_attribute" }]
  }
}
```

# Reminders

- Ensure that any property filters are directly relevant to the user's question. Avoid unnecessary filtering.
- Use `logs-list-attributes` and `logs-list-attribute-values` to discover attributes before guessing filter keys/values.
- Prefer `searchTerm` for simple text matching; use `filterGroup` with type `log` and key `message` for regex or exact matching.
