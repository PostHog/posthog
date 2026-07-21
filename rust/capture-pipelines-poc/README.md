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
`HasDistinctId` / `HasTimestamp` / `HasLane`. The demo pipeline mirrors the plan's
step templates: `Validate` → `ApplyQuota.fail_open()` → `ApplyRestrictions` → an async
`BatchAnnotate` chunk stage.

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

## Module tour

| Module | Contents |
|---|---|
| `result` | `StepResult`, `Outputs`, `NoOutputs`, `VerdictKind` |
| `step` | `Step` (infallible workhorse), `FallibleStep` |
| `chain` | `Chain`, `IntoOutputs`, typestate `PipelineBuilder`, `Pipeline` runner |
| `fail_open` | `FailOpen<S>` + the `.fail_open()` extension method |
| `capability` | capability traits, phase wrappers, lane markers, **`impl_passthrough_caps!`** |
| `fx` | `HasSink`, `WarningSink`, `WarningEffects`, **`compose_fx!`** |
| `observer` | `Observer`, `CountingObserver`, **`impl_observer_tuple!`** |
| `outputs` | `AnalyticsOutputs`, `Produce`, `MemProducer`, `OutputRegistry` |
| `chunk` | `ChunkStep` (native async-fn-in-trait), sync→chunk→sync runner |
| `demo` | the analytics demo steps, reused by `tests/analytics_demo.rs` |

The three `macro_rules!` macros each eliminate one class of boilerplate that a derive
macro would generate in the real framework: capability forwarding through wrappers
(`impl_passthrough_caps!`), `HasSink` wiring for a composed effects struct
(`compose_fx!`), and `Observer` impls for tuple composition (`impl_observer_tuple!`).

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
- **Two generic extension methods need type annotations at the call site.** Because
  `FallibleStepExt<In, Fx>` and the builder's unconstrained `.step` don't pin `In`/`Fx`
  locally, `.fail_open()` occasionally needs `FallibleStepExt::<In, Fx>::fail_open(..)`.
  In a real pipeline assembly these are inferred from the surrounding step types; the
  annotations only appear in isolated unit-test snippets.
- **`async_fn_in_trait` lint allowed crate-wide.** `ChunkStep` is a public trait with an
  `async fn`; the lint guards against auto-trait (`Send`) leakage, which a
  single-threaded demo doesn't need. The real framework would spell the `Send` bound out
  explicitly instead.
