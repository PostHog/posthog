mod common;

use common::{collect_chunks, consume_all, items, shared, sleep_ms};
use ingestion_framework::{new_chunk_pipeline, ok, step};

#[tokio::test(start_paused = true)]
async fn sequentially_processes_items_one_at_a_time() {
    let order = shared(Vec::<i64>::new());
    let o = order.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .sequentially(move |b| {
            b.pipe(step("orderTrackingStep", move |n: i64| {
                let o = o.clone();
                async move {
                    sleep_ms(10).await;
                    o.lock().unwrap().push(n);
                    Ok(ok(n))
                }
            }))
        })
        .build();
    pipeline.feed(items([1, 2, 3]));
    let started = tokio::time::Instant::now();
    let values = consume_all(pipeline.as_ref()).await;
    assert_eq!(*order.lock().unwrap(), vec![1, 2, 3]);
    assert_eq!(values, [1, 2, 3]);
    assert!(started.elapsed().as_millis() >= 30);
}

#[tokio::test(start_paused = true)]
async fn all_items_are_returned_together_after_sequential_processing() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .sequentially(|b| {
            b.pipe(step("slowStep", |n: i64| async move {
                sleep_ms(10).await;
                Ok(ok(n * 10))
            }))
        })
        .build();
    pipeline.feed(items([1, 2, 3]));
    assert_eq!(
        collect_chunks(pipeline.as_ref()).await,
        vec![vec![10, 20, 30]]
    );
}

#[tokio::test(start_paused = true)]
async fn result_ordering_matches_input_order() {
    let order = shared(Vec::<i64>::new());
    let o = order.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .sequentially(move |b| {
            b.pipe(step("trackingStep", move |n: i64| {
                let o = o.clone();
                async move {
                    sleep_ms(10).await;
                    o.lock().unwrap().push(n);
                    Ok(ok(n * 10))
                }
            }))
        })
        .build();
    pipeline.feed(items([3, 1, 2]));
    let values = consume_all(pipeline.as_ref()).await;
    assert_eq!(*order.lock().unwrap(), vec![3, 1, 2]);
    assert_eq!(values, [30, 10, 20]);
}
