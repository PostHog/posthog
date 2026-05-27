# cymbal-resolution

gRPC service that owns exception-level symbol resolution for PostHog error
tracking. Speaks `cymbal.resolution.v1`. Used by the [`cymbal`](../cymbal)
ingestion binary when remote resolution is enabled.

## Architecture

```text
                   ┌─────────────────────────────────────────────┐
event ──HTTP──────▶│ cymbal                                      │
                   │   /process pipeline                         │
                   │   ┌───────────────────────────────────────┐ │
                   │   │ ResolutionStage                       │ │
                   │   │   remote: Some(ctx) ─┐                │ │
                   │   └────────────────────┬─┘                │ │
                   │                        │                  │ │
                   │   ┌────────────────────┴────────────────┐ │ │
                   │   │ EndpointPool                        │ │ │
                   │   │  - DNS-discovered endpoints         │ │ │
                   │   │  - per-endpoint load snapshot       │ │ │
                   │   │  - selects on lowest reported load  │ │ │
                   │   └─┬───────────────────────────────┬──┘ │ │
                   └─────┼───────────────────────────────┼────┘
                         │ Resolve                      │ Subscribe
                         │ (per ResolveRequest →        │ (long-lived
                         │  one ExceptionResolutionItem │  stream of
                         │  per exception, stream of    │  LoadEvent
                         │  ItemOutcome × N + Summary)  │  ticks)
                         ▼                              ▼
                   ┌─────────────────────────────────────────────┐
                   │ cymbal-resolution                           │
                   │   Resolve handler                           │
                   │   - ItemOutcome × N (one per item)          │
                   │   - BatchSummary (terminal)                 │
                   │                                             │
                   │   Subscribe handler                         │
                   │   - LoadEvent × ∞ (periodic ticks)          │
                   └─────────────────────────────────────────────┘
```

The contract is intentionally split across **two server-streaming RPCs**:

- **`Resolve`** carries work only — one item outcome per submitted exception
  plus a terminal `BatchSummary`. Load and health information have moved
  off this stream entirely, so a busy server stays observable independently
  of resolution traffic.
- **`Subscribe`** is the load event bus. The cymbal-side `EndpointPool`
  opens one long-lived `Subscribe` stream per pod; the server pushes a
  `LoadEvent` (`in_flight`, `max_in_flight`, `degraded`, `draining`,
  `sequence`) on a periodic tick. Each event refreshes a per-endpoint
  snapshot the pool consults during `select()`. Snapshots are considered
  fresh for two tick periods (twice
  `CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_TICK_HINT_MS`). **Snapshot-required
  routing**: a pod with no fresh snapshot is excluded from selection
  outright — the pool does not fall back to caller-side load guesses.
  When the load bus is starved across the whole pool, callers see
  `pool_empty` and retry with backoff until a fresh `LoadEvent` arrives.

- `cymbal` remains the HTTP ingress and the full pipeline owner
  (fingerprinting, suppression, Kafka producers, issue linking).
- `cymbal-resolution` owns symbol resolution only — Apple, Java/Kotlin, Dart,
  and JavaScript stack-frame symbolication using the existing cymbal symbol
  store catalog and resolver.
- Wire-level contract is exception-level: each `ResolveRequest` carries one
  `ExceptionResolutionItem` per exception. The cymbal client may group
  exceptions from multiple HTTP events into the same `ResolveRequest` when
  they share a routing key, and the server emits one `ItemOutcome` per
  submitted item plus a terminal `BatchSummary` for accounting. The proto lives at
  [`proto/cymbal/resolution/v1/resolution.proto`](../../proto/cymbal/resolution/v1/resolution.proto).

## Rollout model

