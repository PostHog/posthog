use std::future::Future;
use std::time::Duration;

use metrics::counter;
use rand::Rng;
use tonic::{Code, Status};
use tracing::warn;

use crate::config::RetryConfig;

fn is_retryable(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable | Code::DeadlineExceeded | Code::Internal
    )
}

fn code_as_str(code: Code) -> &'static str {
    match code {
        Code::Ok => "ok",
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::InvalidArgument => "invalid_argument",
        Code::DeadlineExceeded => "deadline_exceeded",
        Code::NotFound => "not_found",
        Code::AlreadyExists => "already_exists",
        Code::PermissionDenied => "permission_denied",
        Code::ResourceExhausted => "resource_exhausted",
        Code::FailedPrecondition => "failed_precondition",
        Code::Aborted => "aborted",
        Code::OutOfRange => "out_of_range",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data_loss",
        Code::Unauthenticated => "unauthenticated",
    }
}

/// Executes an async operation with exponential backoff and jitter on transient gRPC errors.
///
/// Only retries on `Unavailable`, `DeadlineExceeded`, and `Internal` status codes.
/// Permanent errors (e.g. `InvalidArgument`, `NotFound`) are returned immediately.
pub async fn with_retry<F, Fut, T>(
    config: &RetryConfig,
    method: &'static str,
    mut make_call: F,
) -> Result<T, Status>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, Status>>,
{
    let mut delay_ms = config.initial_backoff_ms;

    for attempt in 0..=config.max_retries {
        match make_call().await {
            Ok(value) => return Ok(value),
            Err(status) if attempt < config.max_retries && is_retryable(status.code()) => {
                let code_str = code_as_str(status.code());

                counter!(
                    "personhog_router_backend_retries_total",
                    "method" => method,
                    "status_code" => code_str
                )
                .increment(1);

                warn!(
                    method = method,
                    attempt = attempt + 1,
                    max_retries = config.max_retries,
                    status_code = code_str,
                    "retrying after transient error"
                );

                let base = delay_ms / 2;
                let jittered_ms = base + rand::thread_rng().gen_range(0..=base);
                tokio::time::sleep(Duration::from_millis(jittered_ms)).await;
                delay_ms = (delay_ms * 2).min(config.max_backoff_ms);
            }
            Err(status) => return Err(status),
        }
    }

    unreachable!("loop runs max_retries + 1 times and always returns")
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU32, Ordering};

    use super::*;

    fn test_config() -> RetryConfig {
        RetryConfig {
            max_retries: 3,
            initial_backoff_ms: 1,
            max_backoff_ms: 10,
        }
    }

    #[tokio::test]
    async fn succeeds_on_first_attempt() {
        let calls = AtomicU32::new(0);
        let result = with_retry(&test_config(), "test", || {
            calls.fetch_add(1, Ordering::SeqCst);
            async { Ok::<_, Status>("ok") }
        })
        .await;

        assert_eq!(result.unwrap(), "ok");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn retries_transient_then_succeeds() {
        let transient_codes = vec![Code::Unavailable, Code::DeadlineExceeded, Code::Internal];
        for code in transient_codes {
            let calls = AtomicU32::new(0);
            let result = with_retry(&test_config(), "test", || {
                let attempt = calls.fetch_add(1, Ordering::SeqCst);
                let status = Status::new(code, "transient");
                async move {
                    if attempt < 2 {
                        Err(status)
                    } else {
                        Ok("recovered")
                    }
                }
            })
            .await;

            assert_eq!(result.unwrap(), "recovered", "should recover from {code:?}");
            assert_eq!(
                calls.load(Ordering::SeqCst),
                3,
                "should take 3 attempts for {code:?}"
            );
        }
    }

    #[tokio::test]
    async fn does_not_retry_permanent_errors() {
        let calls = AtomicU32::new(0);
        let result = with_retry(&test_config(), "test", || {
            calls.fetch_add(1, Ordering::SeqCst);
            async { Err::<&str, _>(Status::invalid_argument("bad request")) }
        })
        .await;

        assert_eq!(result.unwrap_err().code(), Code::InvalidArgument);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn exhausts_retries_on_persistent_transient_error() {
        let calls = AtomicU32::new(0);
        let result = with_retry(&test_config(), "test", || {
            calls.fetch_add(1, Ordering::SeqCst);
            async { Err::<&str, _>(Status::unavailable("still down")) }
        })
        .await;

        assert_eq!(result.unwrap_err().code(), Code::Unavailable);
        // 1 initial + 3 retries = 4 total attempts
        assert_eq!(calls.load(Ordering::SeqCst), 4);
    }

    #[tokio::test]
    async fn no_retries_when_max_retries_is_zero() {
        let config = RetryConfig {
            max_retries: 0,
            initial_backoff_ms: 1,
            max_backoff_ms: 10,
        };
        let calls = AtomicU32::new(0);
        let result = with_retry(&config, "test", || {
            calls.fetch_add(1, Ordering::SeqCst);
            async { Err::<&str, _>(Status::unavailable("down")) }
        })
        .await;

        assert_eq!(result.unwrap_err().code(), Code::Unavailable);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn retries_all_transient_codes() {
        let cases = vec![
            (Code::Unavailable, "unavailable"),
            (Code::DeadlineExceeded, "deadline_exceeded"),
            (Code::Internal, "internal"),
        ];
        for (code, msg) in cases {
            let calls = AtomicU32::new(0);
            let config = RetryConfig {
                max_retries: 1,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            };
            let result = with_retry(&config, "test", || {
                calls.fetch_add(1, Ordering::SeqCst);
                let status = Status::new(code, msg);
                async move { Err::<&str, _>(status) }
            })
            .await;

            assert_eq!(result.unwrap_err().code(), code);
            assert_eq!(calls.load(Ordering::SeqCst), 2, "should retry {code:?}");
        }
    }
}
