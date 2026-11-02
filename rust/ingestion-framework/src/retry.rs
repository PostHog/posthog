//! Port of `retry.ts` and `retryIfRetriable` from `~/common/utils/retries`.

use std::sync::Arc;
use std::time::Duration;

use rand::Rng;
use tokio::time::Instant;

use crate::errors::is_retriable;
use crate::metrics::record_retry_attempts;
use crate::results::{dlq, PipelineResult};
use crate::steps::{ChunkProcessingStep, ProcessingStep};

/// Port of `RetrySchedule` plus `RetryOptions.name`. Defaults match `defaultRetryConfig`.
#[derive(Debug, Clone, Default)]
pub struct RetryOptions {
    pub tries: Option<u32>,
    pub sleep_ms: Option<u64>,
    pub backoff_factor: Option<f64>,
    pub max_sleep_ms: Option<u64>,
    pub jitter: Option<f64>,
    pub soft_deadline_ms: Option<u64>,
    pub name: Option<String>,
}

pub const DEFAULT_TRIES: u32 = 3;
pub const DEFAULT_SLEEP_MS: u64 = 100;
pub const DEFAULT_BACKOFF_FACTOR: f64 = 2.0;
pub const DEFAULT_MAX_SLEEP_MS: u64 = 10_000;
pub const DEFAULT_JITTER: f64 = 0.05;

pub async fn retry_if_retriable<T, F, Fut>(
    mut f: F,
    options: &RetryOptions,
) -> (anyhow::Result<T>, u32)
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    retry_with_input((), |()| f(), options).await
}

/// Every attempt but the last possible one gets a clone, so `tries: 1` clones nothing. The first
/// attempt cannot take `input`, because a retry needs it again.
pub async fn retry_with_input<V, T, F, Fut>(
    input: V,
    mut f: F,
    options: &RetryOptions,
) -> (anyhow::Result<T>, u32)
where
    V: Clone,
    F: FnMut(V) -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    let tries = options.tries.unwrap_or(DEFAULT_TRIES);
    if tries == 0 {
        // Node's loop runs no attempt and reaches this throw.
        return (Err(anyhow::anyhow!("Unreachable error in retry")), 0);
    }
    let backoff = options.backoff_factor.unwrap_or(DEFAULT_BACKOFF_FACTOR);
    let max_sleep = options.max_sleep_ms.unwrap_or(DEFAULT_MAX_SLEEP_MS) as f64;
    let jitter = options.jitter.unwrap_or(DEFAULT_JITTER);
    let soft_deadline = options.soft_deadline_ms.map(Duration::from_millis);
    let started = Instant::now();
    let past_deadline = || soft_deadline.is_some_and(|d| started.elapsed() >= d);

    let mut sleep_ms = options.sleep_ms.unwrap_or(DEFAULT_SLEEP_MS) as f64;
    let mut input = Some(input);
    let mut attempts = 0;
    loop {
        attempts += 1;
        let value = if attempts >= tries {
            input.take().expect("the last attempt takes the input once")
        } else {
            input.clone().expect("input is kept until the last attempt")
        };
        match f(value).await {
            Ok(value) => return (Ok(value), attempts),
            Err(error) => {
                if is_retriable(&error) == Some(false) || attempts >= tries || past_deadline() {
                    return (Err(error), attempts);
                }
                let jittered = if jitter > 0.0 {
                    sleep_ms * (1.0 - jitter + rand::thread_rng().gen::<f64>() * jitter)
                } else {
                    sleep_ms
                };
                tokio::time::sleep(node_timer_delay(jittered)).await;
                sleep_ms = js_min(sleep_ms * backoff, max_sleep);
                if past_deadline() {
                    return (Err(error), attempts);
                }
            }
        }
    }
}

// Node's `TIMEOUT_MAX`, the largest delay that `setTimeout` keeps.
const NODE_TIMEOUT_MAX_MS: f64 = 2_147_483_647.0;

/// Node's `setTimeout` uses 1 ms for a NaN, sub-1 or over-`TIMEOUT_MAX` delay, so bad options cannot fail a retry.
fn node_timer_delay(ms: f64) -> Duration {
    let ms = if (1.0..=NODE_TIMEOUT_MAX_MS).contains(&ms) {
        ms
    } else {
        1.0
    };
    Duration::from_secs_f64(ms / 1000.0)
}

/// `Math.min(a, b)`, which returns NaN when an input is NaN. `f64::min` returns the other input.
fn js_min(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() {
        f64::NAN
    } else {
        a.min(b)
    }
}

const NON_RETRIABLE_REASON: &str = "Processing error - non-retriable";

pub fn with_step_retry<T, U>(
    step: ProcessingStep<T, U>,
    options: RetryOptions,
) -> ProcessingStep<T, U>
where
    T: Clone + Send + Sync + 'static,
    U: Send + 'static,
{
    let name: Arc<str> = Arc::from(
        options
            .name
            .clone()
            .unwrap_or_else(|| step.name().to_string()),
    );
    let step_name = step.name().to_string();
    let options = Arc::new(options);
    ProcessingStep::new(&step_name, move |value: T| {
        let step = step.clone();
        let options = options.clone();
        let name = name.clone();
        async move {
            let (result, attempts) =
                retry_with_input(value, |value| step.call(value), &options).await;
            match result {
                Ok(result) => {
                    record_retry_attempts(name, "completed", attempts);
                    Ok(result)
                }
                Err(error) => {
                    let retriable = is_retriable(&error);
                    tracing::error!(step = %name, error = %error, ?retriable, "Step failed");
                    if retriable == Some(false) {
                        record_retry_attempts(name, "non_retriable", attempts);
                        Ok(dlq(NON_RETRIABLE_REASON, Some(error)))
                    } else {
                        record_retry_attempts(name, "exhausted", attempts);
                        Err(error)
                    }
                }
            }
        }
    })
}

pub fn with_chunk_retry<T, U>(
    step: ChunkProcessingStep<T, U>,
    options: RetryOptions,
) -> ChunkProcessingStep<T, U>
where
    T: Clone + Send + Sync + 'static,
    U: Send + 'static,
{
    let name: Arc<str> = Arc::from(
        options
            .name
            .clone()
            .unwrap_or_else(|| step.name().to_string()),
    );
    let step_name = step.name().to_string();
    let options = Arc::new(options);
    ChunkProcessingStep::new(&step_name, move |values: Vec<T>| {
        let step = step.clone();
        let options = options.clone();
        let name = name.clone();
        async move {
            let count = values.len();
            let (result, attempts) =
                retry_with_input(values, |values| step.call(values), &options).await;
            match result {
                Ok(result) => {
                    record_retry_attempts(name, "completed", attempts);
                    Ok(result)
                }
                Err(error) => {
                    let retriable = is_retriable(&error);
                    tracing::error!(step = %name, error = %error, chunk_size = count, ?retriable, "Chunk step failed");
                    if retriable == Some(false) {
                        record_retry_attempts(name, "non_retriable", attempts);
                        let shared = Arc::new(error);
                        Ok((0..count)
                            .map(|_| {
                                let mut r: PipelineResult<U> = dlq(NON_RETRIABLE_REASON, None);
                                if let crate::results::Outcome::NonOk(
                                    crate::results::NonOk::Dlq { error, .. },
                                ) = &mut r.outcome
                                {
                                    *error = Some(shared.clone());
                                }
                                r
                            })
                            .collect())
                    } else {
                        record_retry_attempts(name, "exhausted", attempts);
                        Err(error)
                    }
                }
            }
        }
    })
}
