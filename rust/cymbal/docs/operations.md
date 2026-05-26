# Cymbal operations

This document covers local operation, deployment knobs, observability, and runbooks for Cymbal.
Architecture invariants live in [`architecture.md`](architecture.md); compatibility exceptions and removal criteria live in [`compatibility.md`](compatibility.md).

## Server modes

The `cymbal-server` binary can run the public ingestion service, the internal stage service, or both:

- `CYMBAL_MODE=pipeline` exposes `CymbalIngestion.ProcessExceptionBatch` only.
- `CYMBAL_MODE=stage` exposes `CymbalStageRuntime.ProcessStage` only.
- `CYMBAL_MODE=all` exposes both services for local development or compact deployments.

It also exposes an HTTP management endpoint for Prometheus and probes on
`METRICS_PORT` (default `8080`):

- `/_readiness` returns `200` while the pod is accepting new work and `503`
  once shutdown starts.
- `/_liveness` always returns `200`.
- `/metrics` exposes Prometheus metrics for pipeline and stage pods.

Stage pods choose local stages with `CYMBAL_STAGE_IDS`:

```text
CYMBAL_STAGE_IDS=resolution:v1
CYMBAL_STAGE_IDS=grouping:v1
CYMBAL_STAGE_IDS=linking:v1
CYMBAL_STAGE_IDS=alerting:v1
```

Pipeline pods route stages remotely with target and stage maps:

```text
CYMBAL_REMOTE_TARGETS=resolution=cymbal-resolution.default.svc.cluster.local:50051,grouping=cymbal-grouping.default.svc.cluster.local:50051,linking=cymbal-linking.default.svc.cluster.local:50051,alerting=cymbal-alerting.default.svc.cluster.local:50051
CYMBAL_REMOTE_STAGES=resolution:v1=resolution,grouping:v1=grouping,linking:v1=linking,alerting:v1=alerting
```

Remote connections use bounded connect, keepalive, per-stage timeouts, DNS endpoint refresh, and a per-target circuit breaker.
When a target repeatedly fails, Cymbal opens the circuit and immediately returns retryable per-item outcomes with jittered `retry_after_ms` instead of letting tonic workers queue behind a flapping stage.

## Routing policies

Remote stage endpoint selection is affinity-first by default for `resolution:v1` and `grouping:v1`.
Resolution prefers symbol-cache locality keys from `$debug_images`, sourcemap/chunk identifiers, or release/source references before falling back to `team_id`.
Grouping and linking use `team_id` when the typed stage input carries it.
The default linking and alerting policy is strict affinity because these stages can contain side effects.

Override policies with `CYMBAL_REMOTE_ROUTING_POLICIES`, formatted as comma-separated `stage_id=mode[:max_fallback_attempts]` entries.
Supported modes are `affinity-first`, `random`, and `strict-affinity`:

```text
CYMBAL_REMOTE_ROUTING_POLICIES=resolution:v1=affinity-first:2,linking:v1=strict-affinity,alerting:v1=random
```

`CYMBAL_REMOTE_ROUTING_ENABLED=false` is retained as an operational escape hatch while usage evidence is collected.
It disables affinity, fallback, and observed-load demotion while keeping explicit per-endpoint clients, returning remote-stage selection to one-shot random endpoint choice.
Prefer narrower `CYMBAL_REMOTE_ROUTING_POLICIES` entries such as `stage_id=random:0` when only one stage needs emergency load spreading.

Use `affinity-first` when a stage benefits from cache or state locality and can safely retry after explicit pre-work rejection.
Use `random` for stateless stages, emergency load spreading, or affinity debugging.
Use `strict-affinity` for side-effectful or locality-sensitive stages where duplicate work is worse than a retry.

## Capacity and backpressure knobs

