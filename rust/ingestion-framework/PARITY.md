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
| `retry.ts` (+ `retryIfRetriable`)             | `retry.rs`                                                                                 |
| `batching-pipeline.ts`                        | `batching.rs`                                                                              |
| `metrics.ts`                                  | `metrics.rs` (same metric names and labels)                                                |
| `helpers.ts`                                  | `helpers.rs`                                                                               |
| `builders/pipeline-builders.ts`               | `builders.rs` (`new_pipeline`, `PipelineBuilder`, `BranchingPipelineBuilder`)              |
| `builders/chunk-pipeline-builders.ts`         | `builders.rs` (`new_chunk_pipeline`, `ChunkPipelineBuilder`, group/fan-out/result builders)|
| `builders/helpers.ts`                         | `builders.rs` (`new_batching_pipeline`)                                                    |
| `~/common/outputs` (`IngestionOutputs`)       | `outputs.rs` (`IngestionOutputs` trait, `KafkaMessage`, `Headers`, `MemoryOutputs`)        |
| `~/common/utils/promise-scheduler`            | `side_effects.rs` (`PromiseScheduler`, `SideEffectScheduler`)                              |
| `span-attributes.ts`, `tophog/`, `extensions/`| not ported (see below)                                                                     |

## Mirrored tests

Each living-docs chapter `docs/NN-*.test.ts` has a Rust twin `tests/docs_NN_*.rs`, with one `#[tokio::test]` per Node `it(...)`.
The Node test name is the doc comment above each Rust test.
Jest fake timers map to `#[tokio::test(start_paused = true)]`: tokio advances the paused clock by itself when every task waits, and `tokio::time::advance` replaces a synchronous `jest.advanceTimersByTime`.

`tests/unit_semantics.rs` pins behavior the chapters leave implicit: poison-then-drain for the concurrent and grouping stages, feed-while-parked, FIFO admission under `max_concurrency`, filter-map passthrough order, DLQ header layout, DLQ rethrow, warnings on timeouts, fan-out DLQ aggregation, and concurrent batch feeds on a multi-thread runtime.

### Skipped cases

