mod common;

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

use common::{items, sleep_ms, within_ms};
use ingestion_framework::{
    chunk_step, create_ok_context, new_chunk_pipeline, new_pipeline, ok, step, PipelineError,
    PipelineResultType, RetryOptions,
};

fn opts(tries: u32, sleep_ms: u64) -> RetryOptions {
    RetryOptions {
        tries: Some(tries),
        sleep_ms: Some(sleep_ms),
        ..Default::default()
    }
}

#[tokio::test(start_paused = true)]
async fn retriable_errors_are_retried_until_the_step_succeeds() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("flakyStep", move |v: String| {
                let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if n < 3 {
                        return Err(PipelineError::retriable("Temporary failure"));
                    }
                    Ok(ok(v.to_uppercase()))
                }
            }),
            opts(5, 100),
        )
        .build();
    let r = within_ms(300, pipeline.process(create_ok_context("hello".into(), ())))
        .await
        .unwrap();
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    assert_eq!(r.value().unwrap(), "HELLO");
}

#[tokio::test(start_paused = true)]
async fn non_retriable_errors_go_directly_to_dlq() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("validationStep", move |_v: String| {
                a.fetch_add(1, Ordering::SeqCst);
                async move {
                    Err::<ingestion_framework::PipelineResult<String>, _>(
                        PipelineError::non_retriable("Validation failed - invalid format"),
                    )
                }
            }),
            opts(5, 100),
        )
        .build();
    let r = within_ms(
        0,
        pipeline.process(create_ok_context("bad-data".into(), ())),
    )
    .await
    .unwrap();
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert_eq!(r.result.result_type(), PipelineResultType::Dlq);
    assert!(r.result.reason().unwrap().contains("non-retriable"));
}

#[tokio::test(start_paused = true)]
async fn after_max_retries_the_error_is_rethrown() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("alwaysFailsStep", move |_v: String| {
                let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    Err::<ingestion_framework::PipelineResult<String>, _>(PipelineError::retriable(
                        format!("Attempt {n} failed"),
                    ))
                }
            }),
            opts(3, 100),
        )
        .build();
    let err = within_ms(300, pipeline.process(create_ok_context("data".into(), ())))
        .await
        .unwrap_err();
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    assert_eq!(err.to_string(), "Attempt 3 failed");
}

#[tokio::test(start_paused = true)]
async fn errors_without_is_retriable_are_retried_then_rethrown() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("unexpectedErrorStep", move |_v: String| {
                a.fetch_add(1, Ordering::SeqCst);
                async move {
                    Err::<ingestion_framework::PipelineResult<String>, _>(anyhow::anyhow!(
                        "Unexpected internal error"
                    ))
                }
            }),
            opts(3, 100),
        )
        .build();
    let err = within_ms(300, pipeline.process(create_ok_context("data".into(), ())))
        .await
        .unwrap_err();
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    assert_eq!(err.to_string(), "Unexpected internal error");
}

#[tokio::test(start_paused = true)]
async fn tries_and_sleep_ms_control_attempts_and_backoff() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("slowlyRecoveringStep", move |v: String| {
                let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if n < 4 {
                        return Err(PipelineError::retriable("Still recovering"));
                    }
                    Ok(ok(v))
                }
            }),
            opts(5, 50),
        )
        .build();
    let handle =
        tokio::spawn(async move { pipeline.process(create_ok_context("data".into(), ())).await });
    async fn advance(ms: u64) {
        sleep_ms(ms).await;
        for _ in 0..10 {
            tokio::task::yield_now().await;
        }
    }
    advance(0).await;
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    advance(50).await;
    assert_eq!(attempts.load(Ordering::SeqCst), 2);
    advance(100).await;
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    advance(200).await;
    assert_eq!(attempts.load(Ordering::SeqCst), 4);
    assert!(handle.await.unwrap().unwrap().is_ok());
}

#[tokio::test(start_paused = true)]
async fn defaults_to_3_tries_and_100ms_sleep() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_pipeline::<String, ()>()
        .pipe_with_retry(
            step("flakyStep", move |v: String| {
                let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if n < 3 {
                        return Err(PipelineError::retriable("retry"));
                    }
                    Ok(ok(v))
                }
            }),
            RetryOptions::default(),
        )
        .build();
    let started = tokio::time::Instant::now();
    let r = within_ms(300, pipeline.process(create_ok_context("data".into(), ())))
        .await
        .unwrap();
    assert!(r.is_ok());
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    // 100 ms + 200 ms nominal, minus at most 5% jitter each.
    let elapsed = started.elapsed().as_millis();
    assert!((285..=300).contains(&elapsed), "{elapsed}");
}

#[tokio::test(start_paused = true)]
async fn pipe_chunk_retries_the_chunk_step_until_it_succeeds() {
    let attempts = Arc::new(AtomicU32::new(0));
    let a = attempts.clone();
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk_with_retry(
            chunk_step("flakyChunkStep", move |events: Vec<i64>| {
                let n = a.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if n < 3 {
                        return Err(PipelineError::retriable("Downstream unavailable"));
                    }
                    Ok(events.into_iter().map(ok).collect())
                }
            }),
            opts(5, 100),
        )
        .build();
    pipeline.feed(items([1, 2]));
    let results = within_ms(300, pipeline.next()).await.unwrap().unwrap();
    assert_eq!(attempts.load(Ordering::SeqCst), 3);
    assert_eq!(results.len(), 2);
    assert!(results.iter().all(|r| r.is_ok()));
}

#[tokio::test(start_paused = true)]
async fn pipe_chunk_sends_one_dlq_per_input_on_a_non_retriable_error() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk_with_retry(
            chunk_step("failingChunkStep", |_events: Vec<i64>| async move {
                Err::<Vec<ingestion_framework::PipelineResult<i64>>, _>(
                    PipelineError::non_retriable("Chunk permanently invalid"),
                )
            }),
            opts(5, 100),
        )
        .build();
    pipeline.feed(items([1, 2, 3]));
    let results = within_ms(0, pipeline.next()).await.unwrap().unwrap();
    assert_eq!(results.len(), 3);
    assert!(results
        .iter()
        .all(|r| r.result.result_type() == PipelineResultType::Dlq));
}
