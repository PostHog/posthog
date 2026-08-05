Aggregate trace span statistics as a call tree — one row per `(parent_service, parent_name) → (service_name, name)` edge.

Requires a `spanName` to bound the matched trace set (the `(trace_id, parent_span_id)` self-join is unsafe at high cardinality without it), and a `serviceName` to scope the returned tree to a single service. All traces that contain at least one span with the given name in the given service are included, and every span in those traces from that service is aggregated against its parent.

Returns rows with:

- `parent_service`, `parent_name` — the parent span identity (`parent_name` is `"<ROOT>"` for root spans)
- `service_name`, `name` — the child span identity
- `count` — number of spans matched for this `(parent, child)` edge
- `total_duration_nano`, `avg_duration_nano`, `p50_duration_nano`, `p95_duration_nano`, `p99_duration_nano`, `p999_duration_nano` — duration stats in nanoseconds (`p999_duration_nano` is the 99.9th percentile; only meaningful for high-volume edges)
- `error_count` — child spans with OTel status code `Error` (status_code = 2)
- `avg_start_offset_nano` — average nanoseconds from the parent span's start to this child's start
- `calls_per_parent_invocation` — how many times this child runs per parent invocation (null for root edges). A child can top `total_duration_nano` purely by fan-out volume; divide by this to compare per-call cost

Rows are ordered by `total_duration_nano` DESC and capped at 5000.

Use to answer:

- "What does the `/checkout` flow actually call downstream?"
- "Which child operation under `POST /orders` is the slowest?"
- "Where is time spent inside `process_payment` — DB, external API, or something else?"
- "Did the call tree under `/api/feed` change between last week and this week?" (with `compareFilter`)

For a flat per-operation view (no parent linkage), use `apm-spans-aggregate` instead.

All parameters must be nested inside a `query` object.

# Comparison window

Set `query.compareFilter.compare: true` to also fetch a comparison window. The response then includes a `compare` array of the same shape as `results`.

- Omit `compare_to` (or set null) to compare against the immediately previous period of equal length.
- Set `compare_to: "-7d"` to compare against the window 7 days earlier (same length as the primary window).

# Data narrowing

## Property filters

`query.filterGroup` narrows the matched span set. Same filter shape and operators as `apm-spans-aggregate` / `query-apm-spans`:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes
- `span_resource_attribute` — resource-level attributes

Use `apm-attributes-list` and `apm-attribute-values-list` to discover available attribute keys/values.

## Time period

Use `query.dateRange` to control the time window. Default is the last hour (`-1h`).

# Parameters

All parameters go inside `query`.

## query.spanName (required)

The span name that anchors the matched trace set. Every trace containing at least one span with this name (in the given `serviceName`) is included.

Pick a high-level entry-point span (e.g. an HTTP route or job name). Generic names (`HTTP`, `GET`) match too many traces and produce noisy aggregates. Use `query-apm-spans` first if you need to discover concrete span names.

## query.serviceName (required)

The service the tree should be scoped to. Applied to the spans CTE so the returned rows only contain spans from this service, even when the matched traces also touch other services. Use `apm-services-list` to discover service names.

## query.dateRange

Date range for the primary window. Defaults to the last hour.

- `date_from`: Start of the range. ISO 8601 or relative: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.compareFilter

Optional comparison-window configuration. Same shape as in `apm-spans-aggregate`.

## query.serviceNames

List of service names to filter the matched span set. Use `apm-services-list` to discover services.

## query.filterGroup

Property filters applied to both windows. See the "Property filters" section.

# Examples

## Call tree under a specific operation in the last hour

```json
{
  "query": {
    "spanName": "POST /api/orders",
    "serviceName": "web-server"
  }
}
```

## Call tree over the last day

```json
{
  "query": {
    "spanName": "checkout_flow",
    "serviceName": "web-server",
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Compare today's call tree vs last week

```json
{
  "query": {
    "spanName": "POST /api/orders",
    "serviceName": "web-server",
    "dateRange": { "date_from": "-1d" },
    "compareFilter": { "compare": true, "compare_to": "-7d" }
  }
}
```

## Restrict to error-bearing traces

```json
{
  "query": {
    "spanName": "POST /api/orders",
    "serviceName": "web-server",
    "filterGroup": [{ "key": "status_code", "operator": "exact", "type": "span", "value": 2 }]
  }
}
```

# Reminders

- `spanName` and `serviceName` are both required. Bound `spanName` to a specific high-level span (avoid generic names like `HTTP`); set `serviceName` to the one service whose call-tree you want.
- Root spans have `parent_name = "<ROOT>"` and `avg_start_offset_nano = 0`.
- Duration values are in nanoseconds.
- Results are ordered by `total_duration_nano` DESC and capped at 5000 rows.
- `calls_per_parent_invocation` is derived from the returned rows. If results hit the 5000-row cap (only happens with very high span-name cardinality in one service), a parent's edges can be split across the cut and the ratio can read high — treat it as approximate when the row count is at the cap.
- For a flat per-operation aggregate without parent linkage, use `apm-spans-aggregate`.
- Use `apm-services-list`, `apm-attributes-list`, `apm-attribute-values-list` to discover values before filtering.
