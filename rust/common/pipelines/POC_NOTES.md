# common-pipelines POC notes

This crate is a proof-of-concept for the design in
`rust-ingestion-pipelines-design.md`. It follows the POC execution plan
(`rust-pipelines-poc-plan.md`): working + unit-tested + honest over maximal. No
derive macros, no typestate build-gating, no Redpanda integration tests.

This file records where the implementation deliberately deviates from the design
doc, and why.

## Framework (Phase A)

### Executor uses type-erased steps, not a monomorphized `Chain`

The design doc (§3.3) describes consecutive sync steps fusing into "one pass over
the chunk ... with no intermediate collections", monomorphized as a tower-style
`Chain<A, B>`. Two requirements pull against that fusion:

1. The executor must record **which step decided** a terminal verdict, for the
   `last_step_name` metric label. A fused `Chain::apply` returns only the verdict,
   losing the deciding step's identity.
2. The design wants **type-changing** steps (`RawMessage -> WithHeaders -> ...`)
   within a sync segment.

To satisfy both cheaply, the executor stores each sync segment as a
`Vec<Box<dyn ErasedStep<Fx, O>>>`. Each step is wrapped so it downcasts its input
from `Box<dyn Any + Send>`, runs, and re-boxes its output. The **typed builder**
(`PipelineBuilder<In, Cur, ...>`) threads the current context type as a generic
parameter, so `.step()` only accepts a step whose input matches the current type —
the chain is checked at compile time exactly as the design intends, and the
downcasts inside the executor can never fail by construction (a mismatch is a
framework bug and panics with a clear message).

Cost of the deviation: one `Box` allocation per event per step boundary, versus
the design's zero-allocation `Continue` path. This is the "simplest working
alternative" the plan explicitly blesses (`Vec<Box<dyn ...>>`). A future
monomorphized `Chain` that tags verdicts with step names can replace the erased
executor without changing the public `Step`/`ChunkStep` traits.

### No typestate `handle_results` build-gating

The design (§3.3) gates `.build()` behind `.handle_results()` via typestate. Per
the POC plan ("no typestate build-gating"), `.build()` is unconditional and
result handling is a separate free function (`outputs::handle_results`) the caller
invokes on the `ChunkOutcome`. The `Outputs`/`OutputRegistry` split still gives a
startup check (`OutputRegistry::check`) that fails if an output has no topic.

### `Observer::on_verdict` drops the `EventView` argument

The design's `Observer::on_verdict` takes `event: &dyn EventView`. The POC passes
only `(step, VerdictKind, reason)` — enough for the built-in metrics observer and
the dry-run comparison use case, without designing an event-view abstraction that
no POC consumer needs yet.

### `fail_open` requires `In: Clone`

`FailOpen<S>` passes the original event through on error. To hand the event to the
wrapped step *and* still have it available on the error path, the input is cloned
before the inner `apply` call. The design left the choice open ("`In: Clone` or
takes-and-returns pattern — pick one"); `In: Clone` is the simpler of the two and
all POC contexts are cheap to clone (`Bytes` refcounts, small structs).

### `handle_results` awaits produces sequentially, not concurrently

The design (§3.4) flushes all deferred effects into an `EffectQueue` and joins
every produce future before the batch completes. The POC's `handle_results`
awaits each DLQ/redirect produce in turn. This still satisfies the load-bearing
property — every produce completes before the function returns, so a caller can
gate commit on it — but does not exploit intra-batch produce concurrency. A
future version can collect the futures and `join_all` them without changing the
signature.

### Two produce paths coexist: `EffectQueue` (plugins) and `handle_results` (verdicts)

The design routes *everything* (plugin effects and verdict DLQ/redirect produces)
through the `EffectQueue`, executed once at chunk end. The POC keeps them
separate: plugin sinks flush into an `EffectQueue` (A4), while verdict-driven
DLQ/redirect produces go straight through `handle_results` (A5) from the
`ChunkOutcome` + aligned `RawRecord`s. A full harness (`harness.rs` in the
design) would unify these; the POC omits that harness and lets the consumer wire
the two pieces together, which is enough to prove both mechanisms.

### `EffectProducer` is built directly on rdkafka, not `common/kafka`

The design (§3.10) layers the output registry over `common/kafka`'s
`FutureProducer`. The POC's `RdKafkaEffectProducer<C>` is generic over any
`rdkafka` `ClientContext`, so a caller can pass a `common/kafka` producer without
this crate depending on `common-kafka`. Keeps the framework free of a
service-adjacent dependency for the POC.
