# Cymbal architecture

This document records stable Cymbal architecture invariants.
Operational knobs and runbooks live in [`operations.md`](operations.md); crate-level edit guidance lives in [`../crates/README.md`](../crates/README.md); retained compatibility exceptions live in [`compatibility.md`](compatibility.md).

## Boundaries

Cymbal is gRPC-only at its service boundaries.
The public Node-facing API is `CymbalIngestion.ProcessExceptionBatch`, defined in [`../crates/api/proto/cymbal/v1/pipeline.proto`](../crates/api/proto/cymbal/v1/pipeline.proto).
Public callers send exception events and processing options, then receive one final outcome per input event.
They do not choose stages or pass stage identifiers.

Remote stage execution uses the internal `CymbalStageRuntime.ProcessStage` service from [`../crates/api/proto/cymbal/v1/stage.proto`](../crates/api/proto/cymbal/v1/stage.proto).
Only Cymbal pipeline and stage deployments use this API.
A `StageBatch` carries the stage identifier, input/output payload type IDs, and opaque item payload bytes so public ingestion contracts stay independent from internal stage composition.

The `rust/cymbal/` directory contains documentation, local tooling, SQLx metadata, shared fixtures, and the local Node client package.
All Rust packages live under `rust/cymbal/crates/` and are workspace members of the parent `rust/Cargo.toml` manifest.

## Stage flow

The public pipeline processes exception events through these logical stages:

```text
public batch
  -> team rate-limiting gate when enabled
  -> resolution
  -> grouping
  -> linking
  -> alerting unless skipped
  -> final event outcomes
```

Rate limiting is an internal pre-resolution gate keyed by numeric `team_id`.
Resolution and grouping are item-progress stages that can safely make independent progress.
Linking and alerting can perform side effects, so the pipeline treats them conservatively and preserves deterministic final ordering at the public boundary.

Each final result is one of:

- `next` — processing succeeded and returns enriched event properties plus metadata.
- `drop` — the event should be permanently discarded.
- `retry` — the event should be retried later.
- `error` — processing failed with a code and retryability hint.

## Crate responsibilities

- `cymbal-api` owns protobuf definitions and generated Rust gRPC types for public ingestion and internal stage-runtime APIs.
- `cymbal-core` owns transport-neutral framework primitives: batch context, stage payload type IDs, codecs, stage traits, generic executor/progress/emission helpers, linear pipeline spec/runner APIs, generic circuit and rate-limit/admission primitives, and routing/capacity/fallback primitives.
- `cymbal-domain` owns shared error-tracking domain types, sanitizers, exception input events, rate-limit gate payloads, and final event outcomes.
- `cymbal-symbol-store` owns symbol artifact storage, caching, loading, and provider-specific parsing.
- `cymbal-symbolication` owns language-specific raw-frame resolution.
- `cymbal-rules` owns HogVM-backed grouping, suppression, and assignment rule evaluation.
- `cymbal-fingerprinting` owns automatic fingerprint generation and manual fingerprint normalization.
- `cymbal-resolution` resolves exception properties and raw frames.
- `cymbal-grouping` applies grouping rules and fingerprinting.
- `cymbal-linking` links grouped events to issues, suppression state, and assignment rules.
- `cymbal-alerting` performs spike-detection alerting side effects and returns event outcomes unchanged.
- `cymbal-repositories` owns Postgres, Redis, and PostHog side-effect boundaries.
- `cymbal-runtime` builds repository, symbol-store, symbolication, and stage dependencies from config.
- `cymbal-pipeline` composes the pure Rust stage graph and preserves final result ordering.
- `cymbal-server` owns gRPC transport, config parsing, stage registry, local/remote dispatch, DNS-backed balancing, metrics, readiness, and shutdown.

Use [`../crates/README.md`](../crates/README.md) for the detailed crate map and validation commands.

## Dependency direction

Keep transport, DNS, tonic status mapping, metrics, readiness, shutdown, and environment parsing out of `cymbal-core` and `cymbal-pipeline`.
Those concerns belong in `cymbal-server`.

Keep business rules and side effects in stage, repository, and runtime crates:

- Stage crates orchestrate stage-specific domain behavior behind traits.
- Repository/runtime crates construct and own concrete Postgres, Redis, object storage, and PostHog clients.
- `cymbal-pipeline` wires stage executors together but does not know gRPC or deployment topology.
- `cymbal-server` adapts local and remote execution into the pipeline executor interfaces.

## Remote routing and capacity model

Remote stage routing is event/item-level while the transport remains sub-batch based.
For each stage invocation, the pipeline extracts a stage-specific routing key per item, orders concrete endpoint candidates with the configured policy, reserves observed item capacity locally for the current dispatch, and sends one `ProcessStage` request per selected endpoint sub-batch.

Capacity is expressed in concurrent events/items as well as batches.
A stage pod admits a sub-batch only when it can reserve all item permits before work starts; otherwise it rejects before work with `RESOURCE_EXHAUSTED` and attaches load metadata when possible.
Pipeline pods record load per `(stage, target, endpoint)` and use fresh observations to avoid saturated affinity primaries.
Stale or missing load falls back to conservative client-side capacity and stage-side admission remains the source of truth.

Fallback is safe only when the first candidate did not do work or could not be called, such as a pre-call circuit-open decision or pre-work admission rejection.
Timeouts and generic transport errors are ambiguous because linking, alerting, or limiter work may already have produced side effects.
Side-effectful stages therefore use strict affinity by default unless their contract is explicitly changed.

See the architecture decisions for more detail:

- [`architecture-decisions/cymbal-remote-stage-transport.md`](architecture-decisions/cymbal-remote-stage-transport.md)
- [`architecture-decisions/cymbal-remote-stage-routing.md`](architecture-decisions/cymbal-remote-stage-routing.md)
- [`architecture-decisions/cymbal-event-level-capacity-routing.md`](architecture-decisions/cymbal-event-level-capacity-routing.md)

## Generated bindings

Rust service/types are generated from protobuf sources at build time through `cymbal-api`.
The tracked TypeScript client bindings under `node/src/generated/` are generated from `pipeline.proto` with `pnpm --dir node run generate`.
Do not edit generated bindings manually.

## Domain glossary

- **Issue**: A group of errors that ideally represents one bug.
- **Error**: An event capable of producing an error fingerprint, letting it be grouped into an issue.
- **Fingerprint**: A stable identifier for a class of errors; multiple fingerprints can point to one issue when symbol availability or fingerprinting heuristics change.
- **Stack trace**: A list of frames, raw or resolved, with the most recent call last.
- **Stack context**: The language, operating system, runtime, dev tools, and related data that identify a raw-frame type.
- **Raw frame**: A context-specific, unprocessed frame.
- **Frame**: Cymbal's unified stack-frame representation.
- **Symbol**: The human-readable function name Cymbal tries to resolve from a raw frame.
- **Resolving**: Transforming a raw frame into a frame; symbolication is the most important resolving step.
- **Symbol set**: Context-specific bytes that map raw-frame addresses or locations to symbols.
- **Symbol set reference**: The stable reference that maps a raw frame to the symbol set needed to resolve it.
- **Symbol set store**: A fetch/cache/load boundary that returns symbol-set bytes for a symbol set reference.
