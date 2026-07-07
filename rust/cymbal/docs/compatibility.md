# Cymbal HTTP compatibility

Remote symbol resolution is an internal implementation detail of cymbal.
The external Node.js error-tracking consumer contract stays unchanged.

## `/process` request and response

- Node still sends `POST /process` to cymbal with an array of `AnyEvent`-shaped exception events.
- Cymbal still returns an array with the same length and ordering as the request.
- Each non-null response entry is the same `AnyEvent` shape with updated `properties`.
- `null` entries keep their existing meaning: the event was suppressed by the normal cymbal pipeline.
- Remote resolution only changes how cymbal fills the exception list before properties, grouping, linking, suppression, and alerting continue.

## Node-side chunking

`nodejs/src/ingestion/error-tracking/cymbal/client.ts` chunks HTTP requests by estimated original event body size before they reach cymbal.
That remains valid with remote resolution enabled because cymbal preserves the HTTP boundary and performs private exception-level gRPC work after it receives an HTTP chunk.

No generated type changes are needed:

- the Node request type remains `CymbalRequest`
- the Node response type remains `(CymbalResponse | null)[]`
- the internal `cymbal.resolution.v1` gRPC messages are not exposed to Node

## Remote rollout controls behind the HTTP boundary

- `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` deterministically chooses remote vs local resolution per event.
- Sampled events use the remote pool and do not silently fall back to local resolution on remote failures.
- Unsampled events use the local exception and frame resolvers.
- Sampled remote exceptions are grouped per team, flattened into `ResolveItem`s, and submitted over per-endpoint bidirectional `Resolve` streams.
- Resolver-specific context is carried in `ResolveItem.metadata` as JSON bytes. The native symbolication convention uses a `debug_images_json` key.
- Per-item `ResolveOutcome.Error.kind` is the control-flow surface. `ERROR_KIND_OVERLOADED` is result-only backpressure and triggers item reroute. Accepted items emit `ResolveOutcome.Accepted` before their terminal outcome; cymbal releases its routing permit on that acceptance signal. If `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MS` is non-zero, the overloaded endpoint is also temporarily excluded from new routing in that cymbal process. Repeated overloads double that cooldown up to `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MAX_MS`, and a quiet `CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_DECAY_MS` window resets it. `CYMBAL_REMOTE_RESOLUTION_ROUTING_JITTER` controls how much routing flattens across the rendezvous-ranked candidate list (`0.0` strict rank-0 sticky, `1.0` uniform across candidates). `LoadEvent` is only endpoint freshness/draining state.

This means Node request chunking limits protect cymbal's public HTTP body size, while cymbal's private gRPC path owns exception-level routing, reroute depth, and overload handling.
