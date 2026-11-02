mod common;

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{items, test_message, MockOutputs, MsgCtx};
use futures::FutureExt;
use ingestion_framework::warning_handling::serialize_ingestion_warning;
use ingestion_framework::{
    chunk_step, create_ok_context, dlq, new_batching_pipeline, new_chunk_pipeline, new_pipeline,
    ok, redirect_with, step, BatchingPipelineOptions, ChunkPipeline, MemoryOutputs, PipelineConfig,
    PipelineError, PipelineWarning, PromiseScheduler, RetryOptions, SideEffect,
    SideEffectHandlingConfig, SideEffectScheduler, DLQ_OUTPUT,
};

const AWAIT: SideEffectHandlingConfig = SideEffectHandlingConfig {
    await_side_effects: true,
};

// The expected prefix is Node's `JSON.stringify({team_id, type, source, details, timestamp})`.
#[test]
fn warning_message_bytes_match_node() {
    let mut w = PipelineWarning::new("client_ingestion_warning", serde_json::json!({}))
        .with_detail("zeta", 1)
        .with_detail("category", "caller")
        .with_detail("alpha", 1.0)
        .with_detail("big", 1e21);
    w.pipeline_step = Some("s".into());
    let s = serialize_ingestion_warning(42, &w).unwrap();
    let expected = r#"{"team_id":42,"type":"client_ingestion_warning","source":"plugin-server","details":"{\"zeta\":1,\"category\":\"event\",\"alpha\":1,\"big\":1e+21,\"severity\":\"info\",\"pipelineStep\":\"s\"}","timestamp":""#;
    assert!(s.starts_with(expected), "{s}");
    let timestamp = &s[expected.len()..s.len() - 2];
    assert!(
        chrono::NaiveDateTime::parse_from_str(timestamp, "%Y-%m-%d %H:%M:%S%.3f").is_ok()
            && timestamp.len() == 23,
        "{timestamp}"
    );
}

#[test]
fn warning_type_outside_the_registry_fails_like_the_node_lookup() {
    let w = PipelineWarning::new("not_a_registered_type", serde_json::json!({}));
    assert!(serialize_ingestion_warning(1, &w).is_err());
}

// Node's DLQ error is `AggregateError(errors, reason)`, and `dlq_reason` is its message.
#[tokio::test]
async fn fan_out_dlq_reason_header_is_the_aggregate_reason_only() {
    let outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<i64, MsgCtx>()
        .fan_out("split", |n: &i64| vec![*n])
        .via(|b| {
            b.pipe_chunk(chunk_step("check", |v: Vec<i64>| async move {
                Ok(v.into_iter()
                    .map(|_| dlq::<i64>("bad sub", Some(anyhow::anyhow!("boom"))))
                    .collect())
            }))
        })
        .fan_in("merge", |o: i64, _s: Vec<i64>| o)
        .message_aware(|b| b)
        .handle_results(PipelineConfig {
            outputs: Arc::new(outputs.clone()),
            scheduler: Arc::new(scheduler.clone()),
            reject_on_dlq_failure: false,
        })
        .handle_side_effects(Arc::new(scheduler), AWAIT)
        .build();
    pipeline.feed(vec![create_ok_context(
        1,
        MsgCtx {
            message: test_message(None),
        },
    )]);
    pipeline.next().await.unwrap().unwrap();
    let calls = outputs.calls();
    assert_eq!(
        calls[0].1.headers.get("dlq_reason"),
        Some("1/1 fan-out sub-elements dlq'd: bad sub")
    );
}

