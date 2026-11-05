# Parity with the Node ingestion framework

This crate is a port of `nodejs/src/ingestion/framework`.
The two implementations are kept in step: a change to one lands with the same change to the other, and the mirrored tests below change together.

## File map

| Node (`nodejs/src/ingestion/framework/`)      | Rust (`rust/ingestion-framework/src/`)                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `results.ts`                                  | `results.rs`                                                                               |
| `pipeline.interface.ts`                       | `context.rs` (types), `pipeline.rs` (`Pipeline` trait)                                     |
| `chunk-pipeline.interface.ts`                 | `chunk_pipeline.rs` (`ChunkPipeline` trait), `context.rs` (`ChunkResults`)                 |
| `steps.ts`                                    | `steps.rs`                                                                                 |
| `start-pipeline.ts`, `step-pipeline.ts`       | `pipeline.rs`                                                                              |
| `branching-pipeline.ts`                       | `branching.rs`                                                                             |
| `timeout-barrier-pipeline.ts`                 | `timeout_barrier.rs`                                                                       |
| `batch-budget.ts`                             | `budget.rs`                                                                                |
| `base-chunk-pipeline.ts`                      | `chunk_pipeline.rs` (`BaseChunkPipeline`, `apply_chunk_step_to_results`)                   |
| `buffering-chunk-pipeline.ts`                 | `chunk_pipeline.rs` (`BufferingChunkPipeline`)                                             |
| `sequential-chunk-pipeline.ts`                | `chunk_pipeline.rs` (`SequentialChunkPipeline`)                                            |
| `gathering-chunk-pipeline.ts`                 | `chunk_pipeline.rs` (`GatheringChunkPipeline`)                                             |
| `chunk-pipeline-unwrapper.ts`                 | `chunk_pipeline.rs` (`ChunkPipelineUnwrapper`)                                             |
| `concurrent-chunk-pipeline.ts`                | `concurrent.rs`                                                                            |
| `concurrently-grouping-chunk-pipeline.ts`     | `grouping.rs`                                                                              |
| `filter-map-chunk-pipeline.ts`                | `filter_map.rs`                                                                            |
| `fan-out-fan-in-chunk-pipeline.ts`            | `fan_out_fan_in.rs`                                                                        |
| `interleaving-chunk-pipeline.ts`              | `interleaving.rs`                                                                          |
| `resettable-signal.ts`                        | `sync.rs` (`ResettableSignal`); `sync.rs` (`FifoLimiter`) replaces `p-limit`               |
| `result-handling-pipeline.ts`                 | `result_handling.rs`                                                                       |
| `result-handling-helpers.ts`                  | `result_handling.rs` (`produce_message_to_dlq`, `redirect_message_to_output`, headers)     |
| `side-effect-handling-pipeline.ts`            | `side_effect_handling.rs`                                                                  |
| `ingestion-warning-handling-chunk-pipeline.ts`| `warning_handling.rs`                                                                      |
| `per-element-step.ts`                         | `per_element.rs` (`per_element`, also exported from `builders.rs`)                         |
| `retry.ts` (+ `retryIfRetriable`)             | `retry.rs`                                                                                 |
| `batching-pipeline.ts`                        | `batching.rs`                                                                              |
| `metrics.ts`                                  | `metrics.rs` (same metric names and labels)                                                |
| `helpers.ts`                                  | `helpers.rs`                                                                               |
| `builders/pipeline-builders.ts`               | `builders.rs` (`new_pipeline`, `PipelineBuilder`, `BranchingPipelineBuilder`)              |
| `builders/chunk-pipeline-builders.ts`         | `builders.rs` (`new_chunk_pipeline`, `ChunkPipelineBuilder`, group/fan-out/result builders)|
| `builders/helpers.ts`                         | `builders.rs` (`new_batching_pipeline`)                                                    |
| `~/common/outputs` (`IngestionOutputs`)       | `outputs.rs` (`IngestionOutputs` trait, `KafkaMessage`, `Headers`, `MemoryOutputs`)        |
| `~/common/utils/promise-scheduler`            | `side_effects.rs` (`PromiseScheduler`, `SideEffectScheduler`)                              |
| `~/ingestion/common/ingestion-warnings.ts` (`serializeIngestionWarning`, `emitIngestionWarning`) | `warning_handling.rs` (`serialize_ingestion_warning`, `OutputsWarningEmitter`), `js_json.rs` (`JSON.stringify` output) |
| `~/ingestion/common/ingestion-warning-types.ts` (`INGESTION_WARNING_TYPES`) | `warning_handling.rs` (`warning_classification`), read from `rust/common/ingestion_warnings/warning_types.generated.json`, which the Node registry exports |
| `span-attributes.ts`, `tophog/`, `extensions/`| not ported (see below)                                                                     |

