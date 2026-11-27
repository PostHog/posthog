use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use ingestion_framework::errors::SharedError;
use ingestion_framework::metrics::record_retry_attempts;
use ingestion_framework::PipelineError;
use logs_ingestion::pipeline::errors::ERR_MSG_SIZE_TOO_LARGE;
use logs_ingestion::pipeline::{DependencyUnavailableError, KafkaProduceError};
use rand::Rng;
use tokio::time::Instant;

/// Node's `error.isRetriable`. `None` is `undefined`, which `retryIfRetriable` retries.
/// The producer throws `MessageSizeTooLarge` (`isRetriable = false`) for librdkafka code 10 and the raw error otherwise.
pub fn is_retriable(error: &anyhow::Error) -> Option<bool> {
    let outermost = error.chain().next()?;
    if let Some(shared) = outermost.downcast_ref::<SharedError>() {
        return is_retriable(&shared.0);
    }
    if let Some(e) = outermost.downcast_ref::<PipelineError>() {
        return e.retriable;
    }
    if outermost
        .downcast_ref::<DependencyUnavailableError>()
        .is_some()
    {
        return Some(true);
    }
    if let Some(e) = outermost.downcast_ref::<KafkaProduceError>() {
        return (e.code == ERR_MSG_SIZE_TOO_LARGE).then_some(false);
    }
    None
}

pub fn error_name(error: &anyhow::Error) -> String {
    match error.downcast_ref::<SharedError>() {
        Some(shared) => error_name(&shared.0),
        None => logs_ingestion::pipeline::errors::error_name(error),
    }
}

#[derive(Debug, Clone, Copy)]
pub struct RetrySchedule {
    pub name: &'static str,
    /// Total attempts, including the first.
    pub tries: u32,
    pub sleep_ms: f64,
    /// No attempt starts after this much time since the first.
    pub soft_deadline: Option<Duration>,
}

pub const RESOLVE_TEAM_RETRY: RetrySchedule = RetrySchedule {
    name: "resolve_metrics_team",
    tries: 3,
    sleep_ms: 100.0,
    soft_deadline: None,
};

/// A delivery timeout already includes librdkafka's retries. The deadline stops more attempts after a slow failure.
pub const PRODUCE_RETRY: RetrySchedule = RetrySchedule {
    name: "produce_metrics",
    tries: 5,
    sleep_ms: 100.0,
    soft_deadline: Some(Duration::from_secs(10)),
};

const BACKOFF_FACTOR: f64 = 2.0;
const MAX_SLEEP_MS: f64 = 10_000.0;
const JITTER: f64 = 0.05;

/// `retryAfterFirstFailure`: the retry rule and schedule of `retryIfRetriable`. The metric records only calls that failed at least once.
pub async fn retry_after_first_failure<T, F, Fut>(
    mut f: F,
    schedule: RetrySchedule,
) -> anyhow::Result<T>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = anyhow::Result<T>>,
{
    let started = Instant::now();
    let mut error = match f().await {
        Ok(value) => return Ok(value),
        Err(error) => error,
    };
    let past_deadline = || {
        schedule
            .soft_deadline
            .is_some_and(|deadline| started.elapsed() >= deadline)
    };
    let name: Arc<str> = Arc::from(schedule.name);
    // With zero tries the first error would not reach the caller.
    let tries = schedule.tries.max(1);
    let mut sleep_ms = schedule.sleep_ms;
    let mut attempts = 1;
    loop {
        if is_retriable(&error) == Some(false) {
            record_retry_attempts(name, "non_retriable", attempts);
            return Err(error);
        }
        if attempts >= tries || past_deadline() {
            record_retry_attempts(name, "exhausted", attempts);
            return Err(error);
        }
        let jittered = sleep_ms * (1.0 - JITTER + rand::thread_rng().gen::<f64>() * JITTER);
        tokio::time::sleep(Duration::from_secs_f64(jittered.max(1.0) / 1000.0)).await;
        sleep_ms = (sleep_ms * BACKOFF_FACTOR).min(MAX_SLEEP_MS);
        if past_deadline() {
            record_retry_attempts(name, "exhausted", attempts);
            return Err(error);
        }
        attempts += 1;
        match f().await {
            Ok(value) => {
                record_retry_attempts(name, "completed", attempts);
                return Ok(value);
            }
            Err(next) => error = next,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU32, Ordering};

    use logs_ingestion::pipeline::NamedError;

    use super::*;

    #[tokio::test(start_paused = true)]
    async fn the_soft_deadline_counts_from_the_first_attempt() {
        let calls = AtomicU32::new(0);
        let schedule = RetrySchedule {
            soft_deadline: Some(Duration::from_millis(250)),
            ..PRODUCE_RETRY
        };
        let result: anyhow::Result<()> = retry_after_first_failure(
            || {
                calls.fetch_add(1, Ordering::SeqCst);
                async { Err(anyhow::Error::new(NamedError::new("Error", "slow"))) }
            },
            schedule,
        )
        .await;
        assert_eq!(result.unwrap_err().to_string(), "slow");
        // The second sleep ends past 250 ms, so no third attempt starts.
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }
}