Remote resolution is opt-in on the cymbal side. There is intentionally **no
silent local fallback** for events sampled into the remote path: when the
pool cannot satisfy a sampled remote request, cymbal surfaces an
`UnhandledError` for that event so the failure is visible rather than masked.
Events not selected by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` are not remote
attempts; they run through the inline local exception/frame resolvers.

| Mode    | Cymbal env vars                       | Resolution path                              |
| ------- | ------------------------------------- | -------------------------------------------- |
| Local   | `CYMBAL_REMOTE_RESOLUTION_ENABLED=false` (default) | Inline local resolver inside `cymbal`        |
| Sampled remote | `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`, sampled by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` | gRPC to `cymbal-resolution` pool, no fallback |
| Unsampled local | `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`, not sampled by `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE` | Inline local resolver inside `cymbal` |

### Enabling remote mode (rollout)

1. Deploy `cymbal-resolution` pods behind a headless Kubernetes service so
   each pod is reachable by IP. `cymbal` resolves the service hostname via
   DNS and opens one channel per returned address (see `EndpointPool`).
2. Confirm the pods are serving:
   - `/_liveness` returns `ok`
   - `/_readiness` returns `ok`
   - `cymbal_remote_resolution_pool_size` becomes non-zero on cymbal pods
     once they are pointed at the service.
3. Set on `cymbal` pods:
   - `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`
   - `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE=<0.0..=1.0>` (defaults to `0.0`
     so enabling alone routes no traffic; ramp this explicitly)
   - `CYMBAL_REMOTE_RESOLUTION_HOST=<service-hostname>` (e.g. the headless
     service DNS name)
   - `CYMBAL_REMOTE_RESOLUTION_PORT=50061` (default)
   - optionally tune `CYMBAL_REMOTE_RESOLUTION_MAX_BATCH_ITEMS` if dashboards
     show requests are too small (per-team groups not amortizing RPC overhead)
     or risk hitting tonic's 4 MiB default message ceiling. Chunking is
     event-atomic: a single event with many exceptions ships as one chunk.
4. Roll cymbal pods. The startup path eagerly resolves DNS and fails loudly
   if the host is empty or no addresses come back, so a misconfiguration is
   caught at boot rather than at first request.

### Server-driven batch sizing

`LoadEvent.suggested_max_batch_items` lets the server tell callers how many
items it wants per `Resolve` request right now. The server emits its own
item-admission cap (`MAX_ITEM_CONCURRENCY`) by default; it can lower the
suggestion under pressure to ask callers to shrink batches without a config
redeploy. The client takes the minimum across pods with fresh snapshots and
caps it at `CYMBAL_REMOTE_RESOLUTION_MAX_BATCH_ITEMS` (its own ceiling); a
suggestion of `0` means "no opinion — use the client config".

### Routing affinity and spillover

Routing is per-team. The caller's `EndpointPool` rendezvous-hashes
`team:{team_id}` against the pod set so every exception from a given team
prefers a single pod, maximizing warm-cache locality without coupling the
caller to symbol-set internals.

Spillover before saturation is driven by the server's own load signal:
once `in_flight / max_in_flight` on the item-admission semaphore crosses
`DEGRADED_LOAD_RATIO` (default `0.8`), the next `LoadEvent` flips
`degraded = true`. The pool already excludes degraded endpoints in
`select_for_key`, so callers route to the next rendezvous-ranked pod
before any request hits the `MAX_CONCURRENT_REQUESTS` admission queue and
load-sheds with `UNAVAILABLE`.

To tune: lower `DEGRADED_LOAD_RATIO` to spill earlier (more
load-spreading, less locality), raise it to spill later (more locality,
risk of late `UNAVAILABLE` retries).

### Disabling / rolling back

Set `CYMBAL_REMOTE_RESOLUTION_ENABLED=false` on the cymbal pods and roll.
That is the only knob required to fully revert to local resolution — no
data-plane state needs to be flushed and the `cymbal-resolution` pods can
keep running without harm. Because there is no fallback, this is also the
correct response to sustained `cymbal-resolution` outage.

For a partial rollback, lower `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE`. The
decision is deterministic by `(team_id, event_uuid)`, so the same event keeps
the same local/remote decision across retries, pods, and process restarts.

