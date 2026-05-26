# Cymbal

Cymbal is PostHog's error-tracking processing service.
Node ingestion sends `$exception` batches to Cymbal over gRPC; Cymbal runs resolution, grouping, linking, and alerting stages, then streams one final outcome per input event.

Cymbal is a crate workspace area, not a standalone Rust package: run Rust commands through the parent `rust/Cargo.toml` manifest.
There is no endpoint named `/process`, and public ingestion requests do not expose stage IDs, stage chains, or stage artifacts.

## API shape

The public API lives in [`crates/api/proto/cymbal/v1/pipeline.proto`](crates/api/proto/cymbal/v1/pipeline.proto):

```text
CymbalIngestion.ProcessExceptionBatch(ProcessExceptionBatchRequest)
    -> stream ProcessExceptionBatchResult
```

A public request contains batch context, exception events, and processing options.
Each event carries JSON properties as `properties_json` bytes so JSON semantics stay intact at the wire boundary.
The response stream emits one `next`, `drop`, `retry`, or `error` outcome per event.

The internal remote-stage API lives in [`crates/api/proto/cymbal/v1/stage.proto`](crates/api/proto/cymbal/v1/stage.proto):

```text
CymbalStageRuntime.ProcessStage(StageBatch) -> StageBatchResult
```

`ProcessStage` is only for Cymbal pipeline and stage deployments.
It carries typed stage envelopes, opaque payload bytes, item results, item errors, and optional stage-load observations.

## Living docs

- [`docs/architecture.md`](docs/architecture.md) — stable architecture invariants, API boundaries, stage flow, and domain glossary.
- [`crates/README.md`](crates/README.md) — the main “where do I edit?” crate map for agents and humans.
- [`docs/operations.md`](docs/operations.md) — server modes, local smoke tests, routing knobs, metrics, readiness, and runbooks.
- [`docs/testing.md`](docs/testing.md) — Cymbal-local test selection, coverage commands, and baseline notes.
- [`docs/compatibility.md`](docs/compatibility.md) — the only living inventory of retained compatibility surfaces and cleanup criteria.
- [`docs/reusable-pipeline-framework.md`](docs/reusable-pipeline-framework.md) — how to reuse Cymbal's routing/capacity primitives in another pipeline.
- [`docs/architecture-decisions/`](docs/architecture-decisions/) — final architecture decisions.

## Binaries

| Binary          | Purpose                                     | Entry                       |
| --------------- | ------------------------------------------- | --------------------------- |
| `cymbal-server` | New gRPC pipeline (production target)       | `rust/cymbal/crates/server` |
| `cymbal-legacy` | Old HTTP pipeline for shadow parity testing | `rust/cymbal/src/`          |

During the shadow phase both binaries run; Node talks HTTP to `cymbal-legacy` on port
3302, which optionally shadows to `cymbal-server` on port 50150.

## Common local commands

Run these from `rust/cymbal/` unless noted.

```sh
# Workspace discovery and formatting
cargo metadata --manifest-path ../Cargo.toml --format-version 1 --no-deps
cargo fmt --check --manifest-path ../Cargo.toml --all

# Local Cymbal-only playground: Postgres, Redis, object storage, pipeline, and resolution stage
mprocs -c mprocs.yaml

# Contract snapshots for the public ingestion API
cargo test --manifest-path ../Cargo.toml -p cymbal-server --test pipeline_snapshots

# Lower-level mixed local/remote smoke once mprocs services are ready
CYMBAL_PIPELINE_ENDPOINT=http://127.0.0.1:50150 cargo run --manifest-path ../Cargo.toml -p cymbal-server --example process_batch
```

From the repository root, use the main PostHog stack when you need to prove Node error-tracking ingestion calls Cymbal over gRPC:

```sh
hogli dev:setup # select the error_tracking intent, or include nodejs_error_tracking + error_symbolication
hogli start     # or hogli up -d && hogli wait
pnpm --filter=@posthog/nodejs run smoke:cymbal-main-stack
```

## Validation checklist

Use this package set for broad Cymbal Rust validation:

```sh
cargo test --manifest-path ../Cargo.toml \
  -p cymbal-api \
  -p cymbal-core \
  -p cymbal-domain \
  -p cymbal-fingerprinting \
  -p cymbal-pipeline \
  -p cymbal-repositories \
  -p cymbal-runtime \
  -p cymbal-rules \
  -p cymbal-alerting \
  -p cymbal-grouping \
  -p cymbal-linking \
  -p cymbal-rate-limiting \
  -p cymbal-resolution \
  -p cymbal-symbol-store \
  -p cymbal-symbolication \
  -p cymbal-server \
  --no-fail-fast

git diff --check
```

If protobufs change, regenerate the local Node client instead of editing generated bindings by hand:

```sh
pnpm --dir node run generate
pnpm --dir node typecheck
```