// Node calls `outputs.produce` synchronously, in item order, inside `next()`.
#[test]
fn dlq_produces_follow_item_order_on_a_multi_thread_runtime() {
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .build()
        .unwrap();
    for _ in 0..50 {
        let order = rt
            .block_on(async {
                tokio::spawn(async {
                    let outputs = MemoryOutputs::new();
                    let scheduler = PromiseScheduler::new();
                    let pipeline = new_chunk_pipeline::<i64, MsgCtx>()
                        .pipe_chunk(chunk_step("v", |v: Vec<i64>| async move {
                            Ok(v.into_iter().map(|_| dlq::<i64>("x", None)).collect())
                        }))
                        .message_aware(|b| b)
                        .handle_results(PipelineConfig {
                            outputs: Arc::new(outputs.clone()),
                            scheduler: Arc::new(scheduler.clone()),
                            reject_on_dlq_failure: false,
                        })
                        .handle_side_effects(Arc::new(scheduler), AWAIT)
                        .build();
                    pipeline.feed(
                        (0..8)
                            .map(|i| {
                                let mut m = test_message(Some(b"k"));
                                m.offset = i;
                                create_ok_context(i, MsgCtx { message: m })
                            })
                            .collect(),
                    );
                    pipeline.next().await.unwrap();
                    outputs
                        .produced_to(DLQ_OUTPUT)
                        .iter()
                        .map(|m| m.headers.get("dlq_offset").unwrap().parse::<i64>().unwrap())
                        .collect::<Vec<_>>()
                })
                .await
            })
            .unwrap();
        assert_eq!(order, (0..8).collect::<Vec<_>>());
    }
}

// Node starts the redirect produce synchronously, so it is called when next() resolves.
#[tokio::test]
async fn redirect_without_await_ack_has_called_produce_when_next_returns() {
    let outputs = MockOutputs::default();
    outputs.close_gate();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<i64, MsgCtx>()
        .pipe_chunk(chunk_step("r", |v: Vec<i64>| async move {
            Ok(v.into_iter()
                .map(|_| redirect_with::<i64>("o", "overflow", true, false))
                .collect())
        }))
        .message_aware(|b| b)
        .handle_results(PipelineConfig {
            outputs: Arc::new(outputs.clone()),
            scheduler: Arc::new(scheduler.clone()),
            reject_on_dlq_failure: false,
        })
        .handle_side_effects(Arc::new(scheduler), AWAIT)
        .build();
    pipeline.feed(vec![create_ok_context(
        1,
        MsgCtx {
            message: test_message(None),
        },
    )]);
    pipeline.next().await.unwrap();
    assert_eq!(outputs.calls().len(), 1);
}

// Node has no cancellation, so a batch always comes back, even after a dropped `next()`.
#[tokio::test(start_paused = true)]
async fn dropped_batching_next_does_not_lose_the_batch() {
    let after_runs = Arc::new(AtomicU32::new(0));
    let runs = after_runs.clone();
    let pipeline = new_batching_pipeline::<i64, _, (), (), (), ()>(
        |b| b.pipe(ingestion_framework::before_batch_step("before", |_| ())),
        |b| b,
        move |b| {
            let runs = runs.clone();
            b.pipe(step(
                "slowAfter",
                move |input: ingestion_framework::AfterBatchInput<_, (), ()>| {
                    runs.fetch_add(1, Ordering::SeqCst);
                    async move {
                        tokio::time::sleep(Duration::from_millis(100)).await;
                        Ok(ok(input))
                    }
                },
            ))
        },
        BatchingPipelineOptions {
            concurrent_batches: 1,
        },
    );
    pipeline.feed(items([1, 2]), (), None).await.unwrap();
    let _ = tokio::time::timeout(Duration::from_millis(10), pipeline.next()).await;
    let batch = pipeline.next().await.unwrap().expect("batch was lost");
    assert_eq!(batch.elements.len(), 2);
    assert_eq!(after_runs.load(Ordering::SeqCst), 1, "afterBatch ran twice");
    assert!(pipeline.next().await.unwrap().is_none());
}

#[tokio::test]
async fn scheduler_releases_settled_side_effects() {
    let scheduler = PromiseScheduler::new();
    for _ in 0..1000 {
        scheduler.schedule(SideEffect::spawn(async {
            tokio::task::yield_now().await;
            Ok(())
        }));
    }
    tokio::time::sleep(Duration::from_millis(20)).await;
    assert_eq!(scheduler.pending_count(), 0);
}

