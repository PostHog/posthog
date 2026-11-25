# Cymbal HTTP compatibility

Remote symbol resolution is an internal implementation detail of cymbal.
It does not change the HTTP contract with the Node.js error-tracking consumer.

## `/process` with one result for each event

A caller that sends `X-PostHog-Ingestion-Response: 1` to `POST /process` gets one result for each event.
The request body is the same array of `AnyEvent`-shaped exception events.
The response follows the ingestion response contract in [`common/ingestion-response`](../../common/ingestion-response/README.md) and carries the same header.
A cymbal version that does not know the header answers with the array described in the next section and without the header, so the caller picks its parser from the response header.

| `result` | Meaning for cymbal |
| --- | --- |
| `ok` | The event was processed. `value` is the same `AnyEvent` shape with updated `properties`. |
| `drop` | The normal cymbal pipeline dropped the event. `reason` is `suppressed`, `suppressed_by_rule`, `rate_limited_per_issue`, or `rate_limited_project`. |
| `fail` | The event's own data cannot be processed, such as a malformed event or `properties` that is not an object. The resolution service can also report an item as poison, but does not yet. The code is `invalid_input`. |
| `retry` | The resolution pool did not resolve the event, but resolved another event of the request. The code is `deadline_exceeded` when the resolution deadline passed, and `resolution_unavailable` when every attempt on a resolution pod failed. |

A request with more events than `PROCESS_MAX_EVENTS_PER_REQUEST` (10000 by default) is rejected with a 413.

An `ok` event that has `$cymbal_errors` also carries an `error_tracking_exception_processing_errors` warning with those errors.

When no event of the request resolved and at least one would answer `retry`, the request fails with a 500 and no event answers `retry`.
Any other failure that can come from a dependency, such as a database or Kafka error, also fails the whole request with a 500, as the contract requires.

## `/process` request and response

Without the header, `/process` answers with the contract the Node.js error-tracking consumer uses.

- The caller sends `POST /process` with an array of `AnyEvent`-shaped exception events.
- Cymbal returns an array with the same length and ordering as the request.
- Each non-null response entry is the same `AnyEvent` shape with updated `properties`.
- `null` entries mean the event was suppressed by the normal cymbal pipeline.
- A slot has no way to report a failed event, so one failed or unresolved event fails the whole request with a 500, and one malformed event rejects the whole body with a 422.
- Remote resolution only changes how cymbal fills the exception list before properties, grouping, linking, suppression, and alerting continue.

## Node-side chunking

`nodejs/src/ingestion/pipelines/errortracking/cymbal/client.ts` chunks HTTP requests by estimated original event body size before they reach cymbal.
That remains valid because cymbal preserves the HTTP boundary and performs private exception-level gRPC work after it receives an HTTP chunk.

No generated type changes are needed:

- the Node request type remains `CymbalRequest`
- the Node response type remains `(CymbalResponse | null)[]`
- the internal `cymbal.resolution.v1` gRPC messages are not exposed to Node

## Remote resolution behind the HTTP boundary

- Events use the remote pool and do not silently fall back to inline resolution on failures.
- Events are flattened into exception-level `ResolveItem`s. Items are grouped by their first symbol-set reference when available, with a per-team fallback, then submitted over per-endpoint bidirectional `Resolve` streams.
- Resolver-specific context is carried in `ResolveItem.metadata` as JSON bytes. The native symbolication convention uses a `debug_images_json` key.
- `Done.release_id` carries the newest release bound to a symbol set the item's frames reference. It is empty when none of them has a release, and on servers that predate the field, so callers treat empty as "no release". The processing side uses it only as the fallback source for `$exception_release`, behind the event's own `$release_id` and mobile app metadata.
- Per-item `ResolveOutcome.Error.kind` is the control-flow surface. `ERROR_KIND_OVERLOADED` is result-only backpressure and triggers item reroute. Accepted items emit `ResolveOutcome.Accepted` before their terminal outcome; cymbal releases its routing permit on that acceptance signal. If `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MS` is non-zero, the overloaded endpoint is also temporarily excluded from new routing in that cymbal process. Repeated overloads double that cooldown up to `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MAX_MS`, and a quiet `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_DECAY_MS` window resets it. `CYMBAL_REMOTE_RESOLUTION_ROUTING_JITTER` controls how much routing flattens across the load-adjusted rendezvous-ranked candidate list (`0.0` strict top load-adjusted candidate, `1.0` load-weighted across candidates). `LoadEvent` carries endpoint freshness/draining state plus `in_flight` / `max_in_flight` as a soft routing load signal.

This means Node request chunking limits protect cymbal's public HTTP body size, while cymbal's private gRPC path owns exception-level routing, reroute depth, and overload handling.
