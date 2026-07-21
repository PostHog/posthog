# capture-pipelines-poc

A proof-of-concept skeleton for the capture pipelines framework, built with **static
dispatch only** — generics and `macro_rules!`, no `Box<dyn …>`, no `async_trait`, no
proc-macros. It exists to answer one open question from the design work: *can the
whole framework — composition, effects, observers, typed outputs, and async stages —
be expressed without type erasure?* This crate is the worked answer: **yes**.

It is a demonstration crate. There is no server, no Kafka, no Redis, no real config.
The only runtime dependency is `futures` (the concurrency combinators are built on its
stream combinators — the design says to buy these, not hand-roll Node's
synchronization engine); the only dev-dependency is `tokio`, to drive the async demos
in tests. It compiles, passes `cargo test`, and passes `cargo clippy -- -D warnings`.

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
enrichment capability).
The demo pipeline composes the plan's step templates *and* the structural combinators as **nested scopes** (`build_analytics_pipeline`) that mirror the Node builder's `sequentially` / `concurrentlyPerGroup` / `concurrently` callbacks, so the code shape matches the execution shape:

```rust
compose::<ParsedEvent, AnalyticsOutputs>()
    .sequentially(|b| b.step(Validate).step(ApplyQuota.fail_open()).step(Branching))
    .grouped(MAX, group_key /* token:distinct_id */, |group| group.in_order(OverflowCheck))
    .concurrently(MAX, |item| item.run(GeoAnnotate))
    .build()
```

The `Branching` is a `$$`-prefixed heatmap split that skips restrictions (mirroring capture's real split); `grouped` runs `concurrently_per_group` (the Node joined pipeline's post-team block) — `in_order` makes the "items in order within a group, groups concurrent" semantics explicit; `concurrently` runs a per-item `concurrently` enrichment. The composed value is still one flat, monomorphized type (no `Box`/`dyn`), returned behind an opaque `impl BatchPipeline`.
Running is `pipeline.run_batch(batch, &mut fx)`; a thin `handle_results` then produces redirects and maps verdicts — the only logic outside the composition.
The end-to-end test (`analytics_demo.rs`) asserts positional verdicts, branch routing, in-group ordering, and observed cross-group concurrency, all through the composed pipeline.

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
    batch.rs              BatchPipeline, SyncStage/ConcurrentStage/GroupedStage, Then, compose (scoped builder), Built
    fail_open.rs          FailOpen<S> + the .fail_open() extension method
    retry.rs              Retry<S> + .retry(tries, backoff) — injectable backoff
    extend.rs             forward_one_capability! — domain-agnostic forwarding machinery
    concurrency/          async combinators (built on futures)
      processor.rs        AsyncProcessor (per-item async, no &mut Fx)
      concurrently.rs     concurrently (FIFO), sequentially, filter_map
      grouping.rs         concurrently_per_group (keyed, in-order within group)
      branching.rs        Branching (classifier → exhaustive match)
    fx.rs                 HasSink, WarningSink, WarningEffects, compose_fx!
    observer.rs           Observer, CountingObserver, impl_observer_tuple!
    outputs.rs            Produce, MemProducer, OutputRegistry (generic; no domain enum)
  events/                 the demo event domain
    capabilities.rs       capability traits + lane markers + for_each_capability! registry
    wrappers.rs           Tagged (Validated), Restricted, WithGeo, Laned + one-line forwarding
    parsed.rs             ParsedEvent (a legitimate concrete boundary type)
  steps/                  one demo step per file
    validate.rs  enrich.rs  quota.rs  restrictions.rs  annotate.rs (async chunk step)
  pipeline/               the composed analytics pipeline
    mod.rs                AnalyticsFx, the nested-scope `compose` composition (returns impl BatchPipeline)
    runner.rs             async stage processors (OverflowCheck, GeoAnnotate) + handle_results (no composition)
    outputs.rs            AnalyticsOutputs enum + topic map
    accumulate.rs         Accumulating — per-key fold + threshold flush (replay shape)
```

The whole pipeline — sync steps, the heatmap branch, and both async stages — is one `compose()...build()` chain producing a single flat type (no `Box`/`dyn`, returned behind `impl BatchPipeline`; the boxless proof is `framework::batch`'s `composed_pipeline_with_async_stage_is_a_flat_struct` test).
Async stages compose *in* the builder as nested scopes: `.concurrently(|item| item.run(proc))` (per-item `concurrently`) and `.grouped(key_fn, |group| group.in_order(proc))` (`concurrently_per_group`) each append an async stage whose per-item body is nested in the callback, so the concurrency boundary is visible rather than reading like another flat step.
`pipeline/runner.rs` holds only the stage processors and the result handler — it does no composition.

## The forwarding problem

Wrappers must forward the capabilities of the event they wrap, or a downstream step's bounds stop resolving.
Done naively that is `wrappers × capabilities` hand-written impls — the boilerplate the user rejected.
The POC climbs the first two rungs of the ladder and documents the rest:

1. **Registry macro (here).**
   `for_each_capability!` lists the standard capabilities **exactly once** as `(Trait, accessor, ReturnType)` and drives a callback (`{ path } (prefix)`) that emits one impl per capability.
   A wrapper forwards them all with one line — `impl_passthrough_caps!(Restricted)` (or `_tagged!` / `_laned!` for the other generic shapes).
   Adding a capability is one registry line; adding a wrapper is one invocation.
   The domain-agnostic emitter (`forward_one_capability!`) lives in `framework/extend.rs` and names no domain traits; the registry lives in `events/` because it names them.
2. **Marker collapse (here).**
   Wrappers that add *no data* — pure phase tags — all share one generic `Tagged<Tag, In>`, so a single forwarding site covers every tag.
   `Validated<In>` is a `type` alias for `Tagged<ValidatedTag, In>`; a second phase tag costs zero forwarding.
   Wrappers that carry data (`WithGeo`, `Restricted`) or a type-level lane (`Laned`) stay concrete.
3. **Providing wrappers (hand-written, documented).**
   `WithGeo` *provides* `HasGeo`, so `HasGeo` is outside the registry and forwarded by hand on the three wrappers that pass it through.
   `macro_rules!` can't express "forward all *except* `HasGeo`"; a production framework would use `#[derive(Passthrough)]` with `except(HasGeo)` (a proc-macro).
