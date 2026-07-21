Latency over time — trace counts per (time bucket, duration bucket) cell, combining `apm-spans-sparkline` and `apm-spans-duration-histogram` into one call: "when did latency change, and how".

Returns one row per non-empty `(time bucket, duration bucket)` cell:

- `time` — ISO 8601 bucket start (UTC)
- `bucket_ns` — duration bucket floor in nanoseconds, on the 1-2-5 series (1ms, 2ms, 5ms, 10ms, 20ms, ...)
- `count` — traces whose ROOT span duration falls in that cell (or spans, when `rootSpans` is false)

Time buckets are sized adaptively to the window (roughly 50 buckets regardless of range, e.g. `-1h` → ~minute buckets, `-7d` → ~4-hour buckets). A time bucket with no matching traces returns a single sentinel row `{time, bucket_ns: 0, count: 0}`, so the full time axis can be read off the response — ignore sentinel rows when reading densities.

Use to answer:

- "When did this service get slow?" — the slow band's first non-empty `time` is the onset.
- "Is the latency regression a shift (whole distribution moved) or a new mode (a second band appeared)?"
- "Did the deploy at 14:00 change the latency profile, not just the p95?"
- "Is the slow tail constant background or bursty?"

For a single distribution with per-service breakdown, use `apm-spans-duration-histogram`; for counts over time, `apm-spans-sparkline`; for per-operation percentiles, `apm-spans-aggregate`.

All parameters must be nested inside a `query` object.

# Reading the grid

Group rows by `bucket_ns` and read each duration bucket as a horizontal band over time:

- A band that exists in every time bucket at similar counts = steady-state population.
- A band that starts at a specific `time` = something changed then (deploy, dependency, cache).
- The whole distribution stepping up one or two buckets at once = a uniform slowdown.

# Parameters

All parameters go inside `query`.

## query.dateRange

Date range for the grid. Defaults to the last hour.

- `date_from`: Start of the range. ISO 8601 or relative: `-1h`, `-6h`, `-1d`, `-7d`.
- `date_to`: End of the range. Same format. Omit or null for "now".

## query.serviceNames

List of service names to restrict the grid to. Use `apm-services-list` to discover services.

## query.statusCodes

Filter by OTel span status codes (list of integers: `0` Unset, `1` OK, `2` Error) — **not** HTTP status codes. Use `[2]` to select error spans.

## query.rootSpans

When true (default), cells count **traces by their root span's duration** — the request the user experienced, lining up with `apm-spans-duration-histogram`. Set false to count every matching span instead; combine with a `name` filter for one operation's latency over time.

## query.filterGroup

Property filters applied to the counted spans. Same filter shape and operators as `query-apm-spans`:

- `span` — built-in span fields (trace_id, span_id, duration, name, kind, status_code, is_root_span)
- `span_attribute` — span-level attributes
- `span_resource_attribute` — resource-level attributes

# Examples

## When did api-gateway get slow, over the last day?

```json
{
  "query": {
    "serviceNames": ["api-gateway"],
    "dateRange": { "date_from": "-1d" }
  }
}
```

## One operation's latency over time (span-level, not per trace)

```json
{
  "query": {
    "rootSpans": false,
    "filterGroup": [{ "key": "name", "operator": "exact", "type": "span", "value": ["SELECT orders"] }],
    "dateRange": { "date_from": "-6h" }
  }
}
```

# Reminders

- `bucket_ns` is nanoseconds: 1ms = 1,000,000; 1s = 1,000,000,000. Buckets follow the 1-2-5 series; a 3.5ms trace lands in the 2ms bucket (bucket floor).
- `{bucket_ns: 0, count: 0}` rows are the sentinel time-axis filler described above — skip them when reading densities.
- Default counts are **traces** (one per root span); they line up with `apm-spans-duration-histogram`, not with `apm-spans-count`.
- Cells carry no service breakdown — narrow with `serviceNames` instead.
- After spotting when the slow band appeared, pull the actual traces with `query-apm-spans` filtered to that time window plus a `duration` filter (nanoseconds), `orderBy: "duration"`.
