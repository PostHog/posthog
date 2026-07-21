# capture-pipelines-poc

A proof-of-concept skeleton for the capture pipelines framework, built with **static
dispatch only** — generics and `macro_rules!`, no `Box<dyn …>`, no `async_trait`, no
proc-macros. It exists to answer one open question from the design work: *can the
whole framework — composition, effects, observers, typed outputs, and async stages —
be expressed without type erasure?* This crate is the worked answer: **yes**.

It is a demonstration crate. There is no server, no Kafka, no Redis, no real config.
`[dependencies]` is empty; the only dev-dependency is `tokio`, used to drive the async
chunk-step demos in tests. It compiles, passes `cargo test`, and passes
`cargo clippy -- -D warnings`.

## Why: the #70814 gap

The earlier POC (#70814) proved the pipeline *shape* but leaned on a type-erased
executor — its runner was a `Vec<Box<dyn ErasedStep>>`, so every step boundary was a
vtable call and every event outcome flowed through a boxed, dynamically-dispatched
interface. That is the one thing this crate deliberately does differently. Here:

| #70814 gap | This POC |
|---|---|
| `Vec<Box<dyn ErasedStep>>` executor | `Chain<Chain<A, B>, C>` — one flat, monomorphized struct (see the `static_dispatch_is_a_flat_struct` test: a ZST pipeline is *zero bytes*) |
| dynamic dispatch per step | generics; each step boundary inlines |
| erased outputs / stringly redirects | per-pipeline `Outputs` enum, completeness-checked at startup (`OutputRegistry::check`) |
| async via `async_trait` (boxed futures) | native async-fn-in-trait (`ChunkStep`), no boxing |
| cross-cutting concerns baked into the context | effects as compile-time capabilities (`Fx: WarningEffects`); a missing sink is a compile error |
| observers as `Vec<Box<dyn Observer>>` | tuple composition (`(A, B, C): Observer`), static |

## How it maps to the capture-evolution plan

The public vocabulary matches the plan page and the design doc (§3.2–3.4):
`Step`, `FallibleStep`, `StepResult`, `Outputs`/`NoOutputs`, `OutputRegistry`,
`fail_open`, `HasSink`, and the capability traits `HasToken` / `HasEventName` /
`HasDistinctId` / `HasTimestamp` / `HasTeamId` / `HasLane` (plus a demo `HasGeo`
enrichment capability). The demo pipeline mirrors the plan's step templates: `Validate`
→ `ApplyQuota.fail_open()` → `ApplyRestrictions` → an async `BatchAnnotate` chunk stage.

Three properties from the design are made *structural* here:

- **Fail-open is compile-enforced.** A capture chain composes only infallible `Step`s.
  A fallible limiter (`FallibleStep`) cannot join it until wrapped with `.fail_open()`,
  which turns any `Err` into "pass the event through unchanged" plus a counter bump.
- **Missing effects don't compile.** A step that emits warnings bounds `Fx:
  WarningEffects`; a pipeline whose composed `Fx` lacks the `WarningSink` won't compile
  it. This is proved by a `compile_fail` doc-test on `compose_fx!`.
- **Historical never overflows.** Lanes are encoded at the type level
  (`HasLane<Lane = Main>`), so an overflow step simply cannot accept a
  `Laned<_, Historical>` — it's a type error, not a runtime guard.

## Steps are open by default

A step is generic over its input `In`, bounding only the capability traits it reads
(`In: HasToken + HasEventName`, never `In = ParsedEvent`), and generic over the effects
struct `Fx`. This is the Node framework's "input open to extension" property: an
upstream step can *enrich* an event — wrapping it to add a field or a whole new
capability — and every downstream step keeps compiling unchanged, because none of them
named the concrete type. A step may fix a concrete input or output type **only when
there is a good reason, stated in a doc comment** — the legitimate cases being boundary
steps that create the initial type (`ParsedEvent` at intake), steps whose job is
type-specific aggregation/folding, and adapters at the pipeline edge. `enrich`'s
concrete *output* wrapper is exactly the "creates a new capability layer" case; every
other demo step is fully open. The `open_extension_*` integration test inserts `Enrich`
ahead of the unmodified `Validate`/`ApplyRestrictions` steps and proves the enrichment
survives to the end.

## Layout

The crate mirrors the Node ingestion layering, one primary abstraction per file, with a
strictly one-way dependency direction `framework ← events ← steps ← pipeline`.

```text
src/
  lib.rs                  crate docs + module tree + ergonomic re-exports
  framework/              reusable, domain-agnostic machinery (never references the domain layers)
    result.rs             StepResult, Outputs, NoOutputs, VerdictKind
    step.rs               Step (infallible workhorse), FallibleStep
    chain.rs              Chain, IntoOutputs, Identity, typestate PipelineBuilder, Pipeline runner
    chunk.rs              ChunkStep (native async-fn-in-trait), yield_now, sync→chunk→sync runner
    fail_open.rs          FailOpen<S> + the .fail_open() extension method
    extend.rs             impl_passthrough_caps! — generic wrapper/openness machinery
    fx.rs                 HasSink, WarningSink, WarningEffects, compose_fx!
    observer.rs           Observer, CountingObserver, impl_observer_tuple!
    outputs.rs            Produce, MemProducer, OutputRegistry (generic; no domain enum)
  events/                 the demo event domain
    capabilities.rs       HasToken/EventName/DistinctId/Timestamp/TeamId/Geo/Lane + lane markers
    wrappers.rs           Validated, Restricted, WithGeo, Laned + capability forwarding
    parsed.rs             ParsedEvent (a legitimate concrete boundary type)
  steps/                  one demo step per file
    validate.rs  enrich.rs  quota.rs  restrictions.rs  annotate.rs (async chunk step)
  pipeline/               the composed analytics pipeline
    mod.rs                AnalyticsFx (compose_fx!), AnalyticsPipeline type alias, builder wiring
    outputs.rs            AnalyticsOutputs enum + topic map
```

The three `macro_rules!` macros each eliminate one class of boilerplate that a derive
macro would generate in the real framework: capability forwarding through wrappers
(`impl_passthrough_caps!`, kept domain-agnostic — it takes the trait/accessor list as
arguments), `HasSink` wiring for a composed effects struct (`compose_fx!`), and
`Observer` impls for tuple composition (`impl_observer_tuple!`).

## Running

From the workspace `rust/` directory:

```bash
cargo test   -p capture-pipelines-poc
cargo clippy -p capture-pipelines-poc --all-targets -- -D warnings
cargo fmt    -p capture-pipelines-poc -- --check
```

## What's simplified (honest list)

This is a skeleton, not the framework. Deliberately out of scope, and where it cuts
corners:

- **No I/O layer.** No Kafka producer, Redis, HTTP, or metrics crate. `MemProducer`
  stands in for a real producer; `fail_open` counts with a plain `AtomicU64` instead of
  a metrics counter; "produce on redirect" is modelled as the harness handing raw bytes
  to `OutputRegistry::emit`.
- **`StepResult::Dlq` carries no error payload.** The design's `Dlq { reason, error:
  Option<anyhow::Error> }` is trimmed to `Dlq { reason }` to keep `[dependencies]`
  empty.
- **No harness/effect-queue/gate/consumer-loop.** `EffectQueue`, deferred-produce
  draining, the request-phase `Gate` concept, and the batch executor with commit
  accounting are all future work; the POC runs the sync chain and one chunk stage
  directly in the demo test.
- **`fail_open` requires `In: Clone` and a pure filter (`Out == In`).** On error it
  returns a cheap clone of the original input. The real framework would additionally
  `catch_unwind` per event for panic isolation.
- **The chunk stage passes events through unchanged** (a `yield_now` plus a stamp),
  standing in for a batched Redis lookup; the point demonstrated is ordering and the
  same-length invariant, not the lookup itself.
- **Observers are notified by the demo harness, not a built-in executor.** In the real
  framework the batch executor drives observer callbacks; here the integration test
  calls `on_verdict` in its run loop.

### Deviations from the brief

- **Output unification via `IntoOutputs`, not same-type-only.** The brief offered a
  choice; a chain unifies on the downstream step's `Outputs` and lifts the upstream one
  in. `NoOutputs → O` is free (uninhabited); a concrete enum needs a one-line identity
  impl (`impl IntoOutputs<AnalyticsOutputs> for AnalyticsOutputs`). There is no
  reflexive blanket impl — it would overlap the `NoOutputs` impl and break coherence.
- **`.fail_open()` needs its `In`/`Fx` named where the builder can't infer them.**
  `FallibleStepExt<In, Fx>` is generic and the builder's `.step` is intentionally
  unconstrained, so wiring a fallible step into a builder chain uses
  `FallibleStepExt::<In, Fx>::fail_open(..)` (see `build_analytics_pipeline`). The
  return-type alias then pins the whole composed shape, so this appears once at the
  assembly site, not at every call.
- **`async_fn_in_trait` lint allowed crate-wide.** `ChunkStep` is a public trait with an
  `async fn`; the lint guards against auto-trait (`Send`) leakage, which a
  single-threaded demo doesn't need. The real framework would spell the `Send` bound out
  explicitly instead.
