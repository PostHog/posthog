---
name: fixing-cookieless-warnings
description: >
  Diagnoses and fixes the cookieless-mode ingestion warnings — `cookieless_missing_timestamp`, `cookieless_timestamp_out_of_range`, `cookieless_missing_user_agent`, `cookieless_missing_ip`, and `cookieless_missing_host` — raised when a cookieless event lacks an ingredient needed to compute its anonymous ID, so the event was dropped.
  Use when a user asks why cookieless events are missing, why cookieless tracking "doesn't work", or when `posthog:ingestion-warnings-list` shows any `cookieless_*` type.
---

# Fixing the cookieless warnings

A cookieless-mode event was **dropped** because an ingredient required to compute its identity was missing or unusable.
Category `event`, severity `error` for all five types: without the ingredient there is no way to know who the event belongs to, so it cannot be ingested at all.

## How cookieless identity works (why these fields are mandatory)

In cookieless mode the client stores nothing — events arrive with the sentinel distinct ID `$posthog_cookieless`, and PostHog computes a rotating anonymous ID server-side by hashing **calendar day + user agent + IP + host**. Every warning in this family is one missing ingredient:

| Type                                | Missing ingredient                                                                                          |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `cookieless_missing_timestamp`      | No usable timestamp (event `timestamp`, `sent_at`, or arrival time)                                         |
| `cookieless_timestamp_out_of_range` | Timestamp's calendar day isn't plausibly current — in the future, or further past than ingestion lag allows |
| `cookieless_missing_user_agent`     | No `$raw_user_agent` property                                                                               |
| `cookieless_missing_ip`             | No `$ip` property                                                                                           |
| `cookieless_missing_host`           | No `$host` property                                                                                         |

The daily rotation is the privacy property — and it means cookieless has a built-in constraint: **events must arrive close to when they happened**. Old events can't be identified retroactively, by design.

Who supplies which ingredient (browser flow): posthog-js sends `$raw_user_agent` and `$host` on every event; **`$ip` is never sent by the client** — capture records the connection's client IP and ingestion attaches it as `$ip` when the property is absent. Stock posthog-js in cookieless mode therefore works with no extra setup.

## Diagnose

Which ingredient is missing points at which layer is broken:

1. `posthog:ingestion-warnings-list` with `q: 'cookieless'` (or per type). Samples carry the event name and UUID.
2. Map the missing field to the layer:
   - **`$raw_user_agent` / `$host` missing** → the events aren't coming from stock posthog-js: a non-browser producer sending the cookieless sentinel, or middleware (`before_send`, a rewriting proxy) stripping properties.
   - **`$ip` missing** → the capture path saw no client IP — a proxy/CDN in front of PostHog not passing the client address through, or middleware explicitly deleting `$ip` before the identity is computed.
   - **timestamp missing** → server-side batching that strips timestamps.
   - **timestamp out of range** → a historical import routed through cookieless (can't work, see below), badly skewed client clocks, or offline queues flushing much later.
3. If cookieless events produce **no warnings and no events at all**, check the project setting first: cookieless server hash mode must be enabled on the team — with it disabled, sentinel events are dropped without a warning.

## Fix

- **Browser via stock posthog-js**: no properties to add — fix whatever strips them (a rewriting proxy, a `before_send` hook), and ensure any proxy in front of PostHog forwards the client IP.
- **Server-side capture** (your backend relays browser traffic): explicitly set `$raw_user_agent`, `$host`, **and `$ip`** from the original browser request on every cookieless event, and timestamp at capture time. The `$ip` is mandatory here even though no warning demands it while your server's IP fills the gap: without it, every user hashes on the **server's** IP and collapses into shared identities — silently, with no warning at all.
- **Privacy middleware**: if something scrubs `$ip` before PostHog, exempt cookieless events — the IP is a hash input, not stored as identity.
- **Historical imports/backfills**: don't route them through cookieless — past calendar days can't be hashed. Imports need real distinct IDs.
- **Late delivery**: cookieless requires timely arrival; events buffered for days will be dropped as out-of-range. If the client legitimately buffers that long, cookieless is the wrong mode for it.

## Verify

Re-run the flow, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new `cookieless_*` occurrences — and confirm cookieless events appear with computed anonymous IDs.

## Related

- `resolving-ingestion-warnings` — the triage entry point.
- `fixing-ignored-invalid-timestamp` — timestamp problems outside cookieless mode (kept at server time instead of dropped).
