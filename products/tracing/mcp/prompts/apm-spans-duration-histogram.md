Trace counts per logarithmic duration bucket — the latency distribution of requests.

Returns one row per `(duration bucket, service)` pair:

- `bucket_ns` — bucket floor in nanoseconds, on the 1-2-5 series (1ms, 2ms, 5ms, 10ms, 20ms, ...)
- `service` — service name (top 10 services per bucket)
- `count` — traces whose ROOT span duration falls in the bucket

Buckets count **traces by their root span's duration** (the request the user experienced), never child spans. Only non-empty buckets are returned.

Use to answer:

- "What does the latency distribution look like — one population or bimodal?"
- "How many requests took longer than 1 second?"
- "Is the long tail a handful of outliers or a real second mode?"
- "Which duration range should I filter on before pulling slow traces?"

For percentiles per operation (p50/p95), use `apm-spans-aggregate`. For counts over time, use `apm-spans-sparkline`.

All parameters must be nested inside a `query` object.

# Parameters

All parameters go inside `query`.

## query.dateRange

Date range. Defaults to the last hour.

- `date_from`: Start of the range. ISO 8601 or relative: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

List of service names to restrict the histogram to. Use `apm-services-list` to discover services.

## query.statusCodes

Filter by OTel span status codes (list of integers: `0` Unset, `1` OK, `2` Error) — **not** HTTP status codes. Use `[2]` to select error spans.

## query.filterGroup

Property filters applied to the matched spans. Same filter shape and operators as `query-apm-spans`:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes
- `span_resource_attribute` — resource-level attributes

# Examples

## Latency distribution for one service over the last day

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## Distribution of error traces only

```json
{
  "query": {
    "statusCodes": [2],
    "dateRange": { "date_from": "-6h" }
  }
}
```

# Reminders

- `bucket_ns` is nanoseconds: 1ms = 1,000,000; 1s = 1,000,000,000.
- Counts are **traces** (one per root span), so they line up with request counts — not with `apm-spans-count`, which counts every span.
- Buckets follow the 1-2-5 series; a trace of 3.5ms lands in the 2ms bucket (bucket floor).
- To fetch the actual slow traces after spotting a tail, use `query-apm-spans` with a `duration` filter (nanoseconds) and `orderBy: "duration"`.
