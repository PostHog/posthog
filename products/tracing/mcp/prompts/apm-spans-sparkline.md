Span counts over time — a zero-filled time series for trend and spike analysis.

Returns one row per `(time bucket, service)` pair:

- `time` — ISO 8601 bucket start (UTC)
- `service` — service name (top 10 services per bucket)
- `count` — spans in that bucket matching the filters

Buckets are sized adaptively to the window (roughly 50 buckets regardless of range, e.g. `-1h` → ~minute buckets, `-7d` → ~hour buckets). Quiet stretches return zero-count rows, so the series is continuous — read spike timing straight off the `time` values.

Use to answer:

- "When did the error rate spike?" (see the error-trend workflow below)
- "Is traffic to service X growing, flat, or bursty?"
- "Did span volume change after the deploy at 14:00?"
- "Which time window should I zoom into before pulling raw spans?"

For a single aggregate number per operation, use `apm-spans-aggregate` instead. For latency distribution, use `apm-spans-duration-histogram`.

All parameters must be nested inside a `query` object.

# Error-trend workflow

Two calls, then divide per bucket:

1. `apm-spans-sparkline` with your filters → total counts per bucket.
2. The same call with `statusCodes: [2]` added → error counts per bucket.

Error rate per bucket = errors / total. The bucket where the ratio jumps is when the spike started.

# Parameters

All parameters go inside `query`.

## query.dateRange

Date range for the series. Defaults to the last hour.

- `date_from`: Start of the range. ISO 8601 or relative: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

List of service names to restrict the series to. Use `apm-services-list` to discover services.

## query.statusCodes

Filter by OTel span status codes (list of integers: `0` Unset, `1` OK, `2` Error) — **not** HTTP status codes. Use `[2]` to select error spans.

## query.filterGroup

Property filters applied to the counted spans. Same filter shape and operators as `query-apm-spans`:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes
- `span_resource_attribute` — resource-level attributes

# Examples

## Span volume per service over the last 6 hours

```json
{
  "query": {
    "dateRange": { "date_from": "-6h" }
  }
}
```

## Error spans only, one service, last day

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "statusCodes": [2],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Request (root span) volume trend

```json
{
  "query": {
    "filterGroup": [{ "key": "is_root_span", "operator": "exact", "type": "span", "value": true }],
    "dateRange": { "date_from": "-1d" }
  }
}
```

# Reminders

- Counts are **spans**, not traces — filter `is_root_span = true` to count requests/traces.
- Zero-count rows are bucket filler; read non-zero rows for activity and zero rows for gaps.
- Only the top 10 services per bucket are returned — narrow with `serviceNames` when a busy project drowns out the service you care about.
- Use `apm-services-list`, `apm-attributes-list`, `apm-attribute-values-list` to discover values before filtering.
