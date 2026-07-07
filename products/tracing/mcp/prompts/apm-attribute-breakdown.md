Group spans by one attribute's value — the "what is different about the bad spans?" tool.

Returns one row per distinct value of the chosen attribute, across the spans matching the filters:

- `value` — the attribute's value (`''` for spans that don't carry the attribute)
- `count` — spans with that value
- `error_count` — of those, spans with OTel status `Error` (status_code = 2)
- `p50_duration_nano`, `p95_duration_nano` — duration quantiles in nanoseconds

Rows are ordered by `count` DESC (or `error_count` DESC via `orderBy`) and capped at 5000.

Use to answer:

- "Which attribute values are over-represented among the errored/slow spans?"
- "Which downstream destination (`server.address`) is failing?"
- "What `http.response.status_code` values are we getting back, and how often?"
- "Which pod / version / region is the bad traffic concentrated on?" (resource attributes)

For aggregates grouped by operation, use `apm-spans-aggregate`. For trends over time, use `apm-spans-sparkline`.

All parameters must be nested inside a `query` object.

# "What's different" workflow

1. Scope to the bad spans with `filterGroup` (e.g. `status_code = Error`) or `serviceNames`.
2. Discover candidate keys with `apm-attributes-list` (don't guess — keys vary per project).
3. Run `apm-attribute-breakdown` per candidate key. A value owning most of the `count` is your signature.
4. To confirm over-representation, re-run without the bad-spans filter (or check `error_count / count` per row): a value at 95% of errors but 10% of all traffic is the smoking gun.

# Parameters

All parameters go inside `query`.

## query.breakdownKey (required)

The attribute key to group by (e.g. `server.address`, `http.response.status_code`, `k8s.pod.name`). Discover keys with `apm-attributes-list`.

## query.breakdownType (required)

- `span_attribute` — span-level attributes (e.g. `server.address`, `db.statement`)
- `span_resource_attribute` — resource-level attributes (e.g. `k8s.pod.name`, `service.version`)

## query.orderBy

`count` (default) or `error_count` — rows are sorted by the chosen column, descending.

## query.dateRange

Date range for the primary window. Defaults to the last hour.

- `date_from`: Start of the range. ISO 8601 or relative: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.compareFilter

Optional comparison-window configuration. Set `compare: true` to also get the breakdown for a previous window under `compare` — useful for "did this value's share change vs last week?" (`compare_to: "-7d"`).

## query.serviceNames

List of service names to restrict the breakdown to. Use `apm-services-list` to discover services.

## query.filterGroup

Property filters scoping the spans the breakdown runs over. Same filter shape and operators as `query-apm-spans`:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes
- `span_resource_attribute` — resource-level attributes

# Examples

## Which destinations do the errored spans hit?

```json
{
  "query": {
    "breakdownKey": "server.address",
    "breakdownType": "span_attribute",
    "filterGroup": [{ "key": "status_code", "operator": "exact", "type": "span", "value": "Error" }],
    "dateRange": { "date_from": "-1h" }
  }
}
```

## Which values drive the most errors overall?

```json
{
  "query": {
    "breakdownKey": "http.response.status_code",
    "breakdownType": "span_attribute",
    "orderBy": "error_count",
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Is the bad pod's share new? (compare vs last week)

```json
{
  "query": {
    "breakdownKey": "k8s.pod.name",
    "breakdownType": "span_resource_attribute",
    "serviceNames": ["cdp-worker"],
    "dateRange": { "date_from": "-1d" },
    "compareFilter": { "compare": true, "compare_to": "-7d" }
  }
}
```

# Reminders

- `value: ''` groups the spans that don't carry the attribute at all — often itself a signal.
- Duration values are in nanoseconds (1s = 1,000,000,000).
- Use `apm-attributes-list` / `apm-attribute-values-list` to discover keys before guessing.
- `error_count / count` per row is the error rate for that value — compute it when judging over-representation.
