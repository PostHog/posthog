//! Mirrors `docs/18-batch-budgets.test.ts`. `tokio::time::advance` inside a step replaces
//! the synchronous `jest.advanceTimersByTime`.

mod common;

use std::time::Duration;

use common::{items, shared};
use ingestion_framework::{
    before_batch_step, chunk_step, new_batching_pipeline, ok, passthrough_after_batch_step, step,
    BatchBudget, BatchingPipelineOptions, ChunkResults, NonOk, Outcome, WithBatch,
};
use tokio::time::Instant;

#[derive(Debug, Clone, Copy)]
struct Event {
    key: &'static str,
    seq: i64,
}

type V = WithBatch<Event, ()>;

fn kinds<C>(results: &ChunkResults<V, C>) -> Vec<&'static str> {
    results
        .iter()
        .map(|r| match &r.result {
            Outcome::Ok(_) => "ok",
            Outcome::NonOk(NonOk::Timeout { .. }) => "timeout",
            _ => "other",
        })
        .collect()
}

fn reasons<C>(results: &ChunkResults<V, C>) -> Vec<Option<String>> {
    results
        .iter()
        .map(|r| match &r.result {
            Outcome::NonOk(NonOk::Timeout { reason }) => Some(reason.clone()),
            _ => None,
        })
        .collect()
}

fn events(
    key: &'static str,
    seqs: impl IntoIterator<Item = i64>,
) -> Vec<ingestion_framework::OkResultWithContext<Event, ()>> {
    items(seqs.into_iter().map(|seq| Event { key, seq }))
}

async fn advance_1s() {
    tokio::time::advance(Duration::from_millis(1000)).await;
}

fn one() -> BatchingPipelineOptions {
    BatchingPipelineOptions {
        concurrent_batches: 1,
    }
}

#[tokio::test(start_paused = true)]
async fn stops_each_element_at_its_next_step_once_the_budget_is_exhausted() {
    let ran = shared(Vec::<String>::new());
    let (r1, r2) = (ran.clone(), ran.clone());
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        move |b| {
            b.sequentially(move |s| {
                s.pipe(step("enrichStep", move |e: V| {
                    r1.lock().unwrap().push(format!("enrich-{}", e.seq));
                    async move {
                        if e.seq == 2 {
                            advance_1s().await;
                        }
                        Ok(ok(e))
                    }
                }))
                .pipe(step("emitStep", move |e: V| {
                    r2.lock().unwrap().push(format!("emit-{}", e.seq));
                    async move { Ok(ok(e)) }
                }))
            })
        },
        |b| b.pipe(passthrough_after_batch_step("passThroughAfter")),
        one(),
    );
    pipeline
        .feed(
            events("a", [1, 2, 3]),
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() + Duration::from_millis(1000),
            )),
        )
        .await
        .unwrap();
    let batch = pipeline.next().await.unwrap().unwrap();
    assert_eq!(*ran.lock().unwrap(), vec!["enrich-1", "emit-1", "enrich-2"]);
    assert_eq!(kinds(&batch.elements), ["ok", "timeout", "timeout"]);
    assert_eq!(
        reasons(&batch.elements),
        [
            None,
            Some("budget exceeded before emitStep".into()),
            Some("budget exceeded before enrichStep".into())
        ]
    );
}

#[tokio::test(start_paused = true)]
async fn runs_a_chunk_step_on_the_elements_whose_batch_still_has_time() {
    let chunked = shared(Vec::<Vec<i64>>::new());
    let c = chunked.clone();
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        move |b| {
            b.pipe_chunk(chunk_step("writeChunk", move |events: Vec<V>| {
                c.lock()
                    .unwrap()
                    .push(events.iter().map(|e| e.seq).collect());
                async move { Ok(events.into_iter().map(ok).collect()) }
            }))
        },
        |b| b.pipe(passthrough_after_batch_step("passThroughAfter")),
        BatchingPipelineOptions {
            concurrent_batches: 2,
        },
    );
    pipeline
        .feed(
            events("a", [1]),
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() - Duration::from_millis(1),
            )),
        )
        .await
        .unwrap();
    pipeline
        .feed(
            events("b", [2]),
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() + Duration::from_secs(60),
            )),
        )
        .await
        .unwrap();
    let spent = pipeline.next().await.unwrap().unwrap();
    let fresh = pipeline.next().await.unwrap().unwrap();
    assert_eq!(*chunked.lock().unwrap(), vec![vec![2]]);
    assert_eq!(kinds(&spent.elements), ["timeout"]);
    assert_eq!(
        reasons(&spent.elements),
        [Some("budget exceeded before writeChunk".into())]
    );
    assert_eq!(kinds(&fresh.elements), ["ok"]);
}

