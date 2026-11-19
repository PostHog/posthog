mod common;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use common::items;
use ingestion_framework::{drop, new_chunk_pipeline, ok, step, PipelineError, RetryOptions};

#[tokio::test]
async fn uploads_attachments_concurrently_and_folds_the_results_back_in() {
    let in_flight = Arc::new(AtomicUsize::new(0));
    let high_water = Arc::new(AtomicUsize::new(0));
    let (f, h) = (in_flight.clone(), high_water.clone());
    let pipeline = new_chunk_pipeline::<(&'static str, Vec<&'static str>), ()>()
        .fan_out(
            "attachmentsFanOut",
            |e: &(&'static str, Vec<&'static str>)| {
                e.1.iter().map(|a| (e.0, *a)).collect::<Vec<_>>()
            },
        )
        .via(move |sub| {
            sub.concurrently(
                move |b| {
                    b.pipe(step(
                        "uploadStep",
                        move |u: (&'static str, &'static str)| {
                            let (f, h) = (f.clone(), h.clone());
                            async move {
                                let now = f.fetch_add(1, Ordering::SeqCst) + 1;
                                h.fetch_max(now, Ordering::SeqCst);
                                tokio::task::yield_now().await;
                                f.fetch_sub(1, Ordering::SeqCst);
                                Ok(ok(format!("s3://bucket/{}", u.1)))
                            }
                        },
                    ))
                },
                Some(2),
            )
        })
        .fan_in(
            "collectUrlsFanIn",
            |e: (&'static str, Vec<&'static str>), urls: Vec<String>| {
                let mut urls = urls;
                urls.sort();
                (e.0, urls)
            },
        )
        .build();
    pipeline.feed(items([
        ("e1", vec!["a.png", "b.png", "c.png"]),
        ("e2", vec![]),
    ]));
    let mut collected = common::consume_all(pipeline.as_ref()).await;
    collected.sort();
    assert_eq!(
        collected,
        vec![
            (
                "e1",
                vec![
                    "s3://bucket/a.png".to_string(),
                    "s3://bucket/b.png".into(),
                    "s3://bucket/c.png".into()
                ]
            ),
            ("e2", vec![]),
        ]
    );
    assert!(high_water.load(Ordering::SeqCst) <= 2);
}

#[tokio::test]
async fn retries_a_transient_sub_step_failure_without_disturbing_the_parent() {
    let attempts = Arc::new(AtomicUsize::new(0));
    let a = attempts.clone();
    let pipeline = new_chunk_pipeline::<(&'static str, Vec<i64>), ()>()
        .fan_out("partsFanOut", |j: &(&'static str, Vec<i64>)| j.1.clone())
        .via(move |sub| {
            sub.concurrently(
                move |b| {
                    b.pipe_with_retry(
                        step("flakyStep", move |part: i64| {
                            let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                            async move {
                                if n == 1 {
                                    return Err(PipelineError::retriable("transient"));
                                }
                                Ok(ok(part))
                            }
                        }),
                        RetryOptions {
                            tries: Some(3),
                            sleep_ms: Some(1),
                            ..Default::default()
                        },
                    )
                },
                None,
            )
        })
        .fan_in(
            "sumFanIn",
            |j: (&'static str, Vec<i64>), parts: Vec<i64>| (j.0, parts.iter().sum::<i64>()),
        )
        .build();
    pipeline.feed(items([("job", vec![7])]));
    let mut results = Vec::new();
    while let Some(chunk) = pipeline.next().await.unwrap() {
        results.extend(chunk);
    }
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].value(), Some(&("job", 7)));
    assert_eq!(attempts.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn drops_a_sub_element_without_failing_its_parent() {
    let pipeline = new_chunk_pipeline::<(&'static str, Vec<i64>), ()>()
        .fan_out("partsFanOut", |j: &(&'static str, Vec<i64>)| j.1.clone())
        .via(|sub| {
            sub.concurrently(
                |b| {
                    b.pipe(step("validatePartStep", |part: i64| async move {
                        Ok(if part < 0 {
                            drop("negative part")
                        } else {
                            ok(part)
                        })
                    }))
                },
                None,
            )
        })
        .fan_in(
            "sumFanIn",
            |j: (&'static str, Vec<i64>), parts: Vec<i64>| (j.0, parts.iter().sum::<i64>()),
        )
        .build();
    pipeline.feed(items([
        ("partly-valid", vec![1, -2, 3]),
        ("all-valid", vec![1, 2]),
    ]));
    let mut collected = common::consume_all(pipeline.as_ref()).await;
    collected.sort();
    assert_eq!(collected, vec![("all-valid", 3), ("partly-valid", 4)]);
}
