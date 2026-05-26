# Plan: opinionated generic pipeline framework in `cymbal-core`

## Product/design goal

Turn `cymbal-core` from a collection of reusable primitives into a small, opinionated **linear pipeline framework** that can serve Cymbal's exception pipeline and future non-exception pipelines without importing exception-domain contracts.

The framework should standardize the mechanics that every such pipeline needs:

- typed stage identity and remote payload type IDs
- linear stage-chain contracts and validation
- batch-oriented stage execution
- continue-vs-terminal per-item outputs
- item-progress vs barrier stage semantics
- stable input/completion-order terminal emission
- routing/capacity/fallback primitives for remote execution
- circuit-breaker state machines and admission/limiter contracts
- generic rate-limiting gate mechanics (while product crates own keys, reasons, and backend wiring)

Product/domain crates should still own their payloads, business stages, side effects, transport adaptation, and public API semantics.

The target developer experience is: a future product can define its payload types and stage list, then use `cymbal-core` for the framework scaffolding instead of re-inventing stage contract validation, progress semantics, ordered emission, and routing primitives.

## Non-goals

- Do not move Cymbal's exception DTOs (`InputEvent`, `EventResult`, `EventOutcome`, `RateLimitGateOutput`, etc.) back into `cymbal-core`.
- Do not make `cymbal-core` depend on `cymbal-domain`, stage crates, server, repositories, runtime, or pipeline crates.
- Do not build an arbitrary DAG/workflow engine. The framework should be explicitly linear and batch-oriented.
- Do not put gRPC/protobuf, DNS/client pools, tonic status mapping, metrics, readiness, environment parsing, or deployment topology in `cymbal-core`. Circuit-breaker **state and decisions** can move to core; transport-specific observation and metrics emission stay in server/adapters.
- Do not require dynamic schemas or `serde_json` payload routing inside core. Payload identity stays `StageType`; serialization stays at transport edges.
- Do not make `cymbal-core` own Cymbal's team-id limiter policy, Redis config, metric names, or drop reasons. Core should own generic limiter interfaces/results; product crates own keys and policy mapping.
- Do not rewrite the exception pipeline in one large PR. Migrate through compatibility-preserving layers with tests at each step.

## Current-state observations from the repo

Inspected from `rust/cymbal/`:

