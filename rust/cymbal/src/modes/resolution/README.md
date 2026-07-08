# Resolution mode (`CYMBAL_MODE=resolution`)

gRPC service that owns exception-level symbol resolution for PostHog error tracking.
It is a run mode of the `cymbal` binary, selected with `CYMBAL_MODE=resolution`.
It speaks `cymbal.resolution.v1` and is used by cymbal's processing mode (the client lives in
[`stages/resolution/remote`](../../stages/resolution/remote)) when remote resolution is enabled.

## Architecture

```text
                   ┌────────────────────────────────────────────────────┐
events ──HTTP─────▶│ cymbal                                             │
                   │ /process pipeline                                  │
                   │                                                    │
                   │  ┌──────────────────────────────────────────────┐  │
                   │  │ ResolutionStage                              │  │
                   │  │ - partitions events into local/remote        │  │
                   │  │ - builds ResolveItems at resolution time     │  │
                   │  └──────────────────────┬───────────────────────┘  │
                   │                         │ sampled remote events    │
                   │  ┌──────────────────────▼───────────────────────┐  │
                   │  │ EndpointPool                                 │  │
                   │  │ - DNS-discovered endpoints                   │  │
                   │  │ - per-endpoint Resolve mux                   │  │
                   │  │ - Subscribe freshness snapshots              │  │
                   │  └──────────────┬─────────────────┬─────────────┘  │
                   └─────────────────┼─────────────────┼────────────────┘
                                     │                 │
                                     │ Resolve         │ Subscribe
                                     │ long-lived bidi │ long-lived stream
                                     │ stream carrying │ carrying LoadEvent
                                     │ ResolveItem /   │ ticks
                                     │ ResolveOutcome  │
                                     ▼                 ▼
                   ┌────────────────────────────────────────────────────┐
                   │ cymbal-resolution                                  │
                   │                                                    │
                   │  Resolve handler                                   │
                   │  - admits each item independently                  │
                   │  - emits one terminal outcome per item             │
                   │                                                    │
                   │  Subscribe handler                                 │
                   │  - emits freshness/draining ticks                  │
                   └────────────────────────────────────────────────────┘
```

The contract is intentionally split across two streams:

- **`Resolve`** is bidirectional work traffic. The caller sends independent `ResolveItem`s, each with a per-stream id, `team_id`, serialized exception JSON, JSON `metadata` bytes, and an item deadline. The server emits an `Accepted` outcome when it admits an item, then exactly one terminal `ResolveOutcome` with the same id: `Done`, `Retry`, or `Error`.
- **`Subscribe`** is endpoint freshness, draining, and soft load state. The cymbal-side `EndpointPool` opens one long-lived stream per pod and treats the latest `LoadEvent` as a freshness snapshot plus an `in_flight` / `max_in_flight` routing bias. `LoadEvent` does not carry overload state or suggested batch sizing.

`Error.kind` is the shared control-flow surface:

- `ERROR_KIND_INVALID_PAYLOAD` means the exception payload or `metadata` bytes do not match the wire convention.
- `ERROR_KIND_POISON` is reserved for well-formed user-provided symbol/stack data that should not be retried.
- `ERROR_KIND_UNHANDLED` is an unexpected resolver failure.
- `ERROR_KIND_OVERLOADED` is result-only backpressure. Callers reroute the item with overload-specific backoff.

The proto lives at [`proto/cymbal/resolution/v1/resolution.proto`](../../../../../proto/cymbal/resolution/v1/resolution.proto).

## Rollout model