4. **Zero-forwarding via type maps (rejected default).**
   An HList / type-map (`frunk`) inner-state design would need *no* forwarding at all, but at the cost of index type-params and inscrutable error messages.
   The design doc already passed on `frunk` for the effects struct for the same reason; we keep hand-written forwarding legible and reserve the type-map option for if wrapper count ever explodes.

## Pipeline shapes & combinators

Every structurally-impactful Node builder maps to a Rust demonstration or a documented deferral:

| Node builder | Rust demonstration |
|---|---|
| `concurrently(maxConcurrency)` | [`concurrently(max, proc, items)`] — `futures` `buffered`; bounded concurrency, FIFO emission. **Composed into the demo pipeline** as `.concurrently(MAX, \|item\| item.run(GeoAnnotate))`; also proven in isolation in `combinators.rs` (order preserved, `max_in_flight == 2`). |
| `concurrentlyPerGroup(groupingFn)` | [`concurrently_per_group(max, key_of, proc, items)`] — groups run concurrently (bounded), items strictly in-order within a group. Emits **positionally** (vs Node's group-completion order) because verdicts are recorded by position. **Composed into the demo pipeline** as `.grouped(MAX, token:distinct_id, \|group\| group.in_order(OverflowCheck))` (the Node post-team block); proven both there and in `combinators.rs` (in-group order, cross-group overlap, bounded, positional verdicts). |
| `sequentially` | Sync steps chain inside a `.sequentially(\|b\| b.step(..).step(..))` scope (the Node `sequentially` callback); an async `sequentially(proc, items)` is also provided for symmetry. |
| `branching` (`Exclude<TRemaining, B>`) | `Branching { classify, route }` — a classifier maps to a user enum, the router `match`es it. Exhaustiveness is the compiler's match check: adding a variant breaks every router until handled — the Rust answer to the `Exclude` builder trick. **Used in the demo pipeline** as the `$$`-heatmap split (`BranchStep`). |
| `gather` | Implicit: chunk stages already receive and return the whole `Vec<In>`, so gathering a chunk into one emission needs no combinator. |
| `filterMap` | `filter_map(results, f)` — map `Continue` values (which may re-drop), pass non-`Continue` verdicts through positionally. |
| retry (`withStepRetry` / `isRetriable`) | `Retry<S>` / `.retry(tries, backoff)` around a `FallibleStep`; backoff is an injectable `Fn(u32)` (tests record attempts, no real sleep). Still fallible, so it composes with `.fail_open()`. |
| `BatchingPipeline` before/after-batch hooks | Plain functions bracketing the runner — no framework machinery (`combinators.rs::batching_hooks_are_plain_functions_around_the_runner`). |
| accumulating (replay session buffering) | `Accumulating<K, T>` — per-key fold with threshold flush + end-of-batch drain; proves the accumulating shape fits static dispatch. |
| `concurrentlyPerGroup` unbounded, `messageAware`/`teamAware` scoping | Deferred: unbounded is `max = group_count`; the `*Aware` builder scopes are capability bounds here (`Fx: WarningEffects`), not builder subtypes. |

The concurrency combinators operate on an `AsyncProcessor` (per-item async, **no `&mut Fx`**): running many concurrently would make a shared `&mut Fx` unsound, and the framework collects effects at chunk boundaries (design §3.4), so per-item concurrent work stays effect-free.

## The macros

Five `macro_rules!` macros each eliminate one class of boilerplate a derive macro would generate in the real framework:
`for_each_capability!` (the capability registry, listed once),
`impl_passthrough_caps!` / `_tagged!` / `_laned!` (one-line capability forwarding per wrapper, driven by the registry via the domain-agnostic `forward_one_capability!` emitter),
`compose_fx!` (`HasSink` wiring for a composed effects struct),
and `impl_observer_tuple!` (`Observer` impls for tuple composition).

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
- **The concurrency combinators take an `AsyncProcessor`, not a `Step`.** It has no
  `&mut Fx` (concurrent per-item effects would need synchronization); effects belong at
  chunk boundaries. Wiring the combinators into the `Step`/`ChunkStep` builder is left
  as follow-up.
- **`concurrently_per_group` emits positionally, not in group-completion order** (the
  one intentional divergence from Node). Within-group order and bounded cross-group
  concurrency match Node exactly.

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
