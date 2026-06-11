Get adaptive-interval bucket counts for a filtered log stream. Returns a flat list of `{date_from, date_to, count}` buckets covering the requested window. Modeled on Elasticsearch's `auto_date_histogram` — caller specifies a target bucket count, the engine picks the interval.

Use this to find **where the volume is concentrated** before pulling rows. Cheaper than `query-logs`, more agent-friendly than `logs-sparkline-query` (each bucket carries explicit `date_from`/`date_to` you can feed straight back as the next call's `dateRange` to drill in).

# When to use this vs other tools

- **`logs-count`** — total volume in a window. Scalar.
- **`logs-count-ranges`** (this tool) — _when_ in the window the volume sits. Time-bucketed.
- **`query-logs`** — pull individual log rows. Most expensive; only call after counts confirm the window is right-sized.

# Recursion pattern (the main reason this tool exists)

Use the response to narrow into a sub-range without reasoning about interval width:

1. Call `logs-count-ranges` with the user's window (e.g. last 24h).
2. Pick the bucket(s) of interest (densest, an obvious spike, an unexpectedly empty stretch).
3. Call `logs-count-ranges` again with that bucket's `date_from` and `date_to` as the next `dateRange`.
4. Repeat up to ~3–4 levels — stop when buckets are shorter than your precision goal (e.g. 1 minute).
5. Once narrowed, call `query-logs` for the actual rows.

This is the same pattern Elasticsearch users follow with `auto_date_histogram`. Keep recursion shallow — every call is cheap individually but they multiply quickly.

# Parameters

All parameters must be nested inside a `query` object.

## query.dateRange

Window to bucket. Defaults to the last hour (`-1h`). Same format as `query-logs`.

## query.targetBuckets

Approximate bucket count. Defaults to **10**, max 100. The engine picks the interval adaptively from a fixed list (1/5/10s, 1/2/5/10/15/30/60/120/240/360/720/1440m) to land near this target — actual count may differ slightly. Empty buckets are dropped, so the response can have fewer rows than `targetBuckets`.

Pick a value based on what you're doing:

- **10** (default) — overview, finding spikes, "is this concentrated or spread out?"
- **20–30** — characterising a known busy window
- **50+** — high-resolution drill-down, only when you know the window is small

## query.severityLevels, query.serviceNames, query.searchTerm, query.filterGroup

Same shape as `query-logs`. Applied **before** bucketing.

# Response

```json
{
  "ranges": [
    { "date_from": "2026-04-26T00:00:00", "date_to": "2026-04-26T02:24:00", "count": 1024 },
    { "date_from": "2026-04-26T02:24:00", "date_to": "2026-04-26T04:48:00", "count": 47 }
  ],
  "interval": "2h"
}
```

- `ranges` — buckets ordered by `date_from` ascending. **Empty buckets are omitted** — infer gaps by comparing each bucket's `date_to` to the next bucket's `date_from`.
- `interval` — short-form duration of the chosen bucket width (`1s` / `5m` / `1h` / `1d`). Informational only — for follow-up queries, use the per-bucket `date_from`/`date_to`.

# Examples

## Find when errors spiked over the last day

```json
{
  "query": {
    "dateRange": { "date_from": "-1d" },
    "targetBuckets": 24,
    "serviceNames": ["api-gateway"],
    "severityLevels": ["error", "fatal"]
  }
}
```

## Drill into the densest hour from a previous call

After picking the densest bucket from the response above (say `{date_from: "2026-04-26T15:00:00", date_to: "2026-04-26T16:00:00", count: 894}`):

```json
{
  "query": {
    "dateRange": {
      "date_from": "2026-04-26T15:00:00",
      "date_to": "2026-04-26T16:00:00"
    },
    "targetBuckets": 12,
    "serviceNames": ["api-gateway"],
    "severityLevels": ["error", "fatal"]
  }
}
```

# Reminders

- Cap recursion at ~3–4 levels. If your bucket width drops below your precision goal (e.g. 1 minute), stop and call `query-logs`.
- Empty windows return `{"ranges": [], "interval": "..."}` — that's not an error, it's "I asked, nothing matched."
- Always include `serviceNames` or a resource attribute filter, just like `query-logs`. Don't bucket the entire team's log stream.
