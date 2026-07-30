# Fixing `ignored_invalid_timestamp`

An event's `timestamp` property couldn't be parsed, so PostHog **ingested the event with the server's arrival time** instead of the intended one.
Category `event`, severity `warning`: no event was lost, but its time is wrong — which quietly corrupts trends, funnels with time windows, and historical imports (everything lands at import time).

Note this is strictly about **unparseable** timestamps. Events that arrive late with _valid_ timestamps (mobile SDKs flushing offline queues, batched backends) are handled normally and don't produce this warning.

## What it means in your code

The timestamp string isn't a format PostHog can parse. Common sources:

- locale formats: `"07/08/2026 14:32"`, `"8 Jul 2026"`,
- unix epochs sent as strings or in seconds where milliseconds are expected,
- `Date` objects serialized via string concatenation instead of `.toISOString()`,
- out-of-range values (year 0 or five digits) from arithmetic bugs.

## Diagnose

1. `posthog:ingestion-warnings-list` with `type: ignored_invalid_timestamp`. The sample details carry the offending `value` and a `reason` from the parser — usually self-explanatory.
2. Grep the app for where `timestamp` is set on capture calls (custom timestamps are most common in backend SDKs and migration/import scripts).

## Fix

Send ISO 8601 with timezone:

```js
client.capture({
  distinctId,
  event: 'order shipped',
  timestamp: new Date(order.shippedAt).toISOString(), // '2026-07-08T14:32:00.000Z'
})
```

If you don't need a custom time, omit `timestamp` entirely — the SDK stamps it correctly. For historical imports, validate the conversion on a sample before running the batch: mis-parsed rows are ingested at "now" and cannot be re-dated afterwards.

## Verify

Re-run the flow or a sample of the import, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm new events carry the intended times.

## Related

- [fixing-event-dropped-too-old.md](fixing-event-dropped-too-old.md) — the other timestamp-related surprise: **valid** but old timestamps (e.g. mobile offline queues flushing days later) dropped by a team-configured threshold.
