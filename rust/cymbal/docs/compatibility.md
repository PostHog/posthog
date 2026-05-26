# Cymbal compatibility and cleanup inventory

This is the only living inventory for Cymbal compatibility surfaces and cleanup constraints.
Do not delete or rename a retained item until the evidence listed here exists and the owner has approved the removal.

## Evidence available

Repo-local inventory on 2026-05-24 checked:

- Clean working tree before the inventory started.
- Recent Cymbal commits `4cb45c1d7c1`, `be6b7393025`, `6da5596319d`, and `307e47535c7`.
- Current docs, crate map, architecture decisions, Rust crates, local Node client package, and Node error-tracking boundary references.
- Greps for stale cleanup terms across current docs, Rust crates, local Node client sources, and related Node error-tracking code.
- Repository config references for `CYMBAL_REMOTE_ROUTING_ENABLED`, `ERROR_TRACKING_CYMBAL_BASE_URL`, `ERROR_TRACKING_CYMBAL_ADDR`, `ERROR_TRACKING_RATE_LIMITER_ENABLED`, and `cymbal_legacy_js_frame_resolved`.
- Crate dependency graph, high-friction large files, tracked generated/static artifacts, and ignored local Node build outputs.

Runtime deployment config and production metrics were not available in the repo-local session, so operational usage is explicitly deferred where noted.

## Compatibility surfaces

| Surface | Class | Owner | Why it exists | Evidence | Removal or cleanup criteria |
| --- | --- | --- | --- | --- | --- |
| `CYMBAL_REMOTE_ROUTING_ENABLED=false` and `emergency_random_remote_routing_config()` | Operational escape hatch needing config evidence | Cymbal server/routing owners plus operators | Disables affinity, fallback, and observed-load demotion while keeping explicit endpoint clients; useful as an incident escape hatch. | Code default is `true`. Repo grep found no non-doc config setting it false in local dev, Docker, or mprocs files. Runtime/deployment config was not available. | Do not delete without deployment-config evidence that no environment sets it false. Prefer narrower `CYMBAL_REMOTE_ROUTING_POLICIES` overrides when only one stage needs emergency load spreading. |
| `ERROR_TRACKING_CYMBAL_BASE_URL` | Operational escape hatch with logged deprecation path | Node error-tracking ingestion owners | Deprecated compatibility input from the pre-gRPC Cymbal endpoint configuration; `ERROR_TRACKING_CYMBAL_ADDR` is the current gRPC address knob. | `resolveErrorTrackingCymbalEndpoint` in `nodejs/src/ingestion/error-tracking/config.ts` still accepts it and logs `error_tracking_cymbal_base_url_deprecated` when it falls back to it or `error_tracking_cymbal_base_url_ignored` when it is shadowed by `ERROR_TRACKING_CYMBAL_ADDR`. Repo greps still find no tracked deployment config setting it; runtime/deployment config remains unavailable in-repo. | Remove the field, the resolve helper's deprecation branch, and the related tests once (1) deployment-config inventory shows no environment sets it, and (2) the `error_tracking_cymbal_base_url_deprecated`/`_ignored` warnings have been absent across all environments over an agreed retention window. Until both conditions are met, keep the parsing and the warnings. |
| Node pre-Cymbal `KeyedRateLimiterStep` controlled by `ERROR_TRACKING_RATE_LIMITER_ENABLED` | Operational escape hatch needing config and product evidence | Node error-tracking ingestion owners | Applies a cheaper pre-Cymbal per-team limiter before symbolication; separate from Cymbal's internal team limiter and may still protect work or enforce product settings. | Defaults to disabled in code, but is wired through `error-tracking-server.ts`, `error-tracking-consumer.ts`, settings loading, tests, and `keyed_rate_limiter_outcomes_total`/app metrics. Runtime config and product-setting usage were not available. | Do not delete as Cymbal cleanup. Removal needs product approval plus evidence from config and limiter metrics that it is redundant for all deployments. |
| `StageBatchResult.load` being optional / `stage_batch_result_accepts_missing_optional_load` | External data/wire compatibility needing metrics/product approval | Cymbal API/server owners | Internal stage pods may omit `StageLoad`; pipeline clients must accept missing load and use conservative capacity behavior. | Protobuf field is optional and `crates/api/src/lib.rs` tests decoding `StageBatchResult { load: None }`. Architecture decisions describe backward-compatible observability fields. | Keep unless all supported stage-runtime clients and pods are guaranteed to emit `StageLoad` and API owners approve a breaking internal wire cleanup. Tests and comments should describe optional load fields. |
| `RawFrame::JavaScriptPlatformAlias` for `platform: "javascript"` and metric `cymbal_legacy_js_frame_resolved` | External data/wire compatibility needing metrics/product approval | Symbolication/resolution owners | Accepts SDK/event payloads that still send JavaScript frames with the bare JavaScript platform alias instead of `web:javascript` or `node:javascript`. | Variant is active in `crates/symbolication/src/raw_frame.rs`, resolution still handles it, and usage is counted with `cymbal_legacy_js_frame_resolved`. Production metric data was not available. | Keep until the metric is zero over an agreed retention window and product/SDK owners approve removal while preserving serialized values and metric continuity. |
| `Frame.frame_id` serializes as `raw_id` | External data/wire compatibility needing product approval | Domain/symbolication owners | Public serialized frame shape and downstream fingerprinting/snapshots expect the `raw_id` JSON field even though the Rust field is now a full `FrameId`. | `crates/domain/src/frame.rs`, symbolication tests, fingerprinting code, and server snapshots all read or assert `raw_id`. | Keep unless ClickHouse/frontend/snapshot consumers migrate. Tests and comments should describe the public serialized field name. |
| Apple symbol-store raw ZIP fallback | External data compatibility needing retention-window evidence | Symbol-store owners | Keeps reading existing raw ZIP uploads while newer source-manifest behavior is supported. | `crates/symbol-store/src/apple.rs` has backward-compatibility comments and dated cleanup TODOs. | Remove only after old uploads have expired or storage inventory proves none remain. |
| Generated protobuf and TypeScript bindings | External wire contract / generated artifact | Cymbal API and Node client owners | Rust tonic types are generated from protobuf at build time; local Node bindings under `node/src/generated` are generated from `pipeline.proto`. | `node/src/generated/cymbal/v1/pipeline_pb.ts` is tracked and generated; ignored `node/dist/` contains build output. | Do not hand-edit generated bindings. Regenerate with `pnpm --dir node run generate` after protobuf changes. |
| `#[allow(...)]` and cleanup TODO/FIXME matches | Internal cleanup debt, not a compatibility contract by itself | Owning crate maintainers | Existing lint suppressions and TODOs mostly mark dead-code, parser/provider constraints, deprecated `Envconfig::init`, or refactor opportunities. | Grep found `allow(deprecated)` in rate limiting, `allow(dead_code)` in symbol-store/provider helpers, and `allow(clippy::too_many_arguments)` in server observability/remote runner. | The lint cleanup should remove or justify each allowance near the code. TODOs should be left unless that cleanup already edits the owning area. |
| `cymbal-legacy` binary + `CYMBAL_SHADOW_GRPC_ADDR` / `CYMBAL_SHADOW_SAMPLE_RATE` | Temporary shadow lane | Cymbal owners | Runs the pre-crate-split HTTP pipeline alongside `cymbal-server` for fingerprint parity testing. Shadow rate defaults to 0.0 (disabled). | Restored from `origin/master` at `rust/cymbal/src/`. New deps: `cymbal-api` (gRPC client only), `tonic`, `rand`. | Remove `rust/cymbal/src/`, `rust/cymbal/Cargo.toml`, the workspace member, and shadow config once Node has been switched to `ERROR_TRACKING_CYMBAL_ADDR` (gRPC) and `cymbal_shadow_fingerprint_match{result="mismatch"}` has been at zero over an agreed retention window. |

