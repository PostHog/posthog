# Fixing the session replay warnings

These warnings come from the **session replay ingestion pipeline** — note the two `message_*` types don't say "replay" in their names, but they are replay warnings (category `replay`).
The symptom side is recordings that never appear or play back with gaps: each dropped message is a chunk of a recording, so a session can exist but miss segments.

| Type                                      | Severity | What happened                                                                                                                                      |
| ----------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `replay_lib_version_too_old`              | info     | Recording sent by posthog-js 1.x below 1.75 — **still processed**, but the SDK is too old to support all recording features. Debounced per version |
| `message_contained_no_valid_rrweb_events` | warning  | A snapshot message carried no usable rrweb events — **that chunk was dropped**                                                                     |
| `message_timestamp_diff_too_large`        | warning  | A snapshot message's event timestamps are 7+ days away from now — **that chunk was dropped**                                                       |

## Diagnose

1. `posthog:ingestion-warnings-list` with the specific `type` (or `q: 'replay'` plus `q: 'message_'`). For `message_timestamp_diff_too_large` the details carry `startDiffDays`/`endDiffDays` vs the 7-day threshold — the magnitude tells the story (8 days = buffering/late flush; hundreds/negative-looking = a broken client clock).
2. **Check SDK version clustering first** (`$lib_version` on the affected sessions' events, via `posthog:execute-sql`): `replay_lib_version_too_old` names the outdated version outright in its details, and the other two also concentrate on old or unusual SDK versions when the payload shape is the problem.
3. For `message_contained_no_valid_rrweb_events`, look between the SDK and PostHog: a rewriting reverse proxy, compression/decompression middleware, or a custom transport that truncates or re-serializes the snapshot payload is the usual cause when the SDK is current.
4. Distinguish clock from buffer for timestamp diffs: a device with a wrong clock produces the warning **continuously** for that user; buffered/offline replay produces **bursts** on reconnect.

## Fix

- **Old posthog-js** (`replay_lib_version_too_old`): upgrade to a current version — 1.75 is the floor for full recording support, but go to latest; recording pipelines evolve quickly. Hunt pinned snippets so every page ships the same version.
- **Mangled snapshots** (`no_valid_rrweb_events`): let replay traffic reach PostHog unmodified — remove or fix payload-rewriting proxies and custom transports; upgrade the SDK if it predates the current snapshot format.
- **Timestamp diffs**: fix client clocks where the skew is persistent. Where it's buffering: replay is designed for near-real-time delivery — snapshot chunks older than 7 days are dropped by design, so recordings can't be imported or replayed into PostHog after the fact.

## Verify

Record a fresh session on the affected app/platform, re-query `posthog:ingestion-warnings-list` with a post-fix `since` — no new occurrences — and confirm the new recording appears (`posthog:query-session-recordings-list`) and plays back complete, without gaps.