- `CYMBAL_MAX_BATCH_EVENTS` defaults to 500 and caps public request size before stage work starts.
- `CYMBAL_MAX_STAGE_ITEMS` caps internal stage-batch size.
- `CYMBAL_MAX_IN_FLIGHT_BATCHES` defaults to 64; once the shared public/stage in-flight counter reaches that limit, Cymbal returns gRPC `resource_exhausted` immediately and emits `cymbal_in_flight_batches`.
- `CYMBAL_MAX_IN_FLIGHT_STAGE_ITEMS` caps stage-pod item/event admission; the default `0` derives a conservative budget of `CYMBAL_MAX_STAGE_ITEMS * CYMBAL_MAX_IN_FLIGHT_BATCHES`.
- `CYMBAL_STAGE_MAX_IN_FLIGHT_ITEMS=resolution:v1=2048,linking:v1=256` overrides item budgets for individual stage IDs.

Keep the public batch size aligned with downstream concurrency budgets.
Each accepted public batch can occupy one in-flight slot and then fan out into stage sub-batches, so large batches increase memory pressure and extend shutdown drain time.

Stage pods attach `StageLoad` on successful responses after releasing item permits and on pre-work `resource_exhausted` rejections through response metadata.
Pipeline pods record load per `(stage, target, endpoint)` with a short freshness window.
Fresh snapshots can demote overloaded affinity primaries; stale snapshots expire back to conservative capacity.

The symbol-resolution pool defaults to `MAX_PG_CONNECTIONS=16`, matching the default `SYMBOL_RESOLUTION_CONCURRENCY=64` ratio of at least one Postgres connection per four concurrent symbol-resolution tasks.
Cymbal emits a startup warning when the configured Postgres pool is below `symbol_resolution_concurrency / 4`.

Stage-level concurrency knobs cap in-flight work across the whole stage on a pod — concurrent stage batches share the same permit pool, so the configured number is the actual ceiling regardless of how many batches the pipeline fans out.
Per-item stages cap concurrent item work.
Alerting is a batch-fold stage: `ALERTING_STAGE_BATCH_SIZE` (default `500`) defines the ideal number of events per spike-detection fold, and `ALERTING_STAGE_CONCURRENCY` caps concurrent folds rather than individual items.
Defaults are intentionally moderate: `RESOLUTION_STAGE_CONCURRENCY=64`, `GROUPING_STAGE_CONCURRENCY=16`, `LINKING_STAGE_CONCURRENCY=8`, and `ALERTING_STAGE_CONCURRENCY=4`.

## Readiness and graceful drain

Use the HTTP management endpoint for readiness and drain.
`/_readiness` returns `200` while the pod is accepting new work and flips to `503` as soon as shutdown begins.
After flipping readiness, Cymbal waits `CYMBAL_SHUTDOWN_DRAIN_DELAY_MS`, then waits up to `CYMBAL_SHUTDOWN_MAX_WAIT_MS` (default 60s) for accepted public and stage batches to finish before letting tonic stop.

Stages are not cancel-safe: they can write repositories or trigger side effects mid-batch.
The readiness drain delay plus max wait should therefore exceed typical batch latency.
A draining pod should stop receiving new Kubernetes traffic before its last observed load reaches zero; stale saturated observations expire on the client, and endpoint refresh removes pods that leave DNS.
Do not use routing ejection as the primary shutdown mechanism.

## Observability

Cymbal logs JSON by default.
Set `CYMBAL_LOG_FORMAT=text` for local development and `CYMBAL_LOG_FORMAT=json` for production-style logs indexed by Loki/Grafana.
Scrape `http://<pod-ip>:${METRICS_PORT:-8080}/metrics` for `cymbal-server`
pipeline pods and stage pods such as a `resolution:v1` deployment.

Every stage invocation, local or remote, is wrapped by `metered_stage` and emits:

- `cymbal_stage_duration_seconds{stage, execution, outcome}` — histogram, `execution ∈ {local, remote}`, `outcome ∈ {ok, error, timeout, fail_open}`.
- `cymbal_stage_items_total{stage, execution, outcome}` — counter, `outcome ∈ {success, drop, retry, error}`.
- `cymbal_stage_batch_size{stage, execution}` — histogram of input items per stage call.

