//! An outer bound on object-store calls that deltalite waits for.
//!
//! `object_store` puts a timeout on each HTTP request and a budget on its retries (see
//! [`crate::table::S3_CLIENT_DEFAULTS`]), so a request that the network leaves open
//! fails by itself. The deadline here is a second line for a wait that those timers do
//! not see: a future that stops being woken, or a spawned task that never finishes.
//! The caller can hold budget permits while it waits, and a wait without an end keeps
//! those permits from every other call in the process.
//!
//! When the deadline passes, the wrapped future is dropped. That cancels its request and
//! releases what it holds, and the caller gets a normal `object_store` error.

use std::future::Future;
use std::sync::OnceLock;
use std::time::Duration;

use crate::limits::env_secs;

/// Default deadline of one deltalite object-store call. It is longer than the most
/// time `object_store` gives one call with its default retry budget (3 minutes, then
/// one more request of at most the request timeout), so it fires only when those timers
/// do not.
pub const DEFAULT_IO_DEADLINE: Duration = Duration::from_secs(10 * 60);
/// Environment override for [`DEFAULT_IO_DEADLINE`], in seconds; `0` removes the bound.
pub const IO_DEADLINE_ENV: &str = "DELTALITE_IO_DEADLINE_SECS";

/// The process-wide deadline, read from the environment on first use.
pub(crate) fn io_deadline() -> Option<Duration> {
    static DEADLINE: OnceLock<Option<Duration>> = OnceLock::new();
    *DEADLINE.get_or_init(|| env_secs(IO_DEADLINE_ENV, DEFAULT_IO_DEADLINE))
}

/// Run `fut` for at most `limit`. After `limit`, `fut` is dropped and the result is an
/// error that names the call with `what`. `None` waits without a bound.
pub(crate) async fn with_deadline<T>(
    limit: Option<Duration>,
    what: impl FnOnce() -> String,
    fut: impl Future<Output = object_store::Result<T>>,
) -> object_store::Result<T> {
    let Some(limit) = limit else {
        return fut.await;
    };
    match tokio::time::timeout(limit, fut).await {
        Ok(result) => result,
        Err(_) => Err(object_store::Error::Generic {
            store: "deltalite",
            source: format!(
                "{} did not finish within {}s; {IO_DEADLINE_ENV} sets this bound",
                what(),
                limit.as_secs()
            )
            .into(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tokio::sync::Semaphore;

    use super::*;

    #[tokio::test(start_paused = true)]
    async fn a_stuck_call_fails_after_the_deadline_and_releases_its_permit() {
        let budget = Arc::new(Semaphore::new(1));
        let permit = budget.clone().acquire_owned().await.unwrap();
        let stuck = async move {
            let _held = permit;
            std::future::pending::<object_store::Result<()>>().await
        };

        let err = with_deadline(
            Some(Duration::from_secs(60)),
            || "upload of part 3 of a.parquet".into(),
            stuck,
        )
        .await
        .unwrap_err()
        .to_string();

        assert!(err.contains("upload of part 3 of a.parquet"), "{err}");
        assert!(err.contains("60s"), "{err}");
        assert_eq!(budget.available_permits(), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn a_call_that_finishes_in_time_keeps_its_result() {
        let slow = async {
            tokio::time::sleep(Duration::from_secs(59)).await;
            Ok(7)
        };
        let got = with_deadline(Some(Duration::from_secs(60)), || "read".into(), slow).await;
        assert_eq!(got.unwrap(), 7);

        let unbounded = async {
            tokio::time::sleep(Duration::from_secs(3600)).await;
            Ok(8)
        };
        assert_eq!(
            with_deadline(None, || "read".into(), unbounded)
                .await
                .unwrap(),
            8
        );
    }
}
