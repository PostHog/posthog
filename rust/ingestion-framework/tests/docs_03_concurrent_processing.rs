mod common;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use common::{consume_all_within, items, shared, sleep_ms};
use ingestion_framework::{new_chunk_pipeline, ok, step};

#[tokio::test(start_paused = true)]
async fn concurrently_processes_items_in_parallel() {
    let processed = shared(Vec::<i64>::new());
    let p = processed.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            move |b| {
                b.pipe(step("slowStep", move |n: i64| {
                    let p = p.clone();
                    async move {
                        sleep_ms(100).await;
                        p.lock().unwrap().push(n);
                        Ok(ok(n * 2))
                    }
                }))
            },
            None,
        )
        .build();
    pipeline.feed(items([1, 2, 3]));
    let started = tokio::time::Instant::now();
    let values = consume_all_within(pipeline.as_ref(), 100).await;
    assert_eq!(processed.lock().unwrap().len(), 3);
    assert_eq!(values, [2, 4, 6]);
    // In parallel: the three 100 ms steps take 100 ms in total, not 300 ms.
    assert!(started.elapsed().as_millis() < 200);
}

#[tokio::test(start_paused = true)]
async fn items_are_returned_one_by_one_as_they_complete() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            |b| {
                b.pipe(step("slowStep", |n: i64| async move {
                    sleep_ms(10).await;
                    Ok(ok(n * 10))
                }))
            },
            None,
        )
        .build();
    pipeline.feed(items([1, 2, 3]));
    let chunks = common::collect_chunks(pipeline.as_ref()).await;
    assert_eq!(chunks, vec![vec![10], vec![20], vec![30]]);
}

#[tokio::test(start_paused = true)]
async fn result_ordering_matches_input_order() {
    let order = shared(Vec::<i64>::new());
    let o = order.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            move |b| {
                b.pipe(step("variableDelayStep", move |n: i64| {
                    let o = o.clone();
                    async move {
                        sleep_ms(((4 - n) * 10) as u64).await;
                        o.lock().unwrap().push(n);
                        Ok(ok(n * 10))
                    }
                }))
            },
            None,
        )
        .build();
    pipeline.feed(items([1, 2, 3]));
    let values = consume_all_within(pipeline.as_ref(), 30).await;
    assert_eq!(*order.lock().unwrap(), vec![3, 2, 1]);
    assert_eq!(values, [10, 20, 30]);
}

#[tokio::test(start_paused = true)]
async fn max_concurrency_caps_how_many_items_run_at_once() {
    let running = Arc::new(AtomicUsize::new(0));
    let peak = Arc::new(AtomicUsize::new(0));
    let (r, p) = (running.clone(), peak.clone());
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .concurrently(
            move |b| {
                b.pipe(step("trackingStep", move |n: i64| {
                    let (r, p) = (r.clone(), p.clone());
                    async move {
                        let now = r.fetch_add(1, Ordering::SeqCst) + 1;
                        p.fetch_max(now, Ordering::SeqCst);
                        sleep_ms(100).await;
                        r.fetch_sub(1, Ordering::SeqCst);
                        Ok(ok(n * 2))
                    }
                }))
            },
            Some(2),
        )
        .build();
    pipeline.feed(items([1, 2, 3, 4, 5]));
    let values = consume_all_within(pipeline.as_ref(), 300).await;
    assert_eq!(peak.load(Ordering::SeqCst), 2);
    assert_eq!(values, [2, 4, 6, 8, 10]);
}