The public boundary emits `cymbal_pipeline_batch_duration_seconds` and `cymbal_pipeline_batch_events`, both labelled by `outcome`.
The shared backpressure counter emits `cymbal_in_flight_batches`.
The remote transport emits `cymbal_remote_stage_retries_total{stage, target, reason}` when it synthesizes per-item retry failures, plus `cymbal_remote_circuit_state{target}` and `cymbal_remote_circuit_opened_total{target, reason}` for circuit-breaker transitions.

Remote-stage routing emits:

- `cymbal_remote_stage_primary_endpoint_total{stage, target, endpoint}` — selected primary endpoint count.
- `cymbal_remote_stage_fallback_attempts_total{stage, target, endpoint, reason, code}` — fallback attempt count.
- `cymbal_remote_stage_fallback_items_total{stage, target, endpoint, reason, code}` — item count retried on fallback endpoints.
- `cymbal_remote_stage_fallback_success_total{stage, target, endpoint}` — successful fallback count.
- `cymbal_remote_stage_fallback_exhausted_total{stage, target, code, reason}` — candidate exhaustion count.
- `cymbal_remote_stage_fallback_exhausted_items_total{stage, target, code}` — item count without an available candidate.
- `cymbal_remote_stage_endpoint_load_observations_total{stage, target, endpoint, overloaded}` — load signals received from stage pods.
- `cymbal_remote_stage_endpoint_in_flight_batches{stage, target, endpoint, kind}` — last observed current/max stage batches.
- `cymbal_remote_stage_endpoint_in_flight_items{stage, target, endpoint, kind}` — last observed current/max items.
- `cymbal_remote_stage_load_skipped_primary_total{stage, target, endpoint}` — observed saturation demoted the stable affinity primary for one decision.
- `cymbal_stage_item_admission_rejections_total{stage, reason}` — stage pod rejected a request before work because capacity was exhausted.

Primary-hit rate should be high for resolution/grouping when pods are healthy.
Rising fallback attempts with `RESOURCE_EXHAUSTED`, high `overloaded=true` load observations, or repeated load-skipped-primary events indicate a hot pod, a too-small stage in-flight budget, or a poor affinity key.
Circuit-open metrics indicate transport failures/ejections rather than explicit load shedding.

Per-stage `cymbal stage finished` structured logs accompany the metrics.
Per-item retry/error warnings are sampled as `cymbal per-item failure (sampled)` at the rate defined in `crates/server/src/observability.rs`.

## Hot-pod and fallback runbook

To debug a hot pod or excessive fallback rate:

1. Compare `cymbal_remote_stage_primary_endpoint_total` distribution with endpoint load and circuit metrics.
2. If one endpoint has high primary hits plus `overloaded=true` load observations, inspect affinity-key cardinality and the pod's `cymbal_in_flight_batches`.
3. If fallback attempts rise without load observations, inspect `cymbal_remote_circuit_opened_total` and transport logs for ejection or connection problems.
4. If fallback exhaustion rises, either all candidates are rejecting work or the policy's `max_fallback_attempts` is too small for the target's replica count.

To debug stale load or underutilized capacity:

1. Compare `cymbal_remote_stage_endpoint_in_flight_items{kind="max"}` across endpoints with expected `CYMBAL_MAX_IN_FLIGHT_STAGE_ITEMS` and `CYMBAL_STAGE_MAX_IN_FLIGHT_ITEMS` values.
2. Treat zero or missing max values as conservative missing-capacity behavior until the next stage response or rejection emits load.
3. If primary distribution is balanced but throughput is low, check whether stale load, strict-affinity overflow, or `random:0` settings are preventing fallback.
4. If one pod stays hot while peers are idle, inspect the routing-key extractor for low-cardinality keys and verify DNS refresh returns all pod IPs for the target.

## Team rate limiting

The Rust Cymbal exception pipeline does not currently run its internal team-level limiter.
The old limiter code and environment knobs remain in the repo for possible future reuse, but they are not part of the active public stage chain.

Node ingestion still has its older pre-Cymbal `KeyedRateLimiterStep`, controlled by `ERROR_TRACKING_RATE_LIMITER_ENABLED`.
Treat that as a separate compatibility path.

## Shadow lane

`cymbal-legacy` (the pre-crate-split HTTP binary) can shadow a fraction of incoming
batches to `cymbal-server` for fingerprint parity testing.