Historical migration records that are fully represented by git history are not retained as living docs.
Current behavior belongs in `README.md`, `docs/architecture.md`, `docs/operations.md`, this inventory, the crate map, and final architecture decisions.

The internal `crates/server/src/remote/routing.rs` re-export shim has been removed; use `cymbal_core::routing` directly.

## Operational checks deferred

The following checks require deployment config or metrics access that was not available in the repo-local session:

- Whether any deployment still sets `CYMBAL_REMOTE_ROUTING_ENABLED=false`.
  Needed evidence: deployment environment inventory for all Cymbal pipeline pods plus any emergency runbook references.
- Whether any deployment still sets `ERROR_TRACKING_CYMBAL_BASE_URL` instead of `ERROR_TRACKING_CYMBAL_ADDR`.
  Needed evidence: deployment environment inventory for Node error-tracking ingestion, plus an observed-absence window for the `error_tracking_cymbal_base_url_deprecated` and `error_tracking_cymbal_base_url_ignored` log messages emitted at boot by `resolveErrorTrackingCymbalEndpoint`.
- Recent rate for `cymbal_legacy_js_frame_resolved`.
  Needed evidence: metric query over the agreed retention window, split by environment if possible.
- Whether the Node pre-Cymbal keyed rate limiter is still used or product-required.
  Needed evidence: `ERROR_TRACKING_RATE_LIMITER_ENABLED` deployment inventory, `keyed_rate_limiter_outcomes_total` or app-metrics usage, and product confirmation that Cymbal's limiter fully replaces the behavior.

Because those checks are deferred, later cleanup should avoid destructive removals for those surfaces.

## Crate dependency graph

Derived from `cargo metadata --manifest-path ../Cargo.toml --format-version 1 --no-deps`.

