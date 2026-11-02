//! Semantics the living docs do not pin down but the Node implementation guarantees.

mod common;

use std::sync::Arc;
use std::time::Duration;

use common::{items, shared, sleep_ms, test_message, MsgCtx};
use ingestion_framework::{
    chunk_step, create_ok_context, dlq, new_chunk_pipeline, ok, step, timeout, MemoryOutputs,
    PipelineConfig, PipelineResultType, PipelineWarning, PromiseScheduler,
    SideEffectHandlingConfig, DLQ_OUTPUT,
};
use tokio::time::Instant;

fn failing_on(n: i64) -> ingestion_framework::ProcessingStep<i64, i64> {
    step("maybeFails", move |v: i64| async move {
        sleep_ms(10 * v as u64).await;
        if v == n {
            anyhow::bail!("boom {v}");
        }
        Ok(ok(v))
    })
}

#[tokio::test(start_paused = true)]
async fn concurrent_poison_drains_in_flight_items_in_order_then_fails_for_good() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(|b| b.pipe(failing_on(2)), None)
        .build();
    pipeline.feed(items([1, 2, 3]));
    assert_eq!(pipeline.next().await.unwrap().unwrap()[0].value(), Some(&1));
    assert_eq!(pipeline.next().await.unwrap_err().to_string(), "boom 2");
    assert_eq!(pipeline.next().await.unwrap().unwrap()[0].value(), Some(&3));
    assert_eq!(pipeline.next().await.unwrap_err().to_string(), "boom 2");
    assert_eq!(pipeline.next().await.unwrap_err().to_string(), "boom 2");
}

#[tokio::test(start_paused = true)]
async fn concurrent_upstream_failure_poisons_the_stage() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("explodes", |_v: Vec<i64>| async move {
            Err::<Vec<ingestion_framework::PipelineResult<i64>>, _>(anyhow::anyhow!("upstream"))
        }))
        .concurrently(
            |b| b.pipe(step("id", |v: i64| async move { Ok(ok(v)) })),
            None,
        )
        .build();
    pipeline.feed(items([1]));
    assert_eq!(pipeline.next().await.unwrap_err().to_string(), "upstream");
    pipeline.feed(items([2]));
    // Poisoned: no new source pull, so the later feed never runs.
    assert_eq!(pipeline.next().await.unwrap_err().to_string(), "upstream");
}

#[tokio::test(start_paused = true)]
async fn concurrent_feed_while_parked_starts_new_input_without_waiting_for_the_head() {
    let starts = shared(Vec::<(i64, u128)>::new());
    let s = starts.clone();
    let origin = Instant::now();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            move |b| {
                b.pipe(step("slowHead", move |v: i64| {
                    s.lock().unwrap().push((v, origin.elapsed().as_millis()));
                    async move {
                        sleep_ms(if v == 1 { 100 } else { 1 }).await;
                        Ok(ok(v))
                    }
                }))
            },
            None,
        )
        .build();
    pipeline.feed(items([1]));
    let p = pipeline.clone();
    let consumer = tokio::spawn(async move { common::consume_all(p.as_ref()).await });
    sleep_ms(10).await;
    pipeline.feed(items([2]));
    let values = consumer.await.unwrap();
    assert_eq!(values, [1, 2]);
    let starts = starts.lock().unwrap().clone();
    assert_eq!(starts[1].0, 2);
    assert!(
        starts[1].1 < 100,
        "item 2 started at {}ms, behind the slow head",
        starts[1].1
    );
}

#[tokio::test(start_paused = true)]
async fn max_concurrency_admits_items_in_input_order() {
    let started = shared(Vec::<i64>::new());
    let s = started.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            move |b| {
                b.pipe(step("record", move |v: i64| {
                    s.lock().unwrap().push(v);
                    async move {
                        sleep_ms(5).await;
                        Ok(ok(v))
                    }
                }))
            },
            Some(1),
        )
        .build();
    pipeline.feed(items(1..=20));
    let values = common::consume_all(pipeline.as_ref()).await;
    assert_eq!(values, (1..=20).collect::<Vec<_>>());
    assert_eq!(*started.lock().unwrap(), (1..=20).collect::<Vec<_>>());
}