## Mirrored tests

Each living-docs chapter `docs/NN-*.test.ts` has a Rust twin `tests/docs_NN_*.rs`, with one `#[tokio::test]` per Node `it(...)`.
The Rust test name is the snake_case form of the Node test name.
Jest fake timers map to `#[tokio::test(start_paused = true)]`: tokio advances the paused clock by itself when every task waits, and `tokio::time::advance` replaces a synchronous `jest.advanceTimersByTime`.

`per-element-step.test.ts` has the twin `tests/per_element_step.rs`.

`tests/unit_semantics.rs` pins behavior the chapters leave implicit: poison-then-drain for the concurrent and grouping stages, feed-while-parked, FIFO admission under `max_concurrency`, filter-map passthrough order, DLQ header layout, DLQ rethrow, warnings on timeouts, fan-out DLQ aggregation, and concurrent batch feeds on a multi-thread runtime.

`tests/review_regressions.rs` pins divergences that a review found and that are now fixed: the ingestion warning bytes, the fan-out `dlq_reason`, produce order on a multi-thread runtime, the redirect produce before `next()` returns, a dropped batching `next()`, scheduler cleanup, `tries: 0`, top-level retriability, a fan-in panic, `max_concurrency: Some(0)`, the cost of a group start, overlapping and cancelled scheduler waits, the parents a fan-in panic leaves ready, a group processor that panics before it returns its future, a dropped limiter `acquire()`, and retry options that give an out-of-range sleep.

`consumeAll(pipeline, ms)` and `jest.advanceTimersByTimeAsync(ms)` before an `await` map to `consume_all_within` and `within_ms` in `tests/common`, which fail the test when the work needs more virtual time than Node gives it.

### Skipped cases