```text
cymbal-alerting -> cymbal-core, cymbal-domain, cymbal-repositories
cymbal-api -> (none)
cymbal-core -> (none)
cymbal-domain -> cymbal-core
cymbal-fingerprinting -> cymbal-domain, cymbal-rules
cymbal-grouping -> cymbal-core, cymbal-domain, cymbal-fingerprinting, cymbal-resolution, cymbal-rules
cymbal-linking -> cymbal-core, cymbal-domain, cymbal-grouping, cymbal-repositories, cymbal-rules
cymbal-pipeline -> cymbal-alerting, cymbal-core, cymbal-domain, cymbal-grouping, cymbal-linking, cymbal-rate-limiting, cymbal-resolution
cymbal-rate-limiting -> cymbal-core, cymbal-domain
cymbal-repositories -> cymbal-rules, cymbal-symbol-store
cymbal-resolution -> cymbal-core, cymbal-domain, cymbal-symbol-store, cymbal-symbolication
cymbal-rules -> cymbal-domain
cymbal-runtime -> cymbal-alerting, cymbal-core, cymbal-grouping, cymbal-linking, cymbal-rate-limiting, cymbal-repositories, cymbal-resolution, cymbal-rules, cymbal-symbol-store, cymbal-symbolication
cymbal-server -> cymbal-alerting, cymbal-api, cymbal-core, cymbal-domain, cymbal-grouping, cymbal-linking, cymbal-pipeline, cymbal-rate-limiting, cymbal-resolution, cymbal-runtime
cymbal-symbol-store -> (none)
cymbal-symbolication -> cymbal-domain, cymbal-symbol-store
```

## High-friction files for module-split cleanup

Largest source files by line count, excluding generated Node bindings:

```text
1820 crates/server/src/remote_runner.rs
1641 crates/server/src/remote.rs
1581 crates/server/src/pipeline.rs
1321 crates/stages/linking/src/lib.rs
1284 crates/server/tests/grpc_integration.rs
1200 crates/pipeline/src/lib.rs
1114 crates/core/src/routing.rs
1006 crates/stages/alerting/src/lib.rs
 976 crates/symbolication/src/apple.rs
 956 crates/runtime/src/lib.rs
 908 crates/symbol-store/src/saving.rs
 891 crates/server/src/observability.rs
 884 crates/symbol-store/src/sourcemap.rs
 626 crates/stages/rate-limiting/src/lib.rs
 591 crates/server/src/stage.rs
```

Largest tracked files by bytes include source-map and Proguard static fixtures that should not be touched during cleanup-only module splits:

```text
9016797 tests/static/sourcemaps/1234.js.map
9016797 tests/static/chunk-PGUQKT6S.js.map
9016797 crates/symbol-store/tests/static/chunk-PGUQKT6S.js.map
3815640 tests/static/proguard/mapping_example.txt
3815640 crates/symbol-store/tests/static/proguard/mapping_example.txt
2334332 tests/static/chunk-PGUQKT6S.js
2334327 tests/static/sourcemaps/1234.js
2334327 crates/symbol-store/tests/static/chunk-PGUQKT6S.js
2333991 tests/static/chunk-PGUQKT6S-no-map.js
2333991 crates/symbol-store/tests/static/chunk-PGUQKT6S-no-map.js
```

## Generated and ignored artifacts

- `.sqlx/query-*.json` files are tracked SQLx metadata.
- `node/src/generated/cymbal/v1/pipeline_pb.ts` is tracked generated TypeScript and should only change through `pnpm --dir node run generate`.
- `crates/api` keeps protobuf sources under `proto/`; Rust service/types are produced by `tonic::include_proto!` at build time.
- Ignored local Node artifacts currently present: `node/dist/*` and `node/node_modules/*`.

## Review notes for remaining cleanup terms

- `legacy` is acceptable only in this inventory or retained metric names.
- `compatibility` wording should map to one of the retained surfaces above or to a stable wire/data contract.
- `allow(...)` occurrences must carry a nearby why-comment that explains the suppression. Add new ones only when the lint is wrong for the call site (for example endemic `tonic::Status` size or a serialization wire-shape constraint), and prefer refactoring or `#[cfg(test)]` over silencing.
- Current docs should describe the supported gRPC APIs and not point readers toward removed service shapes or deleted planning files.

## Local lint exception guidance

When considering a new `#[allow(...)]` under `crates/`:

- Prefer deleting the dead code, moving it behind `#[cfg(test)]` / a feature, or refactoring (typed context structs for `clippy::too_many_arguments`, narrowing the `Result` type for `clippy::result_large_err`, etc.).
- If the suppression is unavoidable, add a one- to three-line comment immediately above the attribute that says what the lint is and why the code intentionally violates it. Bare `#[allow(...)]` without a justification is treated as cleanup debt.
- Compatibility-driven naming (for example `JavaScriptPlatformAlias`, `raw_id`) is reserved for externally required behavior listed in the table above. Do not introduce new `legacy`/`compat` wording for internal refactors — rename internal concepts to describe current behavior instead.