Remote resolution is opt-in on the cymbal side. There is intentionally **no silent local fallback** for events sampled into the remote path: when the pool cannot satisfy a sampled remote item, cymbal surfaces an `UnhandledError` for that event so the failure is visible rather than masked. Events not selected by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` are not remote attempts; they run through the inline local exception/frame resolvers.

| Mode | Cymbal env vars | Resolution path |
| ---- | --------------- | --------------- |
| Local | `CYMBAL_REMOTE_RESOLUTION_ENABLED=false` (default) | Inline local resolver inside `cymbal` |
| Sampled remote | `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`, sampled by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` | gRPC to the `cymbal-resolution` pool, no fallback |
| Unsampled local | `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`, not sampled by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` | Inline local resolver inside `cymbal` |

### Enabling remote mode

1. Deploy `cymbal-resolution` pods behind a headless Kubernetes service so each pod is reachable by IP. `cymbal` resolves the service hostname via DNS and opens one channel per returned address.
2. Confirm the pods are serving:
   - `/_liveness` returns `ok`
   - `/_readiness` returns `ok`
   - `cymbal_remote_resolution_pool_size` becomes non-zero on cymbal pods once they are pointed at the service.
3. Set on `cymbal` pods:
   - `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`
   - `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE=<0.0..=1.0>` (defaults to `0.0`, so enabling alone routes no traffic)
   - `CYMBAL_REMOTE_RESOLUTION_HOST=<service-hostname>`
   - `CYMBAL_REMOTE_RESOLUTION_PORT=50061` (default)
4. Roll cymbal pods. Startup eagerly resolves DNS and fails loudly if the host is empty, no addresses come back, or no endpoint produces a fresh non-draining `LoadEvent` during the readiness window.

### Routing affinity and reroute behavior

Routing is per exception. The caller derives a routing key from the first
symbol-set reference in the exception's raw frames and rendezvous-hashes
`team:{team_id}:symbol:{symbol_set_ref}` against the pod set. Exceptions
without a symbol-set reference fall back to `team:{team_id}`. This keeps work
that needs the same symbol set sticky to a small, stable part of the pod set
while preserving the previous team-level fallback for frames that do not use
symbol stores. The rendezvous score is adjusted by the latest server load
snapshot and the caller's own local in-flight count, so highly loaded pods
become less likely to receive new work before they return overload outcomes.

Each endpoint owns one bidirectional Resolve mux with a bounded outbound queue and one waiter per in-flight item. Queue admission failure, stream break, endpoint drain, and endpoint eviction all fail affected items as `ERROR_KIND_OVERLOADED`; the per-item retry layer excludes that endpoint and reroutes only those items. A `Retry` outcome uses the generic retry policy. Cymbal also holds a process-local routing semaphore for items trying to find an accepting pod; a permit is acquired before routing, released on `Accepted`, and otherwise held until routing exhausts or fails terminally. Terminal `ErrorKind`s fail the current all-or-nothing rollout path.

### Disabling / rolling back

Set `CYMBAL_REMOTE_RESOLUTION_ENABLED=false` on the cymbal pods and roll. That fully reverts to local resolution; no data-plane state needs to be flushed and the `cymbal-resolution` pods can keep running without harm.

For a partial rollback, lower `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE`. The decision is deterministic by `(team_id, event_uuid)`, so the same event keeps the same local/remote decision across retries, pods, and process restarts.

### Compatibility with the Node error-tracking consumer

The Node consumer still talks only to cymbal's HTTP `POST /process` endpoint. Cymbal preserves the response array shape and input ordering after internal remote resolution, so Node-side request chunking by HTTP body size remains valid and no generated type changes are needed. See [`cymbal/docs/compatibility.md`](../cymbal/docs/compatibility.md).

## Configuration

### Cymbal client (`cymbal` binary)

All variables are prefixed `CYMBAL_REMOTE_RESOLUTION_` and live on `cymbal::config::Config`.

| Env var | Default | Purpose |
| ------- | ------- | ------- |
| `CYMBAL_REMOTE_RESOLUTION_ENABLED` | `false` | Master switch. `true` routes sampled exception resolution through the remote pool. |
| `CYMBAL_REMOTE_RESOLUTION_HOST` | _empty_ | Service hostname resolved via DNS. Required when enabled; empty value fails boot. |
| `CYMBAL_REMOTE_RESOLUTION_PORT` | `50061` | gRPC port the pods listen on. Must match the server-side `GRPC_ADDRESS` port. |
| `INTERNAL_API_SECRET` | _empty_ | Shared secret sent as `X-Internal-Api-Secret` on every `Resolve` and `Subscribe` RPC. Required when remote mode is enabled. |
| `CYMBAL_REMOTE_RESOLUTION_DNS_REFRESH_SECS` | `30` | How often DNS is re-resolved and the pool reconciled. |
| `CYMBAL_REMOTE_RESOLUTION_DEADLINE_MS` | `15000` | Shared per-event remote deadline used by all item reroutes. |
| `CYMBAL_REMOTE_RESOLUTION_CONNECT_TIMEOUT_MS` | `1000` | Per-endpoint TCP/HTTP2 connect timeout. |
| `CYMBAL_REMOTE_RESOLUTION_MAX_RETRIES` | `2` | Caller-side reroutes after transport, overload, or `Retry` outcomes. |
| `CYMBAL_REMOTE_RESOLUTION_RETRY_BACKOFF_MS` | `50` | Base retry backoff before jitter. |
| `CYMBAL_REMOTE_RESOLUTION_RETRY_MAX_BACKOFF_MS` | `1000` | Maximum retry backoff after exponential scaling and jitter. |
| `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` | `0.0` | Deterministic event-level remote rollout rate. |
| `CYMBAL_REMOTE_RESOLUTION_ROUTING_ACCEPTANCE_CONCURRENCY` | `10` | Maximum number of items per cymbal process that can wait concurrently for a pod to emit `Accepted`. |
| `CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_TICK_HINT_MS` | `1000` | Cadence hint sent on `SubscribeRequest`; snapshots are considered fresh for two ticks. |
| `CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_RECONNECT_BACKOFF_MS` | `500` | Backoff between subscription reconnect attempts when a stream terminates. |

### Resolution-mode server (`CYMBAL_MODE=resolution`)

| Env var | Default | Purpose |
| ------- | ------- | ------- |
| `GRPC_ADDRESS` | `0.0.0.0:50061` | Bind address for the gRPC server. |
| `METRICS_PORT` | `9101` | HTTP port for `/_liveness`, `/_readiness`, and `/metrics`. |
| `INTERNAL_API_SECRET` | _empty_ | Shared secret required as `X-Internal-Api-Secret` metadata on every gRPC request. Empty configuration rejects all RPCs. |
| `MAX_CONCURRENT_REQUESTS` | `256` | Hard cap on in-flight gRPC streams. Excess returns `UNAVAILABLE` from the gRPC load-shed layer. `0` disables the cap. |
| `SYMBOL_RESOLUTION_CONCURRENCY` | `64` | Cap on concurrent symbol-resolution operations across all in-flight items. |
| `MAX_ITEM_CONCURRENCY` | `64` | Process-wide cap on concurrently processed exception items. Excess items receive `ERROR_KIND_OVERLOADED`. |
| `SERVICE_INSTANCE_ID` | random UUID | Identifier surfaced to callers via `LoadEvent` on the Subscribe stream. |
| `SUBSCRIBE_TICK_INTERVAL_MS` | `1000` | Default `LoadEvent` heartbeat cadence when callers do not suggest one. Load events may be emitted earlier when draining changes or in-flight load crosses coarse thresholds. |
| `SUBSCRIBE_MIN_TICK_MS` | `100` | Lower bound for the Subscribe tick cadence. |
| `SUBSCRIBE_MAX_TICK_MS` | `10000` | Upper bound for the Subscribe tick cadence. |

The server inherits the narrow subset of cymbal's env-var surface needed by `build_symbol_resolver` and internal gRPC authentication: `INTERNAL_API_SECRET`, Postgres, object storage, symbol-store cache/resolver tuning, and outbound HTTP controls. Frame result cache knobs such as `FRAME_RESOLVED_TTL_SECONDS` and `FRAME_UNRESOLVED_TTL_SECONDS` are read through cymbal's shared symbol resolver config, not duplicated in `cymbal-resolution`'s own `Config`. It does not connect to Kafka, Redis, or the signals API.

Shared-secret callers are service-scoped today, so authenticated cymbal pods are permitted to resolve all teams. If future callers carry a team-scoped identity, the `Resolve` handler must reject any `ResolveItem.team_id` outside the caller's allowed team set before scheduling resolution work.

## Operator guidance

### Health and discovery endpoints

| Surface | Where | Notes |
| ------- | ----- | ----- |
| Liveness | `GET :{METRICS_PORT}/_liveness` | Static `ok`. Use to detect crashed pods. |
| Readiness | `GET :{METRICS_PORT}/_readiness` | Static `ok` today; safe to flip to a real probe later. |
| Prometheus metrics | `GET :{METRICS_PORT}/metrics` | Includes `cymbal_remote_resolution_*` and generic `grpc_server_*`. |
| gRPC | `:{GRPC_ADDRESS}` `cymbal.resolution.v1.CymbalResolution` | Headless service DNS name → one channel per pod. |

### Reading the metrics

These metric names are exported by the cymbal client unless noted. Definitions live in [`cymbal/src/metric_consts.rs`](../cymbal/src/metric_consts.rs) and the server's Resolve/LoadMonitor modules.

- **Rollout decisions**: `cymbal_remote_resolution_sampling_total{decision="remote"|"local"}`. `local` during a partial rollout is expected and is not fallback.
- **Item attempts and latency**: `cymbal_remote_resolution_requests_total{outcome, reason?}` and `cymbal_remote_resolution_latency_ms`. The counter is emitted on logical item attempts; `reason` is only a bounded transport status tag.
- **Reroute shape**: `cymbal_remote_resolution_reroute_depth{outcome}` records how many endpoint changes happened before the terminal item result. The legacy attempts histogram may still be emitted for dashboard continuity, but new alerts should use reroute depth.
- **Protocol error taxonomy**: client-observed `cymbal_remote_resolution_error_kinds_total{kind}` and server-emitted `cymbal_remote_resolution_server_error_kinds_total{kind}` count `ErrorKind` values with bounded labels.
- **Overload backpressure**: `cymbal_remote_resolution_overload_escalations_total` counts overloaded item results that are escalated into reroutes. On the server, `grpc_server_load_shed_total{method="Resolve"}` covers gRPC stream admission shedding and `cymbal_remote_resolution_server_in_flight_items` shows active item processing.
- **Endpoint pool health**: `cymbal_remote_resolution_pool_size`, `cymbal_remote_resolution_endpoint_in_flight{endpoint}`, `cymbal_remote_resolution_endpoint_mux_in_flight{endpoint}`, and server-side `cymbal_remote_resolution_server_in_flight_items` show discovery health, selected endpoint usage, active mux waiters, and the load signal used by routing.
- **Per-endpoint local admission**: `cymbal_remote_resolution_endpoint_admission_rejections_total{endpoint, reason}` counts bounded mux queue and closed-stream rejections before an item leaves the cymbal pod.
- **Subscribe health**: `cymbal_remote_resolution_load_subscriptions_total{outcome="connected"|"reconnect"}` tracks the freshness/draining stream lifecycle. Sustained reconnects translate into `pool_empty` with `reason="no_fresh_load_snapshots"` because endpoints without fresh snapshots are excluded from selection.

### Failure interpretation cheat sheet

| Symptom | Likely cause | Suggested response |
| ------- | ------------ | ------------------ |
| `pool_empty` spikes after cymbal startup | DNS refresh removed every endpoint, Subscribe has not produced fresh snapshots, or every endpoint reports draining | Inspect the `reason` label (`no_endpoints`, `no_fresh_load_snapshots`, `all_endpoints_draining`); startup fails for these states while remote resolution is enabled. |
| `sampling_total{decision="local"}` rises while remote errors stay flat | Expected partial rollout or lower sample rate | No action unless the configured sample rate is wrong. |
| `transport_retry{reason="unavailable"}` + `grpc_server_load_shed_total` | Server is at `MAX_CONCURRENT_REQUESTS` | Scale server pods or raise the cap after capacity-checking. |
| `error_kinds_total{kind="overloaded"}` + rising reroute depth | Item-level overload backpressure | Scale server pods, tune item concurrency, or lower sample rate. |
| `endpoint_admission_rejections_total{reason="queue_full"}` | Local mux queue saturated before the item reached gRPC | Scale endpoints or increase the mux queue only after checking memory. |
| `transport_retry{reason="deadline_exceeded"}` with low load | Caller-side deadline shorter than worst-case resolution | Raise `CYMBAL_REMOTE_RESOLUTION_DEADLINE_MS`. |
| `error_kinds_total{kind="invalid_payload"}` | Wire-format or metadata mismatch | Check deploy skew and the metadata JSON convention. |
| `requests_total{outcome="exhausted"}` sustained | Pool unhealthy or reroute budget too small for current failures | Investigate server health; consider rollback. |
| `pool_size` drops on a stable cluster | DNS refresh evicting endpoints | Confirm the headless service still resolves; check for pod restarts. |
| `pool_empty` with `pool_size > 0` | Snapshot-required routing excluded every pod | Inspect the `reason` label plus `load_subscriptions_total{outcome="reconnect"}` and Subscribe logs. |

### Logs to look for

`cymbal-resolution` server-side warnings to watch:

- `unhandled error during resolution` — per-item failure, surfaces as `ERROR_KIND_UNHANDLED`.
- `rejecting item with invalid payload` — malformed exception JSON or `metadata`; surfaces as `ERROR_KIND_INVALID_PAYLOAD`.
- `limiter closed mid-request, asking caller to retry` — symbol-resolution limiter was closed, currently expected only during shutdown/tests.
- `item deadline expired` — the item deadline elapsed before work completed; surfaces as `ERROR_KIND_OVERLOADED`.

Client-side warnings on the cymbal pods:

- `remote resolution dns refresh failed` — DNS refresh task swallowed an error and will retry next tick.
- `remote resolution transport-level retry` — caller-side transport retry classification, tagged with a bounded reason.
- `remote resolution returned item overload` — an overloaded result was escalated into a per-item reroute.
- `remote resolution outcome id did not match submitted item` — the mux ignored an outcome for another id.

Logs intentionally do not include raw routing keys as metric labels. Routing keys can contain symbol-set references, so cymbal uses bounded counters/histograms and endpoint labels only where the endpoint set is bounded by discovery.

## Code organization

- **Service (resolution mode, `cymbal/src/modes/resolution/`)**
  - [`mod.rs`](mod.rs) — `serve()`: gRPC + metrics servers, drain listener, layer stack (`GrpcMetricsLayer`, `GrpcLoadShedLayer`). Invoked from `cymbal`'s `main.rs` when `CYMBAL_MODE=resolution`.
  - [`config.rs`](config.rs) — resolution-mode `Config`, nested into `cymbal::config::Config`.
  - [`app_context.rs`](app_context.rs) — `ResolutionAppContext`: reuses cymbal's `build_symbol_resolver` to materialize a `SymbolResolver`, then dedicates a semaphore for symbol-resolution concurrency.
  - [`service.rs`](service.rs) and [`service/resolve.rs`](service/resolve.rs) — gRPC handlers and `ErrorKind` mapping.
- **Client (`cymbal/src/stages/resolution/remote/`)**
  - `config.rs` — `RemoteResolutionConfig`.
  - `dns.rs` — `DnsResolver` trait + tokio-backed default.
  - `pool.rs` — `EndpointPool`, DNS refresh, endpoint lifecycle, Subscribe freshness, and mux ownership.
  - `mux.rs` — per-endpoint bidirectional Resolve stream, waiter demux, local admission, and stream-break cleanup.
  - `subscription.rs` — long-lived per-endpoint Subscribe task.
  - `resolver.rs` — event partitioning, work-item construction, per-exception reroute, and response reassembly.
- **Proto contract** — [`proto/cymbal/resolution/v1/resolution.proto`](../../../../../proto/cymbal/resolution/v1/resolution.proto).

## Tests

- `cargo test -p cymbal-proto` — proto contract round-trips for `ResolveItem`, `ResolveOutcome`, `ErrorKind`, `Retry`, and `LoadEvent`.
- `cargo test -p cymbal` — resolution-mode service tests (`tests/resolution_service_tests.rs`: bidirectional streaming, accounting, overload, invalid payload, unhandled errors, Subscribe freshness/draining) plus client-side endpoint pool, mux, end-to-end Subscribe routing, and parity vs local mode.
