# Capture v1

Capture v1 is the batch intake API for analytics and AI events.
This file describes the wire contract and how capture hands events to the rest of the pipeline.
The cross-SDK contract is the `capture` spec in [PostHog/sdk-specs](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md).
Public docs: [capture v1 API](https://posthog.com/docs/api/capture-v1) and [SDK upgrade guide](https://posthog.com/docs/libraries/capture-v1).

## Endpoints

| Path                     | Served by                                            | Events                                       |
| ------------------------ | ---------------------------------------------------- | -------------------------------------------- |
| `/i/v1/analytics/events` | capture in `Events` and `Import` modes               | All events. `$ai_*` events go to the AI topic |
| `/i/v1/ai/events`        | capture in `Ai` mode (the `capture-ai` deployment)   | `$ai_*` only. Others drop with `misrouted_event` |

Both paths use one handler ([`analytics/router.rs`](analytics/router.rs)); [`../router.rs`](../router.rs) decides which mode mounts which path.
The legacy endpoints (`/batch`, `/e`, `/capture`, `/i/v0/*`) take a different shape. New code does not use them.

## Request

Headers ([`constants.rs`](constants.rs), checked in [`context.rs`](context.rs)):

- `Authorization: Bearer <project token>`. Missing or invalid is a 401.
- Required: `PostHog-Sdk-Info` (`<lib>/<version>`), `PostHog-Attempt` (integer, 1 or more), `PostHog-Request-Id` (UUID), `PostHog-Request-Timestamp` (RFC 3339), `Content-Type: application/json`, `User-Agent`. Capture reports all missing headers in one 400.
- Optional `Content-Encoding`: `gzip`, `deflate`, `br` or `zstd`. Anything else is a 415.

Body ([`analytics/types.rs`](analytics/types.rs) `Batch` and `Event`):

```json
{
  "created_at": "2026-01-01T00:00:00Z",
  "historical_migration": false,
  "batch": [
    {
      "event": "signed_up",
      "uuid": "0190f3a2-...",
      "distinct_id": "user-123",
      "timestamp": "2026-01-01T00:00:00Z",
      "session_id": "0190f3a2-...",
      "properties": { "plan": "pro" },
      "options": { "process_person_profile": true }
    }
  ]
}
```

- `event`, `uuid`, `distinct_id` and `timestamp` are JSON strings. `properties` and `options` are objects. `session_id` and `window_id` are strings, sent only when present. Capture ignores other fields.
- Body size limits in code are defaults ([`../config.rs`](../config.rs)). Production limits are set per deployment in the Helm charts.

## Response

Capture checks each event on its own. A 200 carries one result per event uuid ([`analytics/response.rs`](analytics/response.rs)):

```json
{ "results": { "0190f3a2-...": { "result": "drop", "details": "invalid_options" } } }
```

- `result` is `ok`, `drop`, `warning` (accepted, person processing off: do not resend) or `retry` (not stored: resend the same event with the same uuid).
- `details` names the reason. The values are constants in [`analytics/constants.rs`](analytics/constants.rs) and [`quota_limiter_shim.rs`](quota_limiter_shim.rs).
- `duplicates_dropped` counts later copies of the same uuid in the batch.
- Any `retry` result adds `Retry-After: 1`.

A whole-request error ([`error.rs`](error.rs)) is a 400 (headers, JSON, a missing or wrong-typed required field, an invalid `uuid`), 401, 402 (over quota, no `Retry-After`), 408, 413, 415 or 5xx.
408 and 5xx carry `Retry-After`.
There is no 429: rate limits show up as per-event results.

## Options

`options` carries per-event settings that capture or ingestion must act on.
Capture reads four keys and ignores all others ([`analytics/types.rs`](analytics/types.rs) `Options`, `ExpectedOption`):

| Option                    | Type    | What capture does                                                  | Ingestion sets property   |
| ------------------------- | ------- | ------------------------------------------------------------------ | ------------------------- |
| `process_person_profile`  | boolean | Forwards it                                                         | `$process_person_profile` |
| `cookieless_mode`         | boolean | Partitions by token and IP, marks the event cookieless              | `$cookieless_mode`        |
| `disable_skew_correction` | boolean | Keeps the timestamp as sent (the 23-hour future clamp still applies) | `$ignore_sent_at`         |
| `product_tour_id`         | string  | Exempts survey events from the survey quota                         | `$product_tour_id`        |

- Capture reads values leniently (`"false"`, `0`, `"off"` are false). A value it cannot read drops that event with `invalid_options`.
- Capture never parses `properties`. It forwards them as raw JSON, so it cannot act on a property.
- Capture writes the parsed options, `session_id`, `window_id` and the `PostHog-Sdk-Info` pair (`req_lib`, `req_lib_version`) to the outer Kafka message as `options` (`OutboundOptions`). This is outside the client-controlled `data`, so consumers can trust it.
- Consumers apply the outer `options`: Node ingestion in [`parse-kafka-message.ts`](../../../../nodejs/src/ingestion/common/steps/event-preprocessing/parse-kafka-message.ts) (`CAPTURE_OPTION_OVERRIDES`), livestream in [`events/kafka.go`](../../../../livestream/events/kafka.go). Each option overwrites its `$` property, so products and queries read the property as before.
- `CAPTURE_V1_LEGACY_PROPERTY_SPLICE` makes capture also write those `$` properties into `data`. It is off in production; do not depend on it.
