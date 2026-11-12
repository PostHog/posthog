# Capture v1

Capture v1 is the batch intake API for analytics and AI events.
This file describes the wire contract and how capture hands events to the rest of the pipeline.
The legacy endpoints (`/batch`, `/e`, `/capture`, `/i/v0/*`) take a different shape. They still serve older SDKs and stay supported, but new senders use v1.

The cross-SDK contract is the `capture` spec in [PostHog/sdk-specs](https://github.com/PostHog/sdk-specs/blob/main/openspec/specs/capture/spec.md).
Public docs: [capture v1 API](https://posthog.com/docs/api/capture-v1) and [SDK upgrade guide](https://posthog.com/docs/libraries/capture-v1).
For changes to this code, see the [`building-on-capture-v1`](../../../../.agents/skills/building-on-capture-v1/SKILL.md) skill.

## Endpoints

| Path                     | Served by                                          | Events                                                                                                    |
| ------------------------ | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `/i/v1/analytics/events` | capture in `Events` and `Import` modes             | Every event except `$ai_*`. For now capture also accepts `$ai_*` events here and routes them to the AI topic. This will be removed. |
| `/i/v1/ai/events`        | capture in `Ai` mode (the `capture-ai` deployment) | `$ai_*` only. Other events drop with `misrouted_event`                                                    |

Both paths use one handler ([`analytics/router.rs`](analytics/router.rs)); [`../router.rs`](../router.rs) decides which mode mounts which path.
A deployment that does not mount a path answers 404.

## Request

Headers ([`constants.rs`](constants.rs), checked in [`context.rs`](context.rs)):

- `Authorization: Bearer <project token>`. A missing header, a malformed token or a personal API key (`phx_`) is a 401 ([`../token.rs`](../token.rs)). A scheme other than `Bearer` is a 400. A well-formed token that matches no project gets a 200 with `ok` results, and nothing is stored.
- Required: `PostHog-Sdk-Info` (`<lib>/<version>`), `PostHog-Attempt` (integer, 1 or more), `PostHog-Request-Id` (UUID), `PostHog-Request-Timestamp` (RFC 3339), `Content-Type: application/json`, `User-Agent`. Capture reports all missing headers in one 400.
- Optional `Content-Encoding`: `gzip`, `deflate`, `br` or `zstd`. Another encoding or `Content-Type` is a 415.

Body ([`analytics/types.rs`](analytics/types.rs) `Batch` and `Event`):

```json
{
  "created_at": "2026-01-01T00:00:00Z",
  "capture_internal": false,
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
- `capture_internal` is an optional batch-level flag, read leniently like an option. PostHog's own senders set it to `true` for events they send on a customer's behalf ([`posthog/api/capture.py`](../../../../posthog/api/capture.py), [`push-capture.ts`](../../../../nodejs/src/messaging/push-subscriptions/push-capture.ts)). Capture then writes `127.0.0.1` as the event IP, because the request comes from a PostHog server, not the user, and partitions cookieless events by token and `127.0.0.1` (`partition_key` and `serialize` in [`analytics/types.rs`](analytics/types.rs)). It is not an option and is not relayed to Kafka. Legacy capture reads a `capture_internal` key in `properties` instead; capture v1 ignores that property.
- Body size limits in code are defaults ([`../config.rs`](../config.rs)). Production limits are set per deployment in the Helm charts. `capture-ai` accepts larger events than the analytics deployments.

## Response

Capture checks each event on its own. A 200 carries one result per event uuid ([`analytics/response.rs`](analytics/response.rs)):

```json
{ "results": { "0190f3a2-...": { "result": "drop", "details": "invalid_options" } } }
```

- `result` is `ok`, `drop`, `warning` (stored, but capture turned person processing off: do not resend) or `retry` (not stored: resend the same event with the same uuid).
- `details` names the reason. The public [result details](https://posthog.com/docs/api/capture-v1#result-details) table lists the common values. In code, new values are constants in [`analytics/constants.rs`](analytics/constants.rs); quota names come from [`quota_limiter_shim.rs`](quota_limiter_shim.rs), and older values are string literals in [`analytics/`](analytics/).
- A problem with one event is a per-event `drop`, not a failed request: a missing or too long `event`, a missing or too large `distinct_id`, a bad `timestamp`, `properties` that is not an object, unreadable `options`, or an event that is too big.
- `duplicates_dropped` counts later copies of the same uuid in the batch.
- Any `retry` result adds `Retry-After: 1`.

A whole-request error ([`error.rs`](error.rs)) is a 400 (missing or invalid headers, a body that is not valid JSON, an empty or invalid batch, an invalid `uuid`), 401, 402 (billing limit, no `Retry-After`), 404, 408, 413, 415 or 5xx.
408 and 5xx carry `Retry-After`.
Capture never returns 429: rate limits are per-event results. The network edge in front of capture can still return 429.

## Options

`options` carries per-event settings that capture or ingestion must act on.
Capture reads four keys ([`analytics/types.rs`](analytics/types.rs) `Options`, `ExpectedOption`):

| Option                    | Type    | What capture does                                                    | Ingestion sets property   |
| ------------------------- | ------- | -------------------------------------------------------------------- | ------------------------- |
| `process_person_profile`  | boolean | Forwards it                                                          | `$process_person_profile` |
| `cookieless_mode`         | boolean | Partitions by token and IP, marks the event cookieless               | `$cookieless_mode`        |
| `disable_skew_correction` | boolean | Keeps the timestamp as sent (the 23-hour future clamp still applies) | `$ignore_sent_at`         |
| `product_tour_id`         | string  | Exempts survey events from the survey quota                          | `$product_tour_id`        |

- Capture reads values leniently (`"false"`, `0`, `"off"` are false). A value it cannot read drops that event with `invalid_options`.
- Capture forwards `properties` to Kafka as raw JSON. A value capture must act on belongs in `options`.
- Settings belong in `options`. For a sender that puts the legacy `$` properties in `properties`, with no SDK to move them into options: ingestion still applies `$process_person_profile` and `$cookieless_mode` when the matching option is not set. Capture does not act on `$ignore_sent_at` or `$product_tour_id` in `properties`: they are stored as ordinary properties, so the timestamp is still corrected and the survey quota still applies.
- Capture writes the parsed options, `session_id`, `window_id` and the `PostHog-Sdk-Info` pair (`req_lib`, `req_lib_version`) to the outer Kafka message as `options` (`OutboundOptions`). This is outside the client-controlled `data`, so consumers can trust it.
- Consumers apply the outer `options`: Node ingestion in [`parse-kafka-message.ts`](../../../../nodejs/src/ingestion/common/steps/event-preprocessing/parse-kafka-message.ts) (`CAPTURE_OPTION_OVERRIDES`), livestream in [`events/kafka.go`](../../../../livestream/events/kafka.go). Each option, `session_id` and `window_id` overwrites its `$` property, so products and queries read the property as before.
- `req_lib` and `req_lib_version` only fill: ingestion sets `$lib` and `$lib_version` from them when the event's `$lib` is not a non-empty string, and sets `$lib_version` alone when `$lib` equals `req_lib` and `$lib_version` is not a non-empty string. SDKs set their own `$lib`.
- A service that reads and re-produces capture messages must keep the outer `options` and the `legacy_property_splice` header (`CapturedEvent` and `CapturedEventHeaders` in [`common/types/src/event.rs`](../../../common/types/src/event.rs)).
- `CAPTURE_V1_LEGACY_PROPERTY_SPLICE` makes capture also write those `$` properties into `data`. It is off in production; do not depend on it.