#[tokio::test(start_paused = true)]
async fn grouping_keeps_per_key_order_across_next_calls_and_feeds() {
    let seen = shared(Vec::<(&'static str, i64)>::new());
    let s = seen.clone();
    let pipeline = new_chunk_pipeline::<(&'static str, i64), ()>()
        .concurrently_per_group(
            |e: &(&'static str, i64)| e.0,
            move |g| {
                g.sequentially(move |b| {
                    b.pipe(step("record", move |e: (&'static str, i64)| {
                        let s = s.clone();
                        async move {
                            sleep_ms(if e.1 % 2 == 0 { 3 } else { 7 }).await;
                            s.lock().unwrap().push(e);
                            Ok(ok(e))
                        }
                    }))
                })
            },
            Some(2),
        )
        .build();
    pipeline.feed(items([("a", 1), ("b", 1), ("a", 2)]));
    let first = pipeline.next().await.unwrap();
    pipeline.feed(items([("a", 3), ("c", 1), ("b", 2), ("a", 4)]));
    let mut rest = common::consume_all(pipeline.as_ref()).await;
    rest.extend(
        first
            .unwrap()
            .into_iter()
            .filter_map(|r| r.result.into_value()),
    );
    assert_eq!(rest.len(), 7);
    let order_of = |key| {
        seen.lock()
            .unwrap()
            .iter()
            .filter(|e| e.0 == key)
            .map(|e| e.1)
            .collect::<Vec<_>>()
    };
    assert_eq!(order_of("a"), [1, 2, 3, 4]);
    assert_eq!(order_of("b"), [1, 2]);
}

#[tokio::test(start_paused = true)]
async fn grouping_failure_drains_completed_groups_then_fails_for_good() {
    let pipeline = new_chunk_pipeline::<(&'static str, i64), ()>()
        .concurrently_per_group(
            |e: &(&'static str, i64)| e.0,
            |g| {
                g.sequentially(|b| {
                    b.pipe(step("maybeFails", |e: (&'static str, i64)| async move {
                        if e.0 == "bad" {
                            sleep_ms(10).await;
                            anyhow::bail!("group failed");
                        }
                        sleep_ms(5).await;
                        Ok(ok(e))
                    }))
                })
            },
            None,
        )
        .build();
    // Only groups that completed before the failure drain ahead of it, as in Node.
    pipeline.feed(items([("bad", 1), ("good", 1)]));
    let good = pipeline.next().await.unwrap().unwrap();
    assert_eq!(good[0].value(), Some(&("good", 1)));
    assert_eq!(
        pipeline.next().await.unwrap_err().to_string(),
        "group failed"
    );
    assert_eq!(
        pipeline.next().await.unwrap_err().to_string(),
        "group failed"
    );
}

#[tokio::test]
async fn filter_map_emits_non_ok_passthroughs_before_sub_pipeline_results() {
    #[derive(Debug)]
    struct Ctx;
    let pipeline = new_chunk_pipeline::<i64, Ctx>()
        .pipe_chunk(chunk_step("split", |v: Vec<i64>| async move {
            Ok(v.into_iter()
                .map(|n| if n % 2 == 0 { dlq("even", None) } else { ok(n) })
                .collect())
        }))
        .filter_map(
            |el| el,
            |b| {
                b.pipe_chunk(chunk_step("double", |v: Vec<i64>| async move {
                    Ok(v.into_iter().map(|n| ok(n * 2)).collect())
                }))
            },
        )
        .build();
    pipeline.feed(vec![
        create_ok_context(1, Ctx),
        create_ok_context(2, Ctx),
        create_ok_context(3, Ctx),
    ]);
    let first = pipeline.next().await.unwrap().unwrap();
    assert_eq!(first.len(), 1);
    assert_eq!(first[0].result.result_type(), PipelineResultType::Dlq);
    let second = pipeline.next().await.unwrap().unwrap();
    assert_eq!(
        second
            .iter()
            .map(|r| *r.value().unwrap())
            .collect::<Vec<_>>(),
        [2, 6]
    );
    assert!(pipeline.next().await.unwrap().is_none());
}

#[tokio::test]
async fn failed_dlq_produce_rejects_the_side_effect_only_when_configured() {
    for reject in [false, true] {
        let outputs = MemoryOutputs::new();
        outputs.fail_output(DLQ_OUTPUT);
        let scheduler = PromiseScheduler::new();
        let pipeline = new_chunk_pipeline::<i64, MsgCtx>()
            .pipe_chunk(chunk_step("fail", |v: Vec<i64>| async move {
                Ok(v.into_iter().map(|_| dlq::<i64>("bad", None)).collect())
            }))
            .message_aware(|b| b)
            .handle_results(PipelineConfig {
                outputs: Arc::new(outputs.clone()),
                scheduler: Arc::new(scheduler.clone()),
                reject_on_dlq_failure: reject,
            })
            .handle_side_effects(
                Arc::new(scheduler.clone()),
                SideEffectHandlingConfig {
                    await_side_effects: false,
                },
            )
            .build();
        pipeline.feed(vec![create_ok_context(
            1,
            MsgCtx {
                message: test_message(None),
            },
        )]);
        pipeline.next().await.unwrap();
        assert_eq!(scheduler.wait_for_all().await.is_err(), reject);
    }
}

#[tokio::test]
async fn dlq_without_error_uses_the_reason_and_copies_source_headers() {
    let outputs = MemoryOutputs::new();
    let scheduler = PromiseScheduler::new();
    let pipeline = new_chunk_pipeline::<i64, MsgCtx>()
        .pipe_chunk(chunk_step("rejectStep", |v: Vec<i64>| async move {
            Ok(v.into_iter()
                .map(|_| dlq::<i64>("plain reason", None))
                .collect())
        }))
        .message_aware(|b| b)
        .handle_results(PipelineConfig {
            outputs: Arc::new(outputs.clone()),
            scheduler: Arc::new(scheduler.clone()),
            reject_on_dlq_failure: false,
        })
        .handle_side_effects(
            Arc::new(scheduler.clone()),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();
    let mut message = test_message(Some(b"k"));
    message.topic = "events".into();
    message.partition = 3;
    message.offset = 42;
    message.headers = vec![
        ("token".into(), Some(b"phc_x".to_vec())),
        ("dlq_step".into(), Some(b"stale".to_vec())),
    ];
    pipeline.feed(vec![create_ok_context(1, MsgCtx { message })]);
    pipeline.next().await.unwrap();
    let produced = outputs.produced_to(DLQ_OUTPUT);
    let h = &produced[0].headers;
    assert_eq!(h.get("token"), Some("phc_x"));
    assert_eq!(h.get("dlq_reason"), Some("plain reason"));
    // A source header with the same name keeps its position and takes the new value, as a JS object spread does.
    assert_eq!(h.0[1], ("dlq_step".to_string(), "rejectStep".to_string()));
    assert_eq!(h.get("dlq_topic"), Some("events"));
    assert_eq!(h.get("dlq_partition"), Some("3"));
    assert_eq!(h.get("dlq_offset"), Some("42"));
}

#[tokio::test]
async fn warnings_on_a_timed_out_result_are_dropped_not_emitted() {
    let outputs = MemoryOutputs::new();
    let pipeline = new_chunk_pipeline::<i64, common::TeamCtx>()
        .pipe_chunk(chunk_step("warnThenTimeout", |v: Vec<i64>| async move {
            Ok(v.into_iter()
                .map(|n| {
                    let r = if n == 1 { timeout::<i64>("cut") } else { ok(n) };
                    r.with_warning(PipelineWarning::new(
                        "client_ingestion_warning",
                        serde_json::json!({}),
                    ))
                })
                .collect())
        }))
        .team_aware(|b| b)
        .handle_ingestion_warnings(Arc::new(
            ingestion_framework::warning_handling::OutputsWarningEmitter {
                outputs: Arc::new(outputs.clone()),
            },
        ))
        .handle_side_effects(
            Arc::new(PromiseScheduler::new()),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();
    pipeline.feed(vec![
        create_ok_context(1, common::TeamCtx { team_id: 1 }),
        create_ok_context(2, common::TeamCtx { team_id: 1 }),
    ]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert!(results.iter().all(|r| r.context.warnings.is_empty()));
    assert_eq!(outputs.produced().len(), 1);
}

#[tokio::test]
async fn fan_out_dlq_sub_result_fails_the_parent_with_an_aggregated_reason() {
    let pipeline = new_chunk_pipeline::<Vec<i64>, ()>()
        .fan_out("split", |v: &Vec<i64>| v.clone())
        .via(|sub| {
            sub.sequentially(|b| {
                b.pipe(step("check", |n: i64| async move {
                    Ok(if n < 0 { dlq("negative", None) } else { ok(n) })
                }))
            })
        })
        .fan_in("sum", |_v: Vec<i64>, parts: Vec<i64>| {
            parts.iter().sum::<i64>()
        })
        .build();
    pipeline.feed(items([vec![1, -1, -2]]));
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(
        results[0].result.reason(),
        Some("2/3 fan-out sub-elements dlq'd: negative")
    );
    assert_eq!(results[0].context.last_step(), Some("check"));
}

#[tokio::test]
async fn budget_flag_stays_set_after_expiry() {
    let budget =
        ingestion_framework::BatchBudget::soft_deadline(Instant::now() - Duration::from_millis(1));
    assert!(budget.exhausted());
    assert!(ingestion_framework::BatchBudget::unlimited().is_unlimited());
    assert!(!ingestion_framework::BatchBudget::unlimited().exhausted());
    assert_eq!(
        ingestion_framework::budget::budget_deadline(Instant::now(), 0),
        None
    );
    assert_eq!(
        ingestion_framework::budget::budget_deadline(Instant::now(), 1 << 31),
        None
    );
}

#[test]
fn compact_offset_ranges_matches_node() {
    use ingestion_framework::helpers::compact_offset_ranges;
    assert_eq!(compact_offset_ranges(&[1, 2, 3, 7, 10, 9]), "1-3,7,9-10");
    assert_eq!(compact_offset_ranges(&[5, 5, 5]), "5");
    assert_eq!(compact_offset_ranges(&[]), "");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn batching_with_concurrent_feeds_on_a_multi_thread_runtime_completes_every_batch() {
    use ingestion_framework::{
        before_batch_step, new_batching_pipeline, passthrough_after_batch_step,
        BatchingPipelineOptions, WithBatch,
    };
    let pipeline = Arc::new(new_batching_pipeline::<
        i64,
        WithBatch<i64, u64>,
        (),
        (),
        u64,
        u64,
    >(
        |b| b.pipe(before_batch_step("before", |id| id)),
        |b| {
            b.concurrently_per_group(
                |v: &WithBatch<i64, u64>| v.value % 7,
                |g| {
                    g.sequentially(|s| {
                        s.pipe(step("work", |v: WithBatch<i64, u64>| async move {
                            tokio::task::yield_now().await;
                            Ok(ok(v))
                        }))
                    })
                },
                Some(3),
            )
        },
        |b| b.pipe(passthrough_after_batch_step("after")),
        BatchingPipelineOptions {
            concurrent_batches: 8,
        },
    ));
    let mut feeders = Vec::new();
    for batch in 0..8u64 {
        let p = pipeline.clone();
        feeders.push(tokio::spawn(async move {
            loop {
                let r = p
                    .feed(items((0..50).map(|i| i + batch as i64 * 1000)), batch, None)
                    .await
                    .unwrap();
                if r.is_ok() {
                    break;
                }
                tokio::task::yield_now().await;
            }
        }));
    }
    for f in feeders {
        f.await.unwrap();
    }
    let mut seen = Vec::new();
    while let Some(done) = pipeline.next().await.unwrap() {
        assert_eq!(done.elements.len(), 50);
        assert_eq!(
            *done.batch_context, done.batch_id,
            "the batch context is the one built for this batch"
        );
        let values: Vec<i64> = done
            .elements
            .iter()
            .map(|e| e.value().unwrap().value)
            .collect();
        assert_eq!(
            values,
            (0..50)
                .map(|i| i + done.feed_context as i64 * 1000)
                .collect::<Vec<_>>(),
            "feed order kept in a batch"
        );
        seen.push(done.feed_context);
    }
    seen.sort();
    assert_eq!(seen, (0..8).collect::<Vec<_>>());
}