| Variable                    | Default         | Description                                |
| --------------------------- | --------------- | ------------------------------------------ |
| `CYMBAL_SHADOW_GRPC_ADDR`   | `""` (disabled) | Host:port of `cymbal-server` gRPC endpoint |
| `CYMBAL_SHADOW_SAMPLE_RATE` | `0.0`           | Fraction of batches to shadow (0.0–1.0)    |

Shadow results never affect the HTTP response.
Each sampled compare records
`cymbal_shadow_compare_duration_seconds` and increments
`cymbal_shadow_compare_total{result=...}` with one of
`match`, `signature_mismatch`, `shadow_drop`, `shadow_retry`,
`shadow_error`, `shadow_missing`, `grpc_call_error`, or `grpc_stream_error`.
The signature is a hash of selected output properties such as issue ID,
including fingerprint and any other output properties, after canonicalizing
JSON object key order so dropped or altered properties affect the result.
Divergences are also logged at WARN with structured context for debugging.

To enable locally: set `CYMBAL_SHADOW_GRPC_ADDR=127.0.0.1:50150` and
`CYMBAL_SHADOW_SAMPLE_RATE=1.0` when starting `cymbal-legacy`, with `cymbal-pipeline`
running as the shadow target.

## Main-stack local smoke

Use the main PostHog dev stack when you need to prove Node error-tracking ingestion calls Cymbal over gRPC.
From the repository root:

```sh
hogli dev:setup # select the error_tracking intent, or include nodejs_error_tracking + error_symbolication
hogli start     # interactive; use hogli up -d && hogli wait for detached startup
```

The relevant main-stack processes are:

- `ingestion-errortracking` — Node error-tracking ingestion on `http://127.0.0.1:6742`, configured with `ERROR_TRACKING_CYMBAL_ADDR=127.0.0.1:50150`.
- `cymbal-pipeline` — public `CymbalIngestion.ProcessExceptionBatch` gRPC endpoint on `127.0.0.1:50150`.
- `cymbal-resolution-stage` — internal `CymbalStageRuntime.ProcessStage` endpoint on `127.0.0.1:50151`.

Quick health checks:

```sh
for file in /tmp/cymbal-resolution-ready /tmp/cymbal-pipeline-ready; do test -f "$file" && echo "ready $file"; done
for port in 50150 50151; do nc -vz 127.0.0.1 "$port"; done
curl -fsS http://127.0.0.1:6742/_ready
```

Run the Node smoke after the gRPC pipeline is healthy:

```sh
pnpm --filter=@posthog/nodejs run smoke:cymbal-main-stack
```

The smoke uses the same `CymbalClient` and `createCymbalProcessingStep` as Node error-tracking ingestion, sends representative `$exception` events to the local Cymbal pipeline, and fails unless processed properties include `$exception_fingerprint`, `$exception_fingerprint_record`, and `$exception_issue_id`.
By default it uses the first row in `posthog_team`; set `CYMBAL_SMOKE_TEAM_ID=<id>` to force a specific local team.
It bypasses Kafka and the final event-emission steps intentionally, so use it as the fast local check for the Node → Cymbal boundary.

There is no Rust Cymbal rate-limit smoke while the limiter is out of the active pipeline.

## Local Cymbal-only playground

Run the split-process shape used by remote stages without the full PostHog Node ingestion stack:

```sh
cd rust/cymbal
mprocs -c mprocs.yaml
```

This starts local Postgres, Redis, and object storage containers for Cymbal-only development, then starts:

- `pipeline` on `127.0.0.1:50150`
- `resolution-stage` on `127.0.0.1:50151`

Only resolution is remote in the local config; grouping, linking, and alerting run in-process in `pipeline`.
After the services are ready, start the `smoke-test` process in mprocs.
It runs `cargo run -p cymbal-server --example process_batch` and exercises baseline, variant, mixed-outcome, and oversized-batch requests through the mixed local/remote stage chain.

The Rust-only smoke is a lower-level Cymbal diagnostic; it does not prove the Node error-tracking ingestion path.