| Node test                                                  | Why                                                                                                                                                                  |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/16-tophog-metrics.test.ts` (all four cases)          | TopHog (`framework/tophog/`) is a separate metrics aggregation subsystem, not part of the pipeline composition this crate ports. Port it as its own module if a Rust pipeline needs it. |

Everything else is mirrored. Where a Node assertion relies on a JS runtime detail, the Rust test checks the same observable behavior another way:

- `13-conventions` "pipelines are created via factory functions" uses `Arc::ptr_eq` for `not.toBe`.
- `07-result-handling` "REDIRECT with awaitAck=true" checks that `next()` does not finish within 50 ms while the ack is held, instead of `setImmediate`.
- `09-ingestion-warnings` debouncing cases check the `key` and `always_send` fields; the limiter itself sits behind `IngestionWarningEmitter` (see below).

## Known differences

These are deliberate. Each one follows from a language difference, and none changes what a pipeline emits.

1. **Step names are explicit.** Node reads `fn.name`. Rust closures have no name, so `step("name", f)` and `chunk_step("name", f)` take one. Use the Node function name.
2. **A step error is `Err`, not a throw.** `PipelineError::retriable` / `non_retriable` stand in for `error.isRetriable`. An error with neither flag behaves like a Node error with no `isRetriable`: retried, then propagated.
3. **Side effects are spawned tasks.** A Node promise runs from creation; a Rust future runs only when polled, so `SideEffect::spawn` starts a tokio task. A `SideEffect` cannot be cloned, so a step's side effects and warnings move from the result into the context (Node keeps a copy on both).
4. **`ResultWithContext.result` is an `Outcome`.** Side effects and warnings live only on the context once a step finishes.
5. **The user context is a field.** Node spreads `C` into the context object; Rust stores it in `PipelineContext.data` with `Deref`. `message_id` (Node's `BatchingContext`) is a base context field, so batching does not change the context type. `traceContext` is not ported.
6. **Structural context access is a trait.** `message_aware`/`handle_results` require `HasMessage`; `team_aware`/`handle_ingestion_warnings` require `HasTeamId`.
7. **`filter_map` output context.** Node types it as the union `CSubOutput | CIntermediate`. Rust requires `CSubOutput: From<CIntermediate>` and converts non-OK passthroughs with it.
8. **Batch context is not spread into values.** Node's sub-pipeline values are `TInput & CBatch`. Rust's are `WithBatch<T, CB>` (value plus `Arc<CB>`, with `Deref` to the value). The caller's feed context returns as `BatchResult.feed_context` rather than merged into `batch_context`.
9. **Retries clone the input.** `pipe_with_retry` needs `T: Clone + Sync`, because each attempt takes the value by value. Node passes the same reference.
10. **Compile-time checks that become run-time.** Node checks branch exhaustiveness and redirect output names in the type system. Rust uses string names, so an unknown branch is the run-time DLQ that Node also has, and an unknown output fails in the `IngestionOutputs` implementation.
11. **Ingestion warning rate limit.** The Node `IngestionWarningLimiter` and the `INGESTION_WARNING_TYPES` registry (category, severity) are app concerns. `IngestionWarningEmitter` is the seam; `OutputsWarningEmitter` serializes the Node message shape with no limiter.
12. **Fan-out DLQ error.** Node builds an `AggregateError`; Rust builds one `anyhow` error whose message lists every sub error. The DLQ reason string is identical.
13. **Concurrency.** Concurrent items and groups run as tokio tasks, so on a multi-thread runtime they run in parallel; Node interleaves them on one thread. Ordering guarantees (FIFO emission, per-key order, FIFO admission under a cap) are the same. The interleaving stage keeps the pending sub-pipeline pull as a stored boxed future so it survives across `next()` calls, which is how Node keeps its memoized promise. That future is polled only while a `next()` is awaited. Item and group work runs in its own tasks and never pauses, but sub-pipeline stages that the pull itself drives (for example a `sequentially` inside `filter_map`) advance only while the caller waits on `next()`. A Node promise advances in the background. This changes timing, not results or order; every consumer loops on `next()` anyway. A spawned task per `next()` was measured first and cost a cross-thread wake per emitted chunk.
16. **`next()` is not cancel-safe.** Dropping a pending `next()` drops the in-flight sub-pipeline pull and the results it held. Node has no cancellation, so no Node caller depends on this; Rust callers must not race `next()` against a timeout and drop it.
14. **Clock.** `BatchBudget` reads `tokio::time::Instant`, so it follows a paused test clock as Node's follows `Date.now()` under fake timers.
15. **Not ported:** `span-attributes.ts` and OTel span parenting (Rust uses `tracing`), `tophog/`, and `extensions/`.

## Benchmarks

`benches/framework.rs` (criterion) and `nodejs/src/ingestion/framework/benchmarks/framework-bench.ts` run the same five workloads at sizes 1, 100 and 10 000, with trivial steps, so the numbers are framework overhead per element.

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
| `step_pipeline_5_steps`          | 1      | 19 079         | 1 654          | 11.5×       |
| `step_pipeline_5_steps`          | 100    | 19 089         | 1 771          | 10.8×       |
| `step_pipeline_5_steps`          | 10 000 | 24 731         | 1 602          | 15.4×       |
| `pipe_chunk_5_steps`             | 1      | 35 913         | 2 821          | 12.7×       |
| `pipe_chunk_5_steps`             | 100    | 1 146          | 512            | 2.2×        |
| `pipe_chunk_5_steps`             | 10 000 | 993            | 469            | 2.1×        |
| `concurrently_max50`             | 1      | 30 215         | 3 792          | 8.0×        |
| `concurrently_max50`             | 100    | 13 231         | 1 582          | 8.4×        |
| `concurrently_max50`             | 10 000 | 13 869         | 1 743          | 8.0×        |
| `concurrently_per_group_16`      | 1      | 17 291         | 4 946          | 3.5×        |
| `concurrently_per_group_16`      | 100    | 10 862         | 1 098          | 9.9×        |
| `concurrently_per_group_16`      | 10 000 | 10 364         | 780            | 13.3×       |
| `batching_full`                  | 1      | 63 344         | 7 849          | 8.1×        |
| `batching_full`                  | 100    | 9 593          | 1 368          | 7.0×        |
| `batching_full`                  | 10 000 | 8 769          | 1 162          | 7.5×        |

On a 4-worker multi-thread runtime, the 10 000-element workloads run at 1 706 (`concurrently_max50`), 502 (`concurrently_per_group_16`) and 1 028 (`batching_full`) ns per element. Single-element batches cost about 50 µs there, which is worker wake-up latency, so a current-thread runtime suits a consumer that feeds tiny batches.

The Node per-step cost is dominated by the per-step instrumentation (`instrumentFn`, the prom-client step histogram); the Rust port records the same histogram through the `metrics` crate.
