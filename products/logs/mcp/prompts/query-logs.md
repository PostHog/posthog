Query log entries with filtering by severity, service name, date range, search term, and structured attribute filters. Supports cursor-based pagination. The response schema (see the tool's typed output) lists every returned field — prefer `severity_text` over `severity_number` / `level`, and be aware that `trace_id` and `span_id` return zero-padded strings rather than null when unset.

Use `logs-attributes-list` and `logs-attribute-values-list` to discover available attributes before building filters.

# Workflow — follow this order every time

1. **Discover services first.** Call `logs-attribute-values-list` with `key: "service.name"` and `attribute_type: "resource"` to see available services.
2. **Explore resource attributes.** Call `logs-attributes-list` with `attribute_type: "resource"` to discover resource-level attributes (e.g. `k8s.pod.name`, `k8s.namespace.name`). Then call `logs-attribute-values-list` with `attribute_type: "resource"` for relevant attributes to validate what data exists.
3. **Explore log attributes if needed.** Call `logs-attributes-list` (defaults to log attributes) and `logs-attribute-values-list` to discover log-level attributes.
4. **Size the total volume with `logs-count`.** Call `logs-count` with the discovered `serviceNames` and filters. If it exceeds `query-logs`'s max `limit` of 1000 — or if the user's question is about _when_ something happened — continue to step 5.
5. **Find where the volume sits with `logs-count-ranges`.** Call `logs-count-ranges` to get time-bucketed counts. Each bucket carries explicit `date_from`/`date_to` you can pass straight back as the next call's `dateRange` to drill into a sub-range. Recurse up to 3–4 levels to narrow onto a spike or a specific window. Stop when the bucket width drops below your precision goal (e.g. 1 minute).
6. **Only then query logs.** Once the count is in range and the window is right-sized, call `query-logs` with `serviceNames` and any additional filters.

Many cheap calls (attribute/value queries, counts, count-ranges) beat one expensive `query-logs`. Prefer thorough exploration over speculative log searches.

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

## Filtering logs by a PostHog person

When the user references a person — by `distinct_id`, name, email, or via a prior `persons-retrieve` call — filter logs to that person via a `log_attribute` filter. The attribute key is configurable per project (it defaults to `distinct_id`); read `logs_distinct_id_attribute_key` from the team config (returned on `projects-retrieve` / `environments-retrieve`, or via the `/api/projects/:id/logs_config/` endpoint) and use that as the filter `key`.

If the team has not configured a custom key, use `distinct_id`. If a person has multiple `distinct_ids`, pass the array as the filter `value` with operator `exact` (matches any of them).

```json
{
  "query": {
    "serviceNames": ["<service>"],
    "filterGroup": [
      {
        "key": "distinct_id",
        "operator": "exact",
        "type": "log_attribute",
        "value": ["<distinct_id_1>", "<distinct_id_2>"]
      }
    ]
  }
}
```

Do not invent a different attribute key based on what looks plausible — use the configured key. If the configured key returns zero results, the customer's logs pipeline may not stamp person identity at all; tell the user rather than guessing.

## Time period

Use the `query.dateRange` field to control the time window. If the question doesn't mention time, the default is the last hour (`-1h`). Examples of relative dates: `-1h`, `-6h`, `-1d`, `-7d`, `-30d`.

# Parameters

All parameters go inside `query`.

## query.severityLevels

Filter by log severity: `trace`, `debug`, `info`, `warn`, `error`, `fatal`. Omit to include all levels.

This filter is an **exact match against the response's `severity_text` field** using these six lowercase buckets — it is _not_ a numeric range and _not_ case-insensitive. If a service ingests non-canonical severity strings (e.g. `"ERROR"`, `"Warning"`, `"err"`), `severityLevels: ["error"]` will not match them and you will get zero rows. When a severity filter returns nothing unexpectedly, discover the actual stored values with `logs-attribute-values-list { key: "severity_text" }` and either filter on the value you find or fall back to a `searchTerm`. See "Severity fields in the response" below for the `severity_text` / `severity_number` / `level` mapping.

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

## query.excludeAttributes

Set `true` to drop the per-log `attributes` and `resource_attributes` maps from results (the maps stay present but empty). These maps can hold large values, so excluding them keeps big result sets compact — set it when you only need `body`, `severity_text`, `timestamp`, and `service`-level fields and not the full attribute maps. Defaults to false.

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

# Severity fields in the response

Each returned log row carries three overlapping severity fields. Read and report `severity_text`; treat the other two as redundant:

| Field             | What it is                                                      | Use it for                                                            |
| ----------------- | --------------------------------------------------------------- | --------------------------------------------------------------------- |
| `severity_text`   | Canonical severity string. **Prefer this.**                     | Filtering (`severityLevels`), grouping, and anything you show a user. |
| `severity_number` | OpenTelemetry numeric severity (1–24). Redundant with the text. | Sorting by exact severity, or interop with OTel tooling.              |
| `level`           | ClickHouse alias for `severity_text`. Redundant.                | Ignore — prefer `severity_text`.                                      |

`severity_number` maps to the `severityLevels` buckets by OTel range. Use this when you only have a number and need the bucket, or vice-versa:

| Bucket  | `severity_number` range | Canonical `severity_text` |
| ------- | ----------------------- | ------------------------- |
| `trace` | 1–4                     | `trace`                   |
| `debug` | 5–8                     | `debug`                   |
| `info`  | 9–12                    | `info`                    |
| `warn`  | 13–16                   | `warn`                    |
| `error` | 17–20                   | `error`                   |
| `fatal` | 21–24                   | `fatal`                   |

When the user asks for "warnings and above", that is `severityLevels: ["warn", "error", "fatal"]` — there is no numeric `>=` operator on the top-level severity filter.

# If the query fails (500 / timeout)

A `query-logs` call that returns a 500 almost always means the query scanned too much data and timed out server-side — it is rarely a bug in your filters. Do not retry the same call. Instead, narrow and re-size:

1. Shorten `dateRange` (e.g. `-1h` instead of `-1d`).
2. Add `serviceNames` or a `log_resource_attribute` filter to reduce the scan.
3. Size the volume with `logs-count`, then locate the busy window with `logs-count-ranges`, before pulling rows again.

# Reminders

- Always set `serviceNames` or a resource attribute filter. Never run a broad unfiltered log query.
- Limit `dateRange` to at most `-1d` (24 hours) unless the user explicitly requests a longer range.
- When using `logs-attributes-list` or `logs-attribute-values-list`, remember they default to `attribute_type: "log"`. Pass `attribute_type: "resource"` to search resource-level attributes.
- Ensure that any property filters are directly relevant to the user's question. Avoid unnecessary filtering.
- Use `logs-attributes-list` and `logs-attribute-values-list` to discover attributes before guessing filter keys/values.
- Prefer `searchTerm` for simple text matching; use `filterGroup` with type `log` and key `message` for regex or exact matching.