### Compatibility with the Node error-tracking consumer

The Node consumer still talks only to cymbal's HTTP `POST /process` endpoint.
Cymbal preserves the response array shape and input ordering after internal
remote resolution, so Node-side request chunking by HTTP body size remains
valid and no generated type changes are needed. The private gRPC grouping and
chunking limits protect the cymbal-to-`cymbal-resolution` hop after a HTTP
chunk has already arrived. See [`cymbal/docs/compatibility.md`](../cymbal/docs/compatibility.md).

## Configuration

### Cymbal client (`cymbal` binary)

All variables are prefixed `CYMBAL_REMOTE_RESOLUTION_` and live on
`cymbal::config::Config`.

| Env var                                       | Default | Purpose                                                                                  |
| --------------------------------------------- | ------- | ---------------------------------------------------------------------------------------- |
| `CYMBAL_REMOTE_RESOLUTION_ENABLED`            | `false` | Master switch. `true` routes exception resolution through the remote pool.               |
| `CYMBAL_REMOTE_RESOLUTION_HOST`               | _empty_ | Service hostname resolved via DNS. Required when enabled; empty value fails boot.        |
| `CYMBAL_REMOTE_RESOLUTION_PORT`               | `50061` | gRPC port the pods listen on. Must match the server-side `GRPC_ADDRESS` port.            |
| `CYMBAL_REMOTE_RESOLUTION_DNS_REFRESH_SECS`   | `30`    | How often DNS is re-resolved and the pool reconciled.                                    |
| `CYMBAL_REMOTE_RESOLUTION_DEADLINE_MS`        | `15000` | Per-call deadline. Caller cancels in-flight RPCs that exceed this.                       |
| `CYMBAL_REMOTE_RESOLUTION_CONNECT_TIMEOUT_MS` | `1000`  | Per-endpoint TCP/HTTP2 connect timeout.                                                  |
| `CYMBAL_REMOTE_RESOLUTION_MAX_RETRIES`        | `2`     | Caller-side retries against another pool endpoint on transport/load-shed/Retry outcomes. |
| `CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE`        | `0.0`   | Deterministic event-level remote rollout rate. `0.0` (default) keeps all events local even when `_ENABLED=true`; ramp up explicitly. `1.0` samples all eligible events remotely. |
| `CYMBAL_REMOTE_RESOLUTION_MAX_BATCH_ITEMS`    | `64`    | Client-side ceiling on exception items per private gRPC `ResolveRequest`. Effective batch size is `min(this, server's suggested_max_batch_items)`, so the server can shrink batches dynamically via `LoadEvent`. Chunking is event-atomic — a single event with more exceptions than the effective cap ships as one oversized chunk. |
| `CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_TICK_HINT_MS` | `1000` | Cadence hint sent on `SubscribeRequest`. The server clamps to its own bounds. Snapshots are considered fresh for two ticks (twice this value); pods without a fresh snapshot are excluded from routing (no caller-side fallback). |
| `CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_RECONNECT_BACKOFF_MS` | `500` | Backoff between subscription reconnect attempts when a stream terminates. |

### Cymbal-resolution server (`cymbal-resolution` binary)