// Node's retryIfRetriable with tries: 0 never calls fn and throws.
#[tokio::test]
async fn retry_with_zero_tries_never_calls_the_step() {
    let calls = Arc::new(AtomicU32::new(0));
    let c = calls.clone();
    let p = new_pipeline::<i64, ()>()
        .pipe_with_retry(
            step("s", move |v: i64| {
                c.fetch_add(1, Ordering::SeqCst);
                async move { Ok(ok(v)) }
            }),
            RetryOptions {
                tries: Some(0),
                ..Default::default()
            },
        )
        .build();
    let r = p.process(create_ok_context(1, ())).await;
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(r.is_err());
}

// Node reads only error.isRetriable; a wrapper error without the flag is retried.
#[tokio::test(start_paused = true)]
async fn wrapped_non_retriable_error_is_retried_like_node() {
    let calls = Arc::new(AtomicU32::new(0));
    let c = calls.clone();
    let p = new_pipeline::<i64, ()>()
        .pipe_with_retry(
            step("s", move |_v: i64| {
                c.fetch_add(1, Ordering::SeqCst);
                async move {
                    Err::<ingestion_framework::PipelineResult<i64>, _>(
                        PipelineError::non_retriable("inner").context("outer"),
                    )
                }
            }),
            RetryOptions::default(),
        )
        .build();
    let _ = p.process(create_ok_context(1, ())).await;
    assert_eq!(calls.load(Ordering::SeqCst), 3);
}

// A Node fan-in throw rejects next() and poisons the stage without crashing the process.
#[tokio::test]
async fn fan_in_panic_rejects_next_and_keeps_rejecting() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .fan_out("split", |n: &i64| vec![*n])
        .via(|b| b)
        .fan_in("explode", |_o: i64, _s: Vec<i64>| -> i64 {
            panic!("fan-in bug")
        })
        .build();
    pipeline.feed(items([1]));
    for _ in 0..2 {
        let outcome = std::panic::AssertUnwindSafe(pipeline.next())
            .catch_unwind()
            .await;
        let error = outcome.expect("next() must not panic").unwrap_err();
        assert!(error.to_string().contains("fan-in bug"), "{error}");
    }
}

// `pLimit(0)` throws when the Node stage is built.
#[test]
#[should_panic(expected = "from 1 and up")]
fn zero_max_concurrency_fails_like_p_limit() {
    let _ = new_chunk_pipeline::<i64, ()>().concurrently(
        |b| b.pipe(step("s", |v: i64| async move { Ok(ok(v)) })),
        Some(0),
    );
}

// A quadratic start makes 4x the distinct keys cost 16x the time.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn grouping_start_scales_linearly_in_distinct_keys() {
    async fn run(n: i64) -> Duration {
        let pipeline = new_chunk_pipeline::<i64, ()>()
            .concurrently_per_group(
                |v: &i64| *v,
                |g| g.sequentially(|b| b.pipe(step("s", |v: i64| async move { Ok(ok(v)) }))),
                None,
            )
            .build();
        pipeline.feed(items(0..n));
        let t = Instant::now();
        common::consume_all(pipeline.as_ref()).await;
        t.elapsed()
    }
    // Warm the runtime and allocator first, so the small run is not inflated.
    run(5_000).await;
    let small = run(10_000).await;
    let big = run(40_000).await;
    assert!(
        big < small * 8,
        "4x keys took {:.1}x ({small:?} vs {big:?})",
        big.as_secs_f64() / small.as_secs_f64()
    );
}