- `TASKS.md` Batches 1-6 completed the first boundary refactor. `cymbal-core` now has no dependency on `cymbal-domain`; exception contracts live in `crates/domain/src/event.rs` and are re-exported from `cymbal_domain`.
- `crates/core/src/lib.rs` owns framework primitives: `StageType`, `StagePayload`, `StageCodec`, `StageInput`, `BatchContext`, `Metadata`, `PipelineStage`, `PerItemStage`, and `StageError`.
- `crates/core/src/executor.rs` owns `StageExecutor`, `LocalExecutor`, `ContinueExecutor`, and generic `IntermediateStageOutput<T, Terminal>`.
- `crates/core/src/progress.rs` owns `StageProgressMode` and `PipelineEventState<T, StageId>`.
- `crates/core/src/emission.rs` owns `Sink<T>`, `EmissionOrder`, and `OrderedEmitter<T, S, F>`.
- `crates/core/src/routing/` owns routing keys, policies, capacity snapshots, local reservation partitioning, and fallback decision primitives.
- `crates/server/src/remote/circuit.rs` currently owns a useful generic-ish circuit breaker (`RemoteTargetCircuit`) but it is server-private and coupled to metrics/tracing labels. Its state machine is a strong candidate for `cymbal-core`; metric emission and endpoint bookkeeping should remain in server.
- `crates/stages/rate-limiting` currently owns Cymbal's team rate-limiting gate, Redis-backed `limiters` wiring, config parsing, metrics labels, and domain decisions. The generic parts are the limiter evaluation contract, disabled/reporting/enforcing modes, fail-open behavior, and allowed-vs-terminal gate shape; the exception-specific parts are `team_id`, Redis key format, drop reasons, metrics names, and `RateLimitGateOutput` DTOs.
- `crates/pipeline` still owns the concrete exception pipeline shape and orchestration: `PipelineStages`, `PipelineExecutors`, `ExceptionPipelineStage`, `CymbalStageProgress`, `process_exception_pipeline`, and `process_exception_pipeline_streaming`.
- `crates/server/src/registry.rs` contains a small but domain-specific stage registry: stage contracts, local/remote placement, retry flags, default stage IDs, and validation of first input, adjacent links, special rate-limit fan-out, and final terminal type.
- `docs/reusable-pipeline-framework.md` already describes core as reusable framework primitives and domain as exception-contract home, but it stops short of a first-class pipeline specification API.
- `docs/architecture.md` and `docs/compatibility.md` still contain some stale historical wording from before the refactor (for example architecture says `cymbal-core` owns input events/per-item outcomes, and compatibility's crate dependency graph says `cymbal-core -> cymbal-domain`). These should be corrected as part of the cleanup/migration phases, not used as current truth.
- There is no `ROAST.md` or `SUGGESTIONS.md` in `rust/cymbal/`, so there is no external critique file to incorporate.
- This `PLAN.md` previously described a coverage plan. That direction is superseded by the current user goal: an opinionated generic pipeline framework plan.

## Proposed architecture

### 1. Keep `cymbal-core` opinionated but domain-agnostic

Add a new core module, likely `crates/core/src/pipeline.rs`, for generic **linear pipeline contracts**. It should not know about exception events, alerting, symbolication, Postgres, gRPC, or remote target names.

Suggested core types:

```rust
pub type StageId = String;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StageSpec {
    pub stage_id: StageId,
    pub stage_type: StageType,
    pub input_type: StageType,
    pub output_type: StageType,
    pub progress: StageProgressMode,
    pub effects: StageEffectMode,
    pub transient_failure_policy: TransientFailurePolicy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StageEffectMode {
    Pure,
    IdempotentSideEffects,
    OrderedSideEffects,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransientFailurePolicy {
    RetryableBeforeWork,
    RetryableIfStageDeclaresSafe,
    NotRetryableAfterDispatch,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LinearPipelineSpec {
    pub input_type: StageType,
    pub terminal_type: StageType,
    pub stages: Vec<StageSpec>,
    pub allowed_links: Vec<StageLinkRule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageLinkRule {
    ExactType,
    FanOutContinue {
        stage_output_type: StageType,
        next_input_type: StageType,
        terminal_type: StageType,
    },
}
```

Design notes:

- `StageSpec` describes a stage contract and execution semantics, not deployment. Local-vs-remote placement and remote target names should remain in `cymbal-server`.
- `StageEffectMode` is deliberately coarse. It is not a formal proof system; it gives routing/fallback/orchestration code a shared vocabulary for barriers and safe retries.
- `StageLinkRule::FanOutContinue` generalizes Cymbal's rate-limit gate: a stage may output a wrapper type that contains either continue items for the next stage or terminal results. The product pipeline owns the wrapper's Rust shape; core only validates the type-level contract.
- `LinearPipelineSpec::validate()` should check: non-empty stages, first input type, adjacent exact or allowed links, final terminal type, duplicate stage IDs, and stable stage ordering.
- Keep all errors typed in core, e.g. `PipelineSpecError::{Empty, DuplicateStage, InvalidFirstStage, InvalidLink, InvalidFinalStage, UnknownStage}`.

### 2. Promote circuit breakers into the framework

Circuit breakers are not Cymbal-exception-specific. They are a core pipeline reliability primitive: a runner or transport adapter needs to know whether an endpoint/stage target should be attempted, skipped, half-open probed, or failed fast with retry guidance.

Move the generic state machine out of `crates/server/src/remote/circuit.rs` into a new core module, likely `crates/core/src/circuit.rs` or `crates/core/src/resilience/circuit.rs`.

Suggested core types:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitState {
    Closed,
    Open,
    HalfOpen,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CircuitBreakerConfig {
    pub window_size: usize,
    pub min_requests: usize,
    pub failure_ratio_to_open: f64,
    pub open_duration: Duration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CircuitDecision {
    Allow,
    Reject { retry_after: Duration },
    ProbeHalfOpen,
}

pub struct CircuitBreaker<Clock = SystemClock> { /* state + rolling outcomes */ }
```

Core should own deterministic transitions and retry-after calculation hooks. Server should own:

- endpoint keying `(target, endpoint)`
- load map storage
- tonic status conversion
- metrics (`cymbal_remote_circuit_state`, `cymbal_remote_circuit_opened_total`)
- tracing/log labels
- pruning stale endpoint circuits

The existing jitter helper can become generic and deterministic in core if it accepts a stable item/endpoint key and reason. Metrics should be emitted by observers/adapters, not inside the core state machine.

### 3. Promote generic rate-limiting mechanics into the framework

Rate limiting is also a framework concern, but only at the level of admission semantics. The framework can standardize the decision model and gate behavior while product crates provide keys, storage backends, and terminal-result mapping.

Core should own generic concepts such as:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitMode {
    Disabled,
    Reporting,
    Enforcing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RateLimitDecision<K> {
    Disabled,
    MissingKey,
    Allowed { key: K },
    Limited { key: K, reason: String },
    LimiterError { message: String },
}

pub trait RateLimitKeyExtractor<T> {
    type Key;
    fn key(&self, item: &T) -> Option<Self::Key>;
}

#[async_trait::async_trait]
pub trait RateLimiter<K>: Send + Sync {
    async fn check(&self, key: &K, cost: u64) -> RateLimitDecision<K>;
}

pub enum GateDecision<T, Terminal> {
    Continue { item: T },
    Terminal { terminal: Terminal },
}
```

The exact naming can change, but the boundary should not: core standardizes mode/decision/fail-open/reporting/enforcing behavior; product crates map decisions into product DTOs and metrics.

For Cymbal specifically:

- `cymbal-rate-limiting` keeps `RateLimitingConfig`, Redis/global-limiter construction, `team_id` extraction, Redis key format, metrics labels, and conversion into `cymbal_domain::RateLimitGateOutput`.
- `cymbal-domain` can keep the exception-facing `RateLimitDecision` and `RateLimitMode` aliases initially, or migrate them to thin re-exports/wrappers around core types in a compatibility-preserving phase.
- `RateLimitGateOutput::from_team_id_decision` can eventually delegate to a core `apply_rate_limit_mode` helper, but the drop reason remains domain-owned.

Do not force the first extraction to remove all current domain rate-limit enums. A staged migration avoids churn in server codecs and wire compatibility tests.

### 4. Treat execution as a second layer, not part of the first extraction

A fully generic heterogeneous typed runner is where Rust abstractions can become over-engineered. The first product-ready step should standardize **contracts and validation** before attempting to move the concrete exception orchestrator.

After `LinearPipelineSpec` is proven through Cymbal's existing registry, introduce a minimal generic execution layer only if it removes duplication without erasing type safety.

The safest runner design is a homogeneous product-owned item enum:

```rust
pub trait PipelineItem: Send + 'static {
    fn item_id(&self) -> &str;
    fn payload_type(&self) -> StageType;
}

pub trait TerminalItem: Send + 'static {
    fn item_id(&self) -> &str;
}

pub struct StageBatchOutcome<Item, Terminal> {
    pub continue_items: Vec<Item>,
    pub terminal_items: Vec<Terminal>,
}

#[async_trait::async_trait]
pub trait StageDriver<Item, Terminal>: Send + Sync {
    async fn run_stage(
        &self,
        context: Arc<BatchContext>,
        stage: &StageSpec,
        items: Vec<Item>,
    ) -> Result<StageBatchOutcome<Item, Terminal>, StageError>;
}
```

For Cymbal, the product enum would be something like:

```rust
enum ExceptionPipelineItem {
    Input(InputEvent),
    Resolved(ResolvedEvent),
    Grouped(GroupedEvent),
    Alerting(AlertingEvent),
}
```

The generic runner can then own ordered terminal emission, item-progress chunking, barrier behavior, and spec-driven stage sequencing while product code owns typed conversions and stage dispatch.

This shape is intentionally more opinionated than a generic DAG and less type-level-complex than variadic tuples of heterogeneous stages.

### 5. Keep product crates responsible for domain contracts and adapters

- `cymbal-domain` owns exception payload contracts and retained `cymbal.core.*` wire labels.
- `cymbal-pipeline` owns exception-specific item enum/adapters, rate-limit split semantics, linking-to-alerting conversion, default stage list, and any public exception-pipeline aliases.
- `cymbal-server` owns gRPC, `StageRegistry` deployment placement, remote target resolution, capacity observations, status/metadata conversion, and process config.
- Stage crates own business behavior and side-effect contracts.

A future non-exception pipeline should be able to depend on `cymbal-core`, define its own domain crate or product crate, and implement a `StageDriver` without importing Cymbal's exception crates.

## Proposed code organization

### `crates/core/src/pipeline.rs` (new)

Own generic linear pipeline contracts:

- `StageId`
- `StageSpec`
- `StageEffectMode`
- `TransientFailurePolicy`
- `StageLinkRule`
- `LinearPipelineSpec`
- `PipelineSpecError`
- tests for validation behavior

### `crates/core/src/circuit.rs` or `crates/core/src/resilience/circuit.rs` (new)

Own generic circuit-breaker mechanics:

- `CircuitBreakerConfig`
- `CircuitState`
- `CircuitDecision`
- `CircuitBreaker` state transitions
- injectable/testable clock or elapsed-time API
- deterministic retry-after/jitter helper that does not emit metrics directly

### `crates/core/src/rate_limit.rs` or `crates/core/src/admission/rate_limit.rs` (new)

Own generic rate-limiting/admission semantics:

- `RateLimitMode`
- generic `RateLimitDecision<K>`
- `RateLimitKeyExtractor<T>`
- generic `RateLimiter<K>` trait, if it does not conflict with the existing `limiters` crate
- `apply_rate_limit_mode` helper that turns mode + decision into continue vs limited behavior without knowing product terminal DTOs

Potential later additions after the spec is adopted:

- `PipelineItem`
- `TerminalItem`
- `StageBatchOutcome<Item, Terminal>`
- `StageDriver<Item, Terminal>`
- `LinearPipelineRunner<Item, Terminal, Driver, Sink, IdFn>`

### `crates/server/src/registry.rs`

Keep Cymbal-specific known stage construction and deployment placement, but delegate generic validation to `cymbal_core::pipeline::LinearPipelineSpec`.

Likely split:

- `StageRegistry` still maps stage IDs to Cymbal's known `StageContract` plus local/remote placement.
- `StageContract` either embeds `StageSpec` or converts into it.
- `StageRegistry::validate_pipeline()` builds a `LinearPipelineSpec` with Cymbal's exception input/terminal types and the rate-limit fan-out link rule, then calls core validation.
- `StageExecution::{Local, Remote}` remains server-only.

### `crates/server/src/remote/circuit.rs`

After core circuit primitives exist, shrink this module to server-specific storage/adaptation:

- key circuits by endpoint/target
- call core `CircuitBreaker` for decisions and state transitions
- emit existing metrics and tracing
- preserve existing retry/fallback behavior and tests

### `crates/stages/rate-limiting`

After core rate-limit primitives exist, keep this crate as the Cymbal team limiter adapter:

- parse Cymbal env config
- construct Redis/global limiter backends
- extract `team_id` and build stable Redis keys
- map generic decisions to `RateLimitGateOutput` and Cymbal metrics
- preserve wire payload strings and drop reasons

### `crates/pipeline`

Keep public exception pipeline functions stable at first:

- `ExceptionPipeline`
- `process_exception_pipeline`
- `process_exception_pipeline_streaming`
- `PipelineExecutors`
- `PipelineStages`
- `CymbalStageProgress`

Incrementally add adapters only after core spec validation is proven:

- `ExceptionPipelineItem` enum if moving toward generic runner.
- `ExceptionStageDriver` that wraps existing typed `PipelineExecutors`.
- Small adapter functions from existing typed outputs into `StageBatchOutcome<ExceptionPipelineItem, EventResult>`.

### Documentation

- Update `docs/reusable-pipeline-framework.md` once the spec types exist to show the standardized API, not just routing primitives.
- Update `crates/README.md` to route "linear pipeline contract validation" work to `cymbal-core` and "exception pipeline adapters" work to `cymbal-pipeline`.
- Update `docs/architecture.md` stale crate responsibilities so it no longer says `cymbal-core` owns input events/per-item outcomes.
- Update `docs/compatibility.md` stale dependency graph after any implementation PR touches those docs.

## Implementation strategy and milestones

### Phase 0: Foundation cleanup and naming alignment

Goal: remove documentation ambiguity before introducing new framework API.

1. Update stale docs discovered during planning:
   - `docs/architecture.md`: `cymbal-core` owns framework primitives, not input events/per-item outcomes.
   - `docs/compatibility.md`: dependency graph should show `cymbal-core -> (none of cymbal-domain)` and `cymbal-domain -> cymbal-core`.
2. Grep for stale ownership wording:
   - `cymbal-core.*InputEvent`
   - `cymbal-core.*EventResult`
   - `core.*ExceptionProperties`
   - `cymbal-core -> cymbal-domain`
3. Do not rename public Rust traits yet. `PipelineStage` can remain as the generic stage trait even though it says "pipeline".

Validation:

- `cargo fmt --check --manifest-path ../Cargo.toml --all`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-core -p cymbal-domain -p cymbal-server`
- targeted grep review

### Phase 1: Add generic linear pipeline contract types to core

Goal: make pipeline contract validation a first-class framework concept without changing Cymbal behavior.

1. Add `crates/core/src/pipeline.rs` with `StageSpec`, `LinearPipelineSpec`, `StageLinkRule`, and `PipelineSpecError`.
2. Re-export the new types from `crates/core/src/lib.rs`.
3. Add focused `cymbal-core` tests:
   - empty pipeline is rejected
   - duplicate stage IDs are rejected
   - first input type mismatch is rejected
   - exact adjacent stage type links pass
   - fan-out/continue link rule passes only for the configured stage output and next input type
   - final terminal type mismatch is rejected
   - error messages identify stage IDs and expected/actual type strings
4. Keep the API simple and owned data-based (`String`, `Vec`) before optimizing lifetimes.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core`
- `cargo clippy --manifest-path ../Cargo.toml --all-targets -p cymbal-core -- -D warnings`

### Phase 2: Adopt `LinearPipelineSpec` in Cymbal's server registry

Goal: prove the generic spec is useful by replacing Cymbal-specific validation logic with core validation while preserving public behavior.

1. Convert `crates/server/src/registry.rs` `StageContract` into or alongside `cymbal_core::pipeline::StageSpec`.
2. Keep `StageExecution` and remote target names in server.
3. Express Cymbal's special rate-limiting gate as `StageLinkRule::FanOutContinue`:
   - stage output type: `RateLimitGateOutput::TYPE`
   - next input type: `InputEvent::TYPE`
   - terminal type: `EventResult::TYPE`
4. Keep all existing registry tests and add one assertion that `StageRegistry` delegates to/specifies the generic link rule.
5. Ensure error text/status behavior remains stable enough for server tests; if error variants change, update only internal tests, not public protobuf behavior.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core -p cymbal-server registry:: -- --nocapture`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test pipeline_snapshots -- --nocapture`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test grpc_integration -- --nocapture`

### Phase 3: Move circuit-breaker mechanics into core

Goal: make endpoint/stage circuit decisions a framework primitive while preserving server behavior.

1. Add the generic circuit module to `cymbal-core` with deterministic unit tests for Closed → Open → HalfOpen → Closed/Open transitions.
2. Remove metrics/tracing from the core state machine; return state/transition information to callers instead.
3. Refactor `crates/server/src/remote/circuit.rs` and `RemoteStageConnectionManager` to wrap the core circuit.
4. Preserve existing metric names, retry-after behavior, fallback classification, and remote connection tests.
5. Add one server test that verifies an open circuit still maps to a pre-work fallback candidate before synthesizing retry outcomes.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server remote::connection:: -- --nocapture`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server remote_runner:: -- --nocapture`
- `cargo clippy --manifest-path ../Cargo.toml --all-targets -p cymbal-core -p cymbal-server -- -D warnings`

### Phase 4: Move generic rate-limit/admission semantics into core

Goal: standardize rate-limit decisions and mode application without moving Cymbal's team limiter policy or wire DTOs into core.

1. Add generic rate-limit/admission types to `cymbal-core`.
2. Add focused core tests for disabled, reporting, enforcing, missing-key, limited, and limiter-error/fail-open behavior.
3. Refactor `cymbal-rate-limiting` so decision evaluation uses the core decision/mode helper internally, while continuing to emit `cymbal_domain::RateLimitGateOutput`.
4. Keep or temporarily alias `cymbal_domain::{RateLimitMode, RateLimitDecision}` until server codecs and public compatibility tests can be migrated cleanly.
5. Preserve `RateLimitGateOutput::TYPE == cymbal.core.RateLimitGateOutput@2`, drop reasons, metrics labels, and Redis key format.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core -p cymbal-domain -p cymbal-rate-limiting -p cymbal-pipeline`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test grpc_integration -- --nocapture`
- `cargo clippy --manifest-path ../Cargo.toml --all-targets -p cymbal-core -p cymbal-domain -p cymbal-rate-limiting -p cymbal-server -- -D warnings`

### Phase 5: Standardize pipeline item identity and terminal emission API

Goal: reduce closure/ad-hoc ID plumbing without requiring a full runner yet.

1. Add optional core traits:
   - `PipelineItemId` or `IdentifiedItem` with `fn item_id(&self) -> &str`.
   - `TerminalItem` with `fn terminal_id(&self) -> &str`, or one generic `Identified` trait reused for both.
2. Add `OrderedEmitter::for_identified(...)` convenience constructor while preserving the existing closure-based constructor for flexibility.
3. Implement the trait for `cymbal-domain::EventResult` in `cymbal-domain` (allowed because the trait is in core and the type is in domain).
4. Consider implementing it for stage-owned intermediate payloads (`ResolvedEvent`, `GroupedEvent`, `AlertingEvent`) if useful.
5. Avoid a blanket trait impl that conflicts with downstream product crates.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core -p cymbal-domain -p cymbal-pipeline`
- Pipeline streaming tests must still cover input-order and completion-order behavior.

### Phase 6: Add a generic runner only after the spec/adapters settle

Goal: move orchestration mechanics into core without forcing a brittle heterogeneous type-level design.

Default direction: use a product-owned homogeneous item enum plus a generic `StageDriver<Item, Terminal>`.

1. Add core traits/types behind normal APIs, not feature flags:
   - `PipelineItem`
   - `TerminalItem`
   - `StageBatchOutcome<Item, Terminal>`
   - `StageDriver<Item, Terminal>`
   - `LinearPipelineRunnerOptions`
   - `LinearPipelineRunner`
2. Runner behavior should be opinionated:
   - stages execute in `LinearPipelineSpec` order
   - each stage receives a batch of current items
   - terminal items bypass remaining stages
   - `StageProgressMode::BatchBarrier` runs the whole current batch before downstream progress
   - `StageProgressMode::ItemProgress` may chunk and run concurrently
   - terminal emission uses `OrderedEmitter`
   - side-effect/failure policies affect retry/fallback decisions but not transport directly
3. Start with local/in-process driver tests in `cymbal-core` using a toy item enum. Do not migrate Cymbal yet.
4. Only migrate `cymbal-pipeline` streaming after the toy tests prove the API is understandable.
5. Keep the existing typed `process_exception_pipeline` as a compatibility wrapper until the generic runner fully matches behavior.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-pipeline`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test grpc_integration -- --nocapture`

### Phase 7: Migrate the exception pipeline onto the generic runner

Goal: prove the framework by making Cymbal itself consume it, without leaking exception types into core.

1. Add `ExceptionPipelineItem` in `crates/pipeline`, not in core.
2. Add `ExceptionStageDriver` around existing `PipelineExecutors`.
3. Move generic split/order/chunk code out of `crates/pipeline/src/streaming.rs` only when it has a matching core abstraction.
4. Preserve:
   - rate-limited terminal drops
   - resolution/grouping item-progress chunk behavior
   - linking and alerting as barriers
   - input-order output by default
   - completion-order option
   - all remote/local server integration behavior
5. Keep `process_exception_pipeline_streaming` as the public Cymbal API and implement it through the generic runner internally.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-pipeline`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test pipeline_snapshots -- --nocapture`
- `cargo test --manifest-path ../Cargo.toml -p cymbal-server --test grpc_integration -- --nocapture`
- `cargo clippy --manifest-path ../Cargo.toml --all-targets -p cymbal-core -p cymbal-pipeline -p cymbal-server -- -D warnings`

### Phase 8: Document and provide a non-exception example

Goal: make the framework agent-explorable and credible for future products.

1. Update `docs/reusable-pipeline-framework.md` with a minimal non-exception "widget" example using:
   - product payload types
   - `StageSpec`s
   - `LinearPipelineSpec::validate()`
   - optional `StageDriver`/runner if implemented
2. Add a small test-only example in `cymbal-core` or docs that does not import `cymbal-domain`.
3. Update `crates/README.md` with the new framework entrypoints.
4. Add a dependency guard to docs/tests if practical: `cargo tree -p cymbal-core` should stay free of product crates.

Validation:

- `cargo test --manifest-path ../Cargo.toml -p cymbal-core -p cymbal-pipeline -p cymbal-server --no-fail-fast`
- `cargo tree --manifest-path ../Cargo.toml -p cymbal-core`
- docs grep for stale ownership claims

## Failure modes and design guardrails

- **Over-generalized runner**: Avoid arbitrary DAGs, dynamic `Any` payloads, and hard-to-read type-level tuple machinery. Prefer a linear runner with a product-owned item enum.
- **Domain leakage back into core**: `cymbal-core` must remain free of `cymbal-domain` and stage crates. Add cargo-tree checks to implementation tasks.
- **Server/deployment leakage into core**: Keep local-vs-remote placement, target names, DNS, tonic, metadata, and metrics in `cymbal-server`. Core circuit breakers should expose decisions/transitions; server emits metrics and maps them to transport behavior.
- **Side-effect ambiguity**: Do not let generic fallback code retry side-effectful stages after ambiguous failures. Use explicit `StageEffectMode` / transient policy and preserve current conservative defaults. Circuit-open and admission/rate-limit rejections are pre-work; timeouts after dispatch are not.
- **Limiter policy leakage**: Core can own generic limiter decisions and mode application, but product crates own limiter keys, backend configs, reason strings, metrics, and terminal DTO mapping.
- **Wire compatibility drift**: The exception contract type strings (`cymbal.core.InputEvent@2`, `cymbal.core.RateLimitGateOutput@2`, `cymbal.core.EventResult@2`) are compatibility labels. Do not rename them as part of framework work.
- **Public API drift**: `ProcessExceptionBatch` callers should not see stage IDs, pipeline specs, or internal artifacts.
- **Agent confusion**: Keep module names and docs blunt: core has generic linear pipeline framework; pipeline crate has Cymbal's exception pipeline.

## Validation and quality gates

Every implementation phase should include:

```sh
cargo metadata --manifest-path ../Cargo.toml --format-version 1 --no-deps
cargo fmt --check --manifest-path ../Cargo.toml --all
git diff --check
```

Depending on touched crates, run:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-core
cargo test --manifest-path ../Cargo.toml -p cymbal-domain
cargo test --manifest-path ../Cargo.toml -p cymbal-pipeline
cargo test --manifest-path ../Cargo.toml -p cymbal-server --test pipeline_snapshots -- --nocapture
cargo test --manifest-path ../Cargo.toml -p cymbal-server --test grpc_integration -- --nocapture
cargo clippy --manifest-path ../Cargo.toml --all-targets \
  -p cymbal-core -p cymbal-domain -p cymbal-pipeline -p cymbal-server -- -D warnings
```

For final migration phases, repeat the broad Cymbal set from `README.md`. If SQLx/Postgres-backed symbol tests fail locally with `PoolTimedOut`, record the environmental blocker and run the narrower non-DB-blocked set as in `TASKS.md` Batch 6.

## Agent handoff and exploration notes

Start here:

- `crates/core/src/lib.rs` — current core exports and stage traits.
- `crates/core/src/executor.rs` — existing generic executor and intermediate output shape.
- `crates/core/src/progress.rs` — current progress modes.
- `crates/core/src/emission.rs` — ordered terminal emission.
- `crates/core/src/routing/` — routing/capacity/fallback framework primitives.
- `crates/server/src/remote/circuit.rs` — current server-private circuit breaker state machine to generalize into core.
- `crates/stages/rate-limiting/src/lib.rs` — current Cymbal team limiter adapter; use it to separate generic limiter semantics from exception/team policy.
- `crates/pipeline/src/stage_graph.rs` — Cymbal's concrete exception stage graph and default progress modes.
- `crates/pipeline/src/streaming.rs` — current exception streaming orchestration and item-progress chunking.
- `crates/server/src/registry.rs` — best first migration target for generic `LinearPipelineSpec` validation.
- `docs/reusable-pipeline-framework.md` — user-facing framework adoption guide.
- `docs/architecture.md` and `docs/compatibility.md` — update stale crate-boundary wording when touching docs.

Suggested first implementation PR:

1. Add `crates/core/src/pipeline.rs` with `StageSpec`, `LinearPipelineSpec`, `StageLinkRule`, and validation tests.
2. Re-export from core.
3. Add docs showing the new API.
4. Do **not** modify Cymbal runtime behavior yet.

Suggested second implementation PR:

1. Convert `crates/server/src/registry.rs` validation to use `LinearPipelineSpec`.
2. Keep existing registry behavior and tests.
3. Run server snapshots and grpc integration.

Suggested third implementation PR:

1. Move the generic circuit-breaker state machine from server to core.
2. Keep server endpoint storage/metrics as an adapter over core decisions.
3. Preserve remote fallback behavior and tests.

Suggested fourth implementation PR:

1. Add generic rate-limit/admission mode and decision helpers to core.
2. Refactor `cymbal-rate-limiting` to use them internally while preserving domain DTOs and wire strings.

## Open questions, assumptions, and tradeoffs

- **Assumption:** linear pipelines are enough. This intentionally rejects DAG/general workflow support until a real product proves it is needed.
- **Assumption:** product-owned homogeneous item enums are acceptable if/when a generic runner is added. This keeps the framework readable and avoids Rust heterogeneous-chain overengineering.
- **Open question:** should `StageEffectMode` and transient failure policy live in core's first `StageSpec`, or should Phase 1 keep only `progress` and type contracts? Default recommendation: include them early as metadata, but do not wire behavior until later.
- **Open question:** should circuit and rate-limit primitives live at `cymbal_core::{circuit, rate_limit}` or under a shared `resilience`/`admission` module? Default recommendation: start with explicit top-level modules for discoverability; merge later only if names sprawl.
- **Open question:** should `cymbal_domain::RateLimitDecision` become a type alias to `cymbal_core::RateLimitDecision<i64>`? Default recommendation: not immediately; use adapter conversions first to avoid accidental serde/wire-shape drift.
- **Open question:** should `StageRegistryError` move to core wholesale or stay as server-specific wrapper errors over `PipelineSpecError`? Default recommendation: introduce `PipelineSpecError` in core and let server wrap/convert only if it needs deployment-specific context.
- **Tradeoff:** adding `PipelineItem`/`TerminalItem` traits improves standardization but may be unnecessary while the closure-based `OrderedEmitter` works well. Default recommendation: add convenience traits only after spec validation has landed.
- **Tradeoff:** keeping `PipelineStage` as a core name may be slightly confusing, but renaming it now would create churn. Default recommendation: keep it and clarify docs.