| Env var                        | Default          | Purpose                                                                                                       |
| ------------------------------ | ---------------- | ------------------------------------------------------------------------------------------------------------- |
| `GRPC_ADDRESS`                 | `0.0.0.0:50061`  | Bind address for the gRPC server.                                                                             |
| `METRICS_PORT`                 | `9101`           | HTTP port for `/_liveness`, `/_readiness`, and `/metrics`.                                                    |
| `MAX_CONCURRENT_REQUESTS`      | `256`            | Hard cap on in-flight gRPC requests. Excess returns `UNAVAILABLE` (fast load shed). `0` disables the cap.     |
| `SYMBOL_RESOLUTION_CONCURRENCY`| `64`             | Cap on concurrent symbol-resolution operations across all in-flight requests (shared `Semaphore`).            |
| `MAX_ITEM_CONCURRENCY`         | `64`             | Process-wide cap on concurrent item (exception) processing across all in-flight `Resolve` RPCs. Replaces the per-request `REQUEST_ITEM_CONCURRENCY`. Drives the `LoadEvent.in_flight` / `max_in_flight` signal the caller pool routes against. |
| `DEGRADED_LOAD_RATIO`          | `0.8`            | Self-marks `LoadEvent.degraded = true` once `in_flight / max_in_flight` crosses this ratio so callers spill over to another pod before the admission queue load-sheds with `UNAVAILABLE`. |
| `SERVICE_INSTANCE_ID`          | random UUID      | Identifier surfaced to callers via `LoadEvent` on the Subscribe stream. Useful when correlating logs across pods. |
| `SUBSCRIBE_TICK_INTERVAL_MS`   | `1000`           | Default cadence for `LoadEvent` ticks when callers don't suggest one. Server has the final say on cadence.    |
| `SUBSCRIBE_MIN_TICK_MS`        | `100`            | Lower bound for the Subscribe tick cadence — hints below this are clamped up.                                 |
| `SUBSCRIBE_MAX_TICK_MS`        | `10000`          | Upper bound for the Subscribe tick cadence — hints above this are clamped down.                               |

In addition, the server inherits the **narrow** subset of cymbal's env-var
surface needed by `build_symbol_resolver` — Postgres (`DATABASE_URL`,
`MAX_PG_CONNECTIONS`), object storage (`OBJECT_STORAGE_*`,
`AWS_*`), the symbol-store cache and resolver tuning (`SYMBOL_STORE_CACHE_MAX_BYTES`,
`FRAME_CACHE_TTL_SECONDS`, `FRAME_RESULT_TTL_MINUTES`, `SS_PREFIX`,
`CONTEXT_LINE_COUNT`), and outbound HTTP (`ALLOW_INTERNAL_IPS`). It does
**not** connect to Kafka, Redis, or the signals API — those belong to
cymbal's fingerprinting/issue path and are skipped here. See
[`cymbal/src/config.rs`](../cymbal/src/config.rs) for full definitions.

## Operator guidance

### Health and discovery endpoints

| Surface                  | Where                                                        | Notes                                                                  |
| ------------------------ | ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Liveness                 | `GET :{METRICS_PORT}/_liveness`                              | Static `ok`. Use to detect crashed pods.                               |
| Readiness                | `GET :{METRICS_PORT}/_readiness`                             | Static `ok` today; safe to flip to a real probe in a later batch.      |
| Prometheus metrics       | `GET :{METRICS_PORT}/metrics`                                | Includes `cymbal_remote_resolution_*` and generic `grpc_server_*`.     |
| gRPC                     | `:{GRPC_ADDRESS}` `cymbal.resolution.v1.CymbalResolution`    | Headless service DNS name → one channel per pod.                       |

### Reading the metrics

These metric names are exported by the cymbal _client_ unless noted (the
server is the `cymbal-resolution` binary and exports `grpc_server_*` plus
the same `cymbal_remote_resolution_pool_size`/`endpoint_in_flight` series
through cymbal pods that talk to it). Their definitions live in
[`cymbal/src/metric_consts.rs`](../cymbal/src/metric_consts.rs).

The metric surface is intentionally minimal — anything previously emitted
that was derivable from the metrics below has been dropped to keep
per-pod active-series counts predictable.

- **Sample-rate rollout decisions** — cymbal is deciding local vs remote
  before any gRPC request exists:
  - Client: `cymbal_remote_resolution_sampling_total{decision="remote"|"local"}`.
    `decision="local"` is expected during a partial rollout and is not a
    server-side fallback.