// Node keeps a promise in the scheduler until it settles.
#[tokio::test]
async fn scheduler_keeps_in_flight_side_effects_for_every_waiter() {
    let scheduler = PromiseScheduler::new();
    let (release, gate) = tokio::sync::oneshot::channel::<()>();
    scheduler.schedule(SideEffect::spawn(async move {
        let _ = gate.await;
        Err(anyhow::anyhow!("produce failed"))
    }));
    let mut cancelled = Box::pin(scheduler.wait_for_all());
    assert!(futures::poll!(cancelled.as_mut()).is_pending());
    let mut overlapping = Box::pin(scheduler.wait_for_all());
    assert!(futures::poll!(overlapping.as_mut()).is_pending());
    drop(cancelled);
    release.send(()).unwrap();
    let error = overlapping.await.unwrap_err();
    assert!(error.to_string().contains("produce failed"), "{error}");
    assert!(scheduler.wait_for_all().await.is_ok());
}

// A Node fan-in throw leaves the parents completed before it in readyResults.
#[tokio::test]
async fn fan_in_panic_keeps_the_parents_completed_before_it() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .fan_out("split", |n: &i64| vec![*n])
        .via(|b| b)
        .fan_in("explode_on_2", |o: i64, _s: Vec<i64>| -> i64 {
            assert!(o != 2, "fan-in bug");
            o
        })
        .build();
    pipeline.feed(items([1, 2]));
    let first = std::panic::AssertUnwindSafe(pipeline.next())
        .catch_unwind()
        .await
        .expect("next() must not panic");
    assert!(first.is_err());
    let kept = pipeline.next().await.unwrap().expect("completed parent");
    let values: Vec<_> = kept
        .into_iter()
        .filter_map(|r| r.result.into_value())
        .collect();
    assert_eq!(values, vec![1]);
    assert!(pipeline.next().await.is_err());
}

// A Node group processor that throws before it returns its promise rejects that group.
#[tokio::test]
async fn group_processor_panic_before_its_future_fails_next() {
    let processor: ingestion_framework::grouping::GroupChunkProcessor<i64, i64, ()> =
        Arc::new(|_items| panic!("processor bug"));
    let pipeline = ingestion_framework::grouping::ConcurrentlyGroupingChunkPipeline::new(
        Arc::new(|v: &i64| *v),
        processor,
        new_chunk_pipeline::<i64, ()>().build(),
        None,
    );
    pipeline.feed(items([1]));
    let outcome = tokio::time::timeout(Duration::from_secs(5), pipeline.next())
        .await
        .expect("next() must not wait forever");
    let error = outcome.unwrap_err();
    assert!(error.to_string().contains("processor bug"), "{error}");
}

// p-limit does not hold a slot for a caller that is gone.
#[tokio::test]
async fn limiter_releases_the_slot_of_a_dropped_acquire() {
    let limiter = ingestion_framework::sync::FifoLimiter::new(1);
    drop(limiter.acquire());
    let held = tokio::time::timeout(Duration::from_secs(5), limiter.acquire())
        .await
        .expect("the slot of the dropped acquire was released");
    // This waiter gets the slot when `held` drops, and is gone before it reads it.
    let queued = limiter.acquire();
    drop(held);
    drop(queued);
    tokio::time::timeout(Duration::from_secs(5), limiter.acquire())
        .await
        .expect("the slot was released");
}

// Node's setTimeout uses 1 ms for a negative, NaN or too-large delay.
#[tokio::test(start_paused = true)]
async fn retry_with_out_of_range_sleep_options_does_not_panic() {
    let cases = [
        (Some(-1.0), Some(0.0)),
        (Some(f64::NAN), None),
        (Some(f64::INFINITY), Some(0.0)),
        (None, Some(3.0)),
        (Some(f64::MAX), Some(-1.0)),
    ];
    for (backoff_factor, jitter) in cases {
        let options = RetryOptions {
            tries: Some(4),
            sleep_ms: Some(100),
            max_sleep_ms: Some(u64::MAX),
            backoff_factor,
            jitter,
            ..RetryOptions::default()
        };
        let (result, attempts) = ingestion_framework::retry::retry_if_retriable(
            || async { Err::<(), _>(anyhow::anyhow!("retriable")) },
            &options,
        )
        .await;
        assert!(result.is_err());
        assert_eq!(attempts, 4, "{backoff_factor:?} {jitter:?}");
    }
}
