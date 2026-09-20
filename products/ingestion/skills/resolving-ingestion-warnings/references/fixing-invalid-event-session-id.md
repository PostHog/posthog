# Fixing `invalid_event_session_id`

An analytics event carried a `$session_id` that isn't a valid UUID. PostHog **ingested the event**, but its session id is dropped from session analytics: the v3 sessions table and the `$session_id_uuid` materialized column keep only valid-UUID ids.
Category `event`, severity `warning`: no event was lost, but it won't appear in session-level analysis — session duration, replay linkage, and any funnel or trend grouped by session will silently undercount.

## What it means in your code

The `$session_id` you send isn't a UUID (PostHog accepts any valid UUID and itself generates UUIDv7). A `$session_id` set manually in a browser `capture()` call is normally overwritten by the SDK's own session manager, so the source is almost always one of:

- **Server-side SDKs** (Node, Python, Go, …) setting a custom `$session_id` from a business identifier — an order id, a request id, a user id — instead of a UUID.
- **A custom `bootstrap.sessionID`** in posthog-js that isn't a valid UUID (it bypasses the SDK's session manager and is not validated client-side).
- **A reverse proxy or gateway** rewriting or injecting `$session_id`.

## Diagnose

1. Query the warnings with `posthog:execute-sql`:
   ```sql
   SELECT timestamp, details FROM system.ingestion_warnings
   WHERE type = 'invalid_event_session_id' AND timestamp > now() - INTERVAL 7 DAY
   ORDER BY timestamp DESC LIMIT 20
   ```
   `details` carries the offending `sessionId` (truncated to 200 chars) and the `eventUuid`. The shape of the value usually names the source — a numeric id, an email, or a slug rather than a UUID.
2. Cluster by `$lib` / `$lib_version` (server SDKs are the usual culprit) and grep the app for where `$session_id` / `bootstrap.sessionID` is set.

## Fix

Send a valid UUID as `$session_id` — ideally a **UUIDv7**, which sorts by time and is what PostHog generates:

```js
import { v7 as uuidv7 } from 'uuid'

const sessionId = uuidv7() // reuse for the life of the session
client.capture({ distinctId, event: 'checkout started', properties: { $session_id: sessionId } })
```

In the browser, prefer letting posthog-js manage sessions — don't set `$session_id` yourself. If you must seed it, pass a UUIDv7 as `bootstrap.sessionID`. Never use a business identifier (user id, order id) as the session id.

## Verify

Re-run the flow, then re-query `system.ingestion_warnings` (filter `type = 'invalid_event_session_id'`, `timestamp` after your fix) — no new occurrences — and confirm the affected sessions now appear in session analytics.

## Related

- [fixing-session-replay-warnings.md](fixing-session-replay-warnings.md) — the capture-produced `invalid_session_id`, which **rejects the recording outright** (session replay) rather than keeping the event as this one does.
- [fixing-invalid-distinct-ids.md](fixing-invalid-distinct-ids.md) — the same "a business id was passed where an identifier belongs" mistake, for `distinct_id`.