#[tokio::test(start_paused = true)]
async fn runs_an_element_past_the_barrier_to_completion_after_the_budget_expires() {
    let ran = shared(Vec::<String>::new());
    let (r1, r2, r3) = (ran.clone(), ran.clone(), ran.clone());
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        move |b| {
            b.sequentially(move |s| {
                s.pipe(step("prepareEvent", move |e: V| {
                    r1.lock().unwrap().push(format!("prepare-{}", e.seq));
                    async move { Ok(ok(e)) }
                }))
                .timeout_barrier()
                .pipe(step("writePerson", move |e: V| {
                    r2.lock().unwrap().push(format!("write-{}", e.seq));
                    async move {
                        advance_1s().await;
                        Ok(ok(e))
                    }
                }))
                .pipe(step("emitEvent", move |e: V| {
                    r3.lock().unwrap().push(format!("emit-{}", e.seq));
                    async move { Ok(ok(e)) }
                }))
            })
        },
        |b| b.pipe(passthrough_after_batch_step("passThroughAfter")),
        one(),
    );
    pipeline
        .feed(
            events("a", [1, 2]),
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() + Duration::from_millis(1000),
            )),
        )
        .await
        .unwrap();
    let batch = pipeline.next().await.unwrap().unwrap();
    assert_eq!(*ran.lock().unwrap(), vec!["prepare-1", "write-1", "emit-1"]);
    assert_eq!(kinds(&batch.elements), ["ok", "timeout"]);
    assert_eq!(
        reasons(&batch.elements),
        [None, Some("budget exceeded before prepareEvent".into())]
    );
}

#[tokio::test(start_paused = true)]
async fn returns_one_result_per_message_and_still_runs_after_batch_when_everything_times_out() {
    let flushed = shared(0usize);
    let f = flushed.clone();
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        |b| b.sequentially(|s| s.pipe(step("emitStep", |e: V| async move { Ok(ok(e)) }))),
        move |b| {
            b.pipe(step(
                "flushBatch",
                move |input: ingestion_framework::AfterBatchInput<V, (), ()>| {
                    *f.lock().unwrap() = input.elements.len();
                    async move { Ok(ok(input)) }
                },
            ))
        },
        one(),
    );
    let mut fed = events("a", [1, 2]);
    fed.extend(events("b", [1]));
    pipeline
        .feed(
            fed,
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() - Duration::from_millis(1),
            )),
        )
        .await
        .unwrap();
    let batch = pipeline.next().await.unwrap().unwrap();
    assert_eq!(batch.elements.len(), 3);
    assert_eq!(kinds(&batch.elements), ["timeout", "timeout", "timeout"]);
    assert_eq!(*flushed.lock().unwrap(), 3);
}

#[tokio::test(start_paused = true)]
async fn completes_a_prefix_of_each_groups_feed_order() {
    let processed = shared(Vec::<i64>::new());
    let p = processed.clone();
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        move |b| {
            b.concurrently_per_group(
                |e: &V| e.key,
                move |g| {
                    g.sequentially(move |s| {
                        s.pipe(step("processStep", move |e: V| {
                            let count = {
                                let mut p = p.lock().unwrap();
                                p.push(e.seq);
                                p.len()
                            };
                            async move {
                                if count == 2 {
                                    advance_1s().await;
                                }
                                Ok(ok(e))
                            }
                        }))
                    })
                },
                None,
            )
        },
        |b| b.pipe(passthrough_after_batch_step("passThroughAfter")),
        one(),
    );
    pipeline
        .feed(
            events("a", [1, 2, 3, 4]),
            (),
            Some(BatchBudget::soft_deadline(
                Instant::now() + Duration::from_millis(1000),
            )),
        )
        .await
        .unwrap();
    let batch = pipeline.next().await.unwrap().unwrap();
    assert_eq!(*processed.lock().unwrap(), vec![1, 2]);
    assert_eq!(kinds(&batch.elements), ["ok", "ok", "timeout", "timeout"]);
}

#[tokio::test(start_paused = true)]
async fn never_cancels_anything_under_the_default_unlimited_budget() {
    let pipeline = new_batching_pipeline::<Event, V, (), (), (), ()>(
        |b| b.pipe(before_batch_step("passThroughBefore", |_| ())),
        |b| b.sequentially(|s| s.pipe(step("emitStep", |e: V| async move { Ok(ok(e)) }))),
        |b| b.pipe(passthrough_after_batch_step("passThroughAfter")),
        one(),
    );
    pipeline.feed(events("a", [1]), (), None).await.unwrap();
    let batch = pipeline.next().await.unwrap().unwrap();
    assert_eq!(kinds(&batch.elements), ["ok"]);
}