| Node test                                                  | Why                                                                                                                                                                  |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/16-tophog-metrics.test.ts` (all four cases)          | TopHog (`framework/tophog/`) is a separate metrics aggregation subsystem, not part of the pipeline composition this crate ports. Port it as its own module if a Rust pipeline needs it. |

Everything else is mirrored. Where a Node assertion relies on a JS runtime detail, the Rust test checks the same observable behavior another way:

- `13-conventions` "pipelines are created via factory functions" uses `Arc::ptr_eq` for `not.toBe`.
- `07-result-handling` "REDIRECT with awaitAck=true" checks that `next()` does not finish within 50 ms while the ack is held, instead of `setImmediate`.
- `08-side-effects` "steps can add side effects" checks that the side effect ran before the step result is awaited, because `SideEffect::spawn` runs the future up to its first pending point, as a Node promise executor runs.

## Known differences

These are deliberate. Each one follows from a language difference. Items 1 to 15 do not change what a pipeline emits; items 16 to 19 change only timing or a failure path.

1. **Step names are explicit.** Node reads `fn.name`. Rust closures have no name, so `step("name", f)` and `chunk_step("name", f)` take one. Use the Node function name.
2. **A step error is `Err`, not a throw.** `PipelineError::retriable` / `non_retriable` stand in for `error.isRetriable`. An error with neither flag behaves like a Node error with no `isRetriable`: retried, then propagated. `is_retriable` reads the outermost error only, as Node reads the property of the thrown object: `PipelineError::non_retriable(..).context(..)` has no flag, so it retries. A `SharedError` reads through, because it is the same error object shared by more than one caller.
3. **Side effects start on creation.** A Node promise runs its executor (or an async function its body up to the first `await`) when it is created; a Rust future runs only when polled. `SideEffect::spawn` polls the future once on the caller's thread and moves the unfinished rest to a tokio task, so DLQ, redirect and warning produces are issued in item order inside `next()`, as in Node. A panic in that first poll becomes a failed side effect, as a throw before the first `await` rejects a promise. A `SideEffect` cannot be cloned, so a step's side effects and warnings move from the result into the context (Node keeps a copy on both).
4. **`ResultWithContext.result` is an `Outcome`.** Side effects and warnings live only on the context once a step finishes.
5. **The user context is a field.** Node spreads `C` into the context object; Rust stores it in `PipelineContext.data` with `Deref`. `message_id` (Node's `BatchingContext`) is a base context field, so batching does not change the context type. `traceContext` is not ported.
6. **Structural context access is a trait.** `message_aware`/`handle_results` require `HasMessage`; `team_aware`/`handle_ingestion_warnings` require `HasTeamId`.
7. **`filter_map` output context.** Node types it as the union `CSubOutput | CIntermediate`. Rust requires `CSubOutput: From<CIntermediate>` and converts non-OK passthroughs with it.
8. **Batch context is not spread into values.** Node's sub-pipeline values are `TInput & CBatch`. Rust's are `WithBatch<T, CB>` (value plus `Arc<CB>`, with `Deref` to the value). The caller's feed context returns as `BatchResult.feed_context` rather than merged into `batch_context`.
9. **Retries clone the input.** `pipe_with_retry` needs `T: Clone + Sync`, because each attempt takes the value by value. Every attempt but the last possible one gets a clone, so `tries: 1` clones nothing; the first of several attempts cannot take the original, because a retry needs it again. Node passes the same reference.
10. **Compile-time checks that become run-time.** Node checks branch exhaustiveness, redirect output names and warning types in the type system. Rust uses string names, so an unknown branch is the run-time DLQ that Node also has, an unknown output fails in the `IngestionOutputs` implementation, and an unregistered warning type fails its side effect, as Node's registry lookup throws at run time.
11. **Ingestion warnings.** The Node `IngestionWarningLimiter` is an app concern: `IngestionWarningEmitter` is the seam, and `OutputsWarningEmitter` emits with no limiter. `serialize_ingestion_warning` writes the Node bytes with `js_json` (key order, `JSON.stringify` numbers and escapes, array-index keys first), with no dependence on serde_json's `preserve_order` feature. `category` and `severity` come from the registry JSON that the Node registry exports. `PipelineWarning.details` is an `IndexMap`, so its keys keep insertion order; build ordered details with `with_detail`, because a `json!` object sorts its keys unless the build enables `preserve_order`. A nested object inside a detail value is a `serde_json::Map` and is written in that map's order, which is sorted in a build without `preserve_order`; Node keeps insertion order there too. Keep details flat where the bytes must match.
12. **Fan-out DLQ error.** Node builds `AggregateError(errors, reason)`; Rust builds `errors::AggregateError` with the same message and every sub error. The `dlq_reason` header is identical.
13. **Concurrency.** Concurrent items and groups run as tokio tasks, so on a multi-thread runtime they run in parallel; Node interleaves them on one thread. Ordering guarantees (FIFO emission, per-key order, FIFO admission under a cap) are the same. When a group completes, the queues still waiting all belong to running groups, so their relative order no longer matters and the remove is O(1). The interleaving stage keeps the pending sub-pipeline pull as a stored boxed future so it survives across `next()` calls, which is how Node keeps its memoized promise. That future is polled only while a `next()` is awaited. Item and group work runs in its own tasks and never pauses, but sub-pipeline stages that the pull itself drives (for example a `sequentially` inside `filter_map`) advance only while the caller waits on `next()`. A Node promise advances in the background. This changes timing, not results or order; every consumer loops on `next()` anyway. A spawned task per `next()` was measured first and cost a cross-thread wake per emitted chunk.
14. **Clock.** `BatchBudget` reads `tokio::time::Instant`, so it follows a paused test clock as Node's follows `Date.now()` under fake timers.
15. **Not ported:** `span-attributes.ts` and OTel span parenting (Rust uses `tracing`), `tophog/`, and `extensions/`.
16. **Cancel safety.** Node has no cancellation. `BatchingPipeline::next()` is cancel-safe: it keeps its sub-pipeline pull, the results it has not routed, and a running afterBatch hook under its pump lock, and the next call resumes them, so a dropped call (for example from an HTTP handler whose client went away) loses no batch and runs no hook twice. A `ChunkPipeline::next()` is not cancel-safe: the interleaving stages keep their pull, but a stage such as `pipe_chunk`, result handling or side-effect handling holds the chunk in the dropped future. Do not race a chunk pipeline's `next()` against a timeout. A dropped batching `next()` also leaves the hook paused until the next call polls it, where Node's would run on.
17. **`PromiseScheduler` keeps the first failure.** Node removes a promise when it settles, so a rejection that settles before `waitForAll()` is not seen there. The Rust scheduler keeps it, as the `FailureLatchingPromiseScheduler` of the Node metrics consumer does, because a consumer that misses it stores the offsets of a batch whose side effect failed. A settled side effect leaves the set at the next `schedule()` that finds the set grown to twice its size after the last cleanup, at `pending_count()`, or when a `wait_for_all()` sees it settle. As in Node, a side effect stays in the set until it settles, so an overlapping `wait_for_all()` also waits for it, and a cancelled one leaves it, and its failure, for the next call. `wait_for_all()` waits for every side effect pending at the call and then returns the first failure; Node's `Promise.all` rejects at the first failure without waiting for the rest.
18. **User callbacks that panic.** A panic in a grouping function, fan-out function or fan-in function becomes an error from `next()`, as a Node throw rejects `next()` and poisons the stage. No lock is held while user code runs. `max_concurrency: Some(0)` panics when the stage is built, as `pLimit(0)` throws.
19. **`per_element` rejects late.** Node's `Promise.all` rejects at the first failed step, and the other steps run on. Rust waits for the other steps and then returns the first error to occur.

## Benchmarks

`benches/framework.rs` (criterion) and `nodejs/src/ingestion/framework/benchmarks/framework-bench.ts` run the same six workloads at sizes 1, 100 and 10 000, with trivial steps, so the numbers are framework overhead per element. The Rust benchmark installs a Prometheus recorder, so both sides pay for their metrics.

```bash
cd rust && cargo bench -p ingestion-framework --bench framework
```

```bash
cd nodejs && DATABASE_URL=postgres://localhost/bench pnpm exec tsx src/ingestion/framework/benchmarks/framework-bench.ts
```

### Measured overhead

One 4-vCPU cloud container, the two runs one after the other. Mean ns per element; lower is better. Rust numbers are on a current-thread runtime, which matches the single Node event loop.

| Workload                         | Size   | Node (ns/elem) | Rust (ns/elem) | Node ÷ Rust |
| -------------------------------- | ------ | -------------- | -------------- | ----------- |
| `step_pipeline_5_steps`          | 1      | 30 383         | 2 379          | 12.8×       |
| `step_pipeline_5_steps`          | 100    | 17 827         | 2 349          | 7.6×        |
| `step_pipeline_5_steps`          | 10 000 | 19 693         | 2 307          | 8.5×        |
| `pipe_chunk_5_steps`             | 1      | 25 940         | 3 483          | 7.4×        |
| `pipe_chunk_5_steps`             | 100    | 722            | 431            | 1.7×        |
| `pipe_chunk_5_steps`             | 10 000 | 740            | 541            | 1.4×        |
| `concurrently_max50`             | 1      | 24 758         | 3 613          | 6.9×        |
| `concurrently_max50`             | 100    | 8 488          | 1 873          | 4.5×        |
| `concurrently_max50`             | 10 000 | 10 007         | 2 187          | 4.6×        |
| `per_element_max50`              | 1      | 20 834         | 2 399          | 8.7×        |
| `per_element_max50`              | 100    | 1 912          | 1 118          | 1.7×        |
| `per_element_max50`              | 10 000 | 4 108          | 2 248          | 1.8×        |
| `concurrently_per_group_16`      | 1      | 14 492         | 5 165          | 2.8×        |
| `concurrently_per_group_16`      | 100    | 7 470          | 1 302          | 5.7×        |
| `concurrently_per_group_16`      | 10 000 | 8 586          | 1 091          | 7.9×        |
| `batching_full`                  | 1      | 53 331         | 8 726          | 6.1×        |
| `batching_full`                  | 100    | 7 091          | 1 454          | 4.9×        |
| `batching_full`                  | 10 000 | 6 868          | 1 400          | 4.9×        |

On a 4-worker multi-thread runtime, the 10 000-element workloads run at 1 885 (`concurrently_max50`), 947 (`concurrently_per_group_16`) and 1 798 (`batching_full`) ns per element. Single-element batches cost about 50 µs there, which is worker wake-up latency, so a current-thread runtime suits a consumer that feeds tiny batches.

The Node per-step cost is dominated by the per-step instrumentation (`instrumentFn`, the prom-client step histogram); the Rust port records the same histogram through the `metrics` crate.