- **Request-level RED** — every `Resolve` RPC outcome:
  - Client: `cymbal_remote_resolution_requests_total{outcome, reason?}`
    with outcomes `ok / pool_empty / retryable_item / missing_items /
    transport_retry / terminal / exhausted / items_failed / no_summary`.
    `reason` is the gRPC code tag for transport classes.
  - Client: `cymbal_remote_resolution_latency_ms` per-RPC duration.
  - Client: `cymbal_remote_resolution_attempts_per_request{outcome}`
    histogram — right tail surfaces retry storms.
- **Service saturation** — cymbal-resolution is at capacity:
  - Server: `grpc_server_load_shed_total{method="Resolve"}` — fast
    `UNAVAILABLE` from `GrpcLoadShedLayer` once `MAX_CONCURRENT_REQUESTS`
    is exceeded.
  - Server: `cymbal_remote_resolution_server_request_duration_ms{outcome}`
    distinguishes slow successful requests from cancellation outcomes
    inside the service.
  - Client correlate: `requests_total{outcome="transport_retry",
    reason="unavailable" | "resource_exhausted"}`.
- **Endpoint discovery / pool health**:
  - Client: `cymbal_remote_resolution_pool_size` — gauge of healthy
    endpoint count. Persistently zero means DNS is failing or all pods
    are unhealthy. Client correlate is `requests_total{outcome="pool_empty"}`.
  - Client: `cymbal_remote_resolution_endpoint_in_flight{endpoint}` —
    per-pod in-flight gauge; useful for spotting load imbalance.
- **Load event bus health**:
  - Client: `cymbal_remote_resolution_load_subscriptions_total{outcome="connected"|"reconnect"}`
    — Subscribe stream lifecycle. A consistently high `reconnect` rate
    means pods are dropping subscriptions (rolling restarts, server panics).
    Under snapshot-required routing, sustained reconnects translate
    directly into `pool_empty` because pods without fresh snapshots are
    excluded from selection.

### Failure interpretation cheat sheet

| Symptom                                                                  | Likely cause                                          | Suggested response                                                                 |
| ------------------------------------------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `pool_empty` spikes at cymbal startup                                    | Misconfigured `CYMBAL_REMOTE_RESOLUTION_HOST` or DNS  | Fix host; cymbal will fail boot when host is empty.                                |
| `sampling_total{decision="local"}` rises while remote errors stay flat   | Expected partial rollout or lower sample rate         | No action unless the configured sample rate is wrong.                              |
| `transport_retry{reason="unavailable"}` + `grpc_server_load_shed_total`  | Server is at `MAX_CONCURRENT_REQUESTS`                | Scale up server pods, or raise `MAX_CONCURRENT_REQUESTS` after capacity-checking.  |
| `transport_retry{reason="deadline_exceeded"}` with low load              | Caller-side deadline shorter than worst-case resolution | Raise `CYMBAL_REMOTE_RESOLUTION_DEADLINE_MS` (server has no separate deadline knob). |
| `requests_total{outcome="no_summary"}` non-zero                          | Server stream ended without terminal `BatchSummary`   | Check server logs for panics; client retries to a different pod automatically.      |
| `requests_total{outcome="items_failed"}` non-zero                        | Server returned `ItemOutcome.Error` for one or more items | All-or-nothing policy fails the batch; investigate the surfaced item error code.    |
| `requests_total{outcome="exhausted"}` non-zero, sustained                | Pool unhealthy and exceeding `MAX_RETRIES`            | Investigate server health; consider rollback (`CYMBAL_REMOTE_RESOLUTION_ENABLED=false`). |
| `pool_size` drops on a stable cluster                                    | DNS refresh evicting endpoints                        | Confirm headless service still resolves; check for pod restarts.                   |
| `pool_empty` non-zero with `pool_size > 0`                               | Snapshot-required routing excluded every pod (no fresh `LoadEvent`) | Inspect `load_subscriptions_total{outcome="reconnect"}` — the Subscribe stream is starved for at least one endpoint. |

### Logs to look for

`cymbal-resolution` server-side warnings to watch:

