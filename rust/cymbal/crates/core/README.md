# cymbal-core

Transport-neutral pipeline framework for typed stage graphs.

Edit this package when changing reusable framework primitives only:

- stage identity and payload contracts (`StageType`, `StagePayload`, `StageCodec`)
- stage execution traits (`PipelineStage`, `PerItemStage`, `StageExecutor`, `LocalExecutor`, `ContinueExecutor`)
- generic intermediate, progress, and emission helpers (`IntermediateStageOutput<T, Terminal>`, `StageProgressMode`, `PipelineEventState<T, StageId>`, `Sink<T>`, `EmissionOrder`, `OrderedEmitter<T, S, F>`)
- routing, capacity, affinity, and fallback primitives in `src/routing/`
- generic circuit-breaker state and retry-after helpers in `src/circuit.rs`
- generic linear pipeline contract types and validation (`pipeline::{StageSpec, LinearPipelineSpec, StageLinkRule, PipelineSpecError}`)
- generic linear runner APIs (`runner::{PipelineItem, TerminalItem, StageBatchOutcome, StageDriver, LinearPipelineRunner}`)
- generic circuit-breaker state and rate-limit/admission primitives (`circuit`, `rate_limit`)
- shared stage concurrency primitives (`StageConcurrencyLimiter`, `run_buffered`)
- shared context and errors (`BatchContext`, `Metadata`, `StageInput`, `StageError`)

Do not add exception-domain DTOs, gRPC/protobuf types, persistence, runtime config, or stage business logic here.
Exception-pipeline contracts such as `InputEvent`, `EventResult`, `EventOutcome`, and `RateLimitGateOutput` live in `cymbal-domain::event`; they keep their historical `cymbal.core.*` payload strings only as wire-compatibility labels.

The framework direction is intentionally linear, batch-oriented, and domain-agnostic.
Core owns reusable specs, validation, runner mechanics, circuit/admission mechanics, and ordered emission; server deployment concerns and Cymbal exception adapters stay outside this crate.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-core
```
