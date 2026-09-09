Answers "how slow is it, across all requests?" — the latency distribution, as trace counts per logarithmic duration bucket.

Use it for:

- "What does the latency distribution look like — one population or bimodal?"
- "How many requests took longer than 1 second?"
- "Is the long tail a handful of outliers or a real second mode?"

One call reads the whole population. Rows are capped at the top 10 services per duration bucket, so summing `count` undercounts a bucket that more than ten services land in; filter `serviceNames` to ten or fewer services for an exact total. Do not estimate the distribution by listing spans with `query-apm-spans` — that result is capped and sorted, so it shows the tail, not the shape.

Sibling tools: for when the distribution changed use `apm-spans-latency-heatmap`; for p50/p95 per operation use `apm-spans-aggregate`; for counts over time use `apm-spans-sparkline`; for where the time goes inside one operation use `apm-spans-tree`.

# Return shape

One row per `(duration bucket, service)` pair:

- `bucket_ns` — bucket floor in nanoseconds, on the 1-2-5 series (1ms, 2ms, 5ms, 10ms, 20ms, ...)
- `service` — service name (top 10 services per bucket)
- `count` — traces whose ROOT span duration falls in the bucket

Buckets count **traces by their root span's duration** (the request the user experienced), never child spans. Only non-empty buckets are returned.

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