- `unhandled error during resolution` — per-item failure, surfaces to caller
  as `ItemOutcome.Error { code = "unhandled" }`.
- `rejecting item with invalid payload` — caller sent malformed JSON; usually
  indicates a wire-version skew. Pairs with `code = "invalid_payload"`.
- `limiter closed mid-request, asking caller to retry` — only emitted when
  the symbol-resolution semaphore is closed, which today only happens in
  tests; in production, sustained pressure shows up as deadline-driven
  cancellations instead.
- `item limiter closed, asking caller to retry` — same shape but for the
  process-wide item-admission semaphore (`MAX_ITEM_CONCURRENCY`). Only
  occurs at shutdown today; per-item Retry outcomes flow back to the caller.

Client-side warnings on the cymbal pods:

- `remote resolution dns refresh failed` — DNS refresh task swallowed an
  error and will retry next tick. Persistent failures should trip the
  symptoms above.
- `remote resolution transport-level retry` / `... per-item Retry outcomes`
  — caller-side retry classification, tagged with the reason.
- `remote resolution missing outcome` — server omitted an item; the caller
  keeps the unresolved exception in place and continues.

Logs intentionally do not include raw routing keys as metric labels. Routing
keys can contain symbol-set references, so cymbal uses bounded histograms for
group counts, chunk counts, and request item counts, and hashes the routing
key into the private `ResolveRequest.batch_id` for low-cardinality navigation.

## Code organization

- **Service (`cymbal-resolution`)**
  - [`src/main.rs`](src/main.rs) — process bootstrap, gRPC + metrics
    servers, layer stack (`GrpcMetricsLayer`, `GrpcLoadShedLayer`).
  - [`src/config.rs`](src/config.rs) — server `Config` (env-driven).
  - [`src/app_context.rs`](src/app_context.rs) — constructs an `AppContext`
    by reusing cymbal's `AppContext::from_config` to materialise a
    `SymbolResolver`, then dedicates a `Semaphore` for this service's
    symbol-resolution concurrency.
  - [`src/service.rs`](src/service.rs) — `CymbalResolutionService` gRPC
    handler. Error/Retry taxonomy lives in [`service::codes`](src/service.rs).
- **Client (`cymbal/src/stages/resolution/remote/`)**
  - `config.rs` — `RemoteResolutionConfig` (narrowed view of cymbal's full config).
  - `dns.rs` — `DnsResolver` trait + tokio-backed default.
  - `pool.rs` — `EndpointPool`, refresh task, RAII handle for in-flight
    accounting, load-aware `select()` that prefers the lowest reported
    load ratio (with caller-side in-flight as the fallback).
  - `client.rs` — single-attempt gRPC call with deadline (Resolve RPC).
  - `subscription.rs` — long-lived per-endpoint Subscribe stream task. Owns
    the `LoadSnapshot` write side; the pool owns the read side.
  - `resolver.rs` — batch-aware remote orchestration called by
    `ResolutionStage::process`; it samples events, groups exception work by
    routing key, chunks each group by item/byte limits, and reconciles streamed
    outcomes back into the original HTTP event order.
- **Proto contract** — [`proto/cymbal/resolution/v1/resolution.proto`](../../proto/cymbal/resolution/v1/resolution.proto).

## Tests

- `cargo test -p cymbal-resolution` — service-level streaming, accounting,
  overload behavior, and Subscribe (load event bus) coverage
  (`tests/service_tests.rs`).
- `cargo test -p cymbal` — client-side endpoint pool (load-aware routing
  via injected snapshots), integration tests against an in-process tonic
  stub (`tests/remote_resolution.rs`, `tests/remote_resolution_hardening.rs`),
  end-to-end Subscribe routing against a real server
  (`tests/remote_resolution_subscribe.rs`), and parity vs local mode
  (`tests/remote_resolution_parity.rs`). The parity and subscribe tests
  bring the cymbal-resolution crate in as a dev-dependency only;
  production cymbal does not depend on the service crate.
