//! Mirrors `per-element-step.test.ts`.

use std::sync::{Arc, Mutex};

use ingestion_framework::{ok, per_element, step, PipelineResult};

#[derive(Default)]
struct Track {
    running: usize,
    peak: usize,
    started: Vec<i64>,
}

#[tokio::test]
async fn keeps_input_order_and_never_runs_more_than_max_concurrency_steps_at_once() {
    let track = Arc::new(Mutex::new(Track::default()));
    let t = track.clone();
    let chunk = per_element(
        step("slowStep", move |value: i64| {
            let t = t.clone();
            async move {
                {
                    let mut t = t.lock().unwrap();
                    t.started.push(value);
                    t.running += 1;
                    t.peak = t.peak.max(t.running);
                }
                // Later values wait fewer ticks and finish first, so output order cannot
                // follow completion order.
                for _ in 0..(8 - value) {
                    tokio::task::yield_now().await;
                }
                t.lock().unwrap().running -= 1;
                Ok(ok(value * 10))
            }
        }),
        Some(3),
    );

    let results: Vec<PipelineResult<i64>> = chunk.call(vec![1, 2, 3, 4, 5, 6, 7]).await.unwrap();

    let values: Vec<i64> = results
        .into_iter()
        .map(|r| r.outcome.into_value().unwrap())
        .collect();
    assert_eq!(values, [10, 20, 30, 40, 50, 60, 70]);
    let track = track.lock().unwrap();
    assert_eq!(track.peak, 3);
    assert_eq!(track.started, [1, 2, 3, 4, 5, 6, 7]);
    assert_eq!(chunk.name().as_ref(), "slowStep");
}
