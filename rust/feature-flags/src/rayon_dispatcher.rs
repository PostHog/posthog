use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_metrics::{gauge, histogram, inc};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::metrics::consts::{
    RAYON_DISPATCHER_AVAILABLE_PERMITS, RAYON_DISPATCHER_CONTENDED_ACQUIRES,
    RAYON_DISPATCHER_EXECUTION_TIME, RAYON_DISPATCHER_INFLIGHT_TASKS,
    RAYON_DISPATCHER_SEMAPHORE_TIMEOUTS, RAYON_DISPATCHER_SEMAPHORE_WAIT_TIME,
    RAYON_DISPATCHER_TOTAL_ACQUIRES,
};

static INFLIGHT_TASKS: AtomicUsize = AtomicUsize::new(0);

/// Returned by [`RayonDispatcher::try_spawn`] when the semaphore wait exceeds the
/// configured timeout. The caller can convert this into an HTTP 504 to trigger
/// ingress retry on a less-loaded pod.
#[derive(Debug)]
pub struct SemaphoreTimeout {
    pub waited: Duration,
}

/// Bounds concurrent batch dispatches to the Rayon thread pool.
///
/// Without backpressure, `rayon::spawn` feeds an unbounded injector queue.
/// Under sustained load this causes two compounding problems:
///   1. Queue depth grows without limit → queueing delay dominates p99.
///   2. Many concurrent `into_par_iter` batches each get fewer threads for
///      work-stealing → per-batch latency increases → queue drains slower.
///
/// `RayonDispatcher` interposes a [`tokio::sync::Semaphore`] so that at most
/// N batches are in-flight on the Rayon pool at any time. Callers that cannot
/// acquire a permit `.await` — yielding the Tokio worker thread — until a
/// slot opens.
#[derive(Clone)]
pub struct RayonDispatcher {
    semaphore: Arc<Semaphore>,
    timeout: Option<Duration>,
}

impl RayonDispatcher {
    pub fn new(max_concurrent_batches: usize, timeout: Option<Duration>) -> Self {
        Self {
            semaphore: Arc::new(Semaphore::new(max_concurrent_batches)),
            timeout,
        }
    }

    /// Dispatches `work` to the Rayon pool with bounded concurrency.
    ///
    /// 1. Acquires a semaphore permit (suspends if the pool is saturated).
    /// 2. Sends the closure to Rayon via `rayon::spawn`.
    /// 3. Returns the result through a `tokio::sync::oneshot` channel.
    /// 4. Releases the permit **before** signaling completion by sending the result,
    ///    `handle.await` is a reliable synchronisation point for permit
    ///    availability.
    ///
    /// Returns `None` if the Rayon task panicked (dropped the oneshot sender).
    pub async fn spawn<F, R>(&self, work: F) -> Option<R>
    where
        F: FnOnce() -> R + Send + 'static,
        R: Send + 'static,
    {
        // try_acquire(None) is infallible — no timeout means unbounded wait
        let permit = self
            .try_acquire(None)
            .await
            .expect("try_acquire(None) is infallible");
        Self::dispatch(permit, work).await
    }

    /// Like [`spawn`](Self::spawn), but respects the configured semaphore timeout.
    ///
    /// - When `self.timeout` is `None`: acquires without timeout, wraps in `Ok`.
    /// - When `self.timeout` is `Some(d)`: if the semaphore wait exceeds `d`,
    ///   returns `Err(SemaphoreTimeout)` so the caller can fail fast (HTTP 504).
    pub async fn try_spawn<F, R>(&self, work: F) -> Result<Option<R>, SemaphoreTimeout>
    where
        F: FnOnce() -> R + Send + 'static,
        R: Send + 'static,
    {
        let permit = self.try_acquire(self.timeout).await?;
        Ok(Self::dispatch(permit, work).await)
    }

    /// Number of permits not currently held. Useful for saturation metrics.
    pub fn available_permits(&self) -> usize {
        self.semaphore.available_permits()
    }

    /// Acquires a semaphore permit, recording all acquire-time metrics.
    ///
    /// When `timeout` is `None`, waits without limit. When `Some(d)`, fails
    /// with `SemaphoreTimeout` if the permit isn't acquired within `d`.
    async fn try_acquire(
        &self,
        timeout: Option<Duration>,
    ) -> Result<OwnedSemaphorePermit, SemaphoreTimeout> {
        let available_before = self.available_permits();
        gauge(
            RAYON_DISPATCHER_AVAILABLE_PERMITS,
            &[],
            available_before as f64,
        );

        inc(RAYON_DISPATCHER_TOTAL_ACQUIRES, &[], 1);
        if available_before == 0 {
            inc(RAYON_DISPATCHER_CONTENDED_ACQUIRES, &[], 1);
        }

        let wait_start = std::time::Instant::now();
        let result = match timeout {
            None => Ok(self.acquire().await),
            Some(deadline) => tokio::time::timeout(deadline, self.acquire())
                .await
                .map_err(|_| wait_start.elapsed()),
        };

        histogram(
            RAYON_DISPATCHER_SEMAPHORE_WAIT_TIME,
            &[],
            wait_start.elapsed().as_secs_f64() * 1000.0,
        );

        match result {
            Ok(permit) => Ok(permit),
            Err(waited) => {
                inc(RAYON_DISPATCHER_SEMAPHORE_TIMEOUTS, &[], 1);
                Err(SemaphoreTimeout { waited })
            }
        }
    }

    async fn acquire(&self) -> OwnedSemaphorePermit {
        self.semaphore
            .clone()
            .acquire_owned()
            .await
            .expect("rayon dispatcher semaphore closed — this is a bug")
    }

    /// Dispatches `work` onto the Rayon pool, returning the result via oneshot.
    /// The permit is released before sending the result so that `rx.await` is a
    /// reliable synchronization point for permit availability.
    async fn dispatch<F, R>(permit: OwnedSemaphorePermit, work: F) -> Option<R>
    where
        F: FnOnce() -> R + Send + 'static,
        R: Send + 'static,
    {
        let (tx, rx) = tokio::sync::oneshot::channel();

        rayon::spawn(move || {
            let inflight = INFLIGHT_TASKS.fetch_add(1, Ordering::Relaxed) + 1;
            gauge(RAYON_DISPATCHER_INFLIGHT_TASKS, &[], inflight as f64);

            let exec_start = std::time::Instant::now();
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work));
            histogram(
                RAYON_DISPATCHER_EXECUTION_TIME,
                &[],
                exec_start.elapsed().as_secs_f64() * 1000.0,
            );

            INFLIGHT_TASKS.fetch_sub(1, Ordering::Relaxed);
            drop(permit);

            if let Ok(value) = result {
                drop(tx.send(value));
            }
            // On panic: tx is dropped without sending → rx yields None via .ok()
        });

        rx.await.ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn spawn_returns_result() {
        let dispatcher = RayonDispatcher::new(2, None);
        let result = dispatcher.spawn(|| 42).await;
        assert_eq!(result, Some(42));
    }

    #[tokio::test]
    async fn spawn_returns_none_on_panic() {
        let dispatcher = RayonDispatcher::new(2, None);
        let result = dispatcher
            .spawn(|| {
                panic!("intentional test panic");
            })
            .await;
        assert_eq!(result, None::<()>);
    }

    #[tokio::test]
    async fn permits_bound_concurrency() {
        let dispatcher = RayonDispatcher::new(1, None);
        let peak = Arc::new(AtomicUsize::new(0));
        let active = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::new();
        for _ in 0..4 {
            let d = dispatcher.clone();
            let active = active.clone();
            let peak = peak.clone();
            handles.push(tokio::spawn(async move {
                d.spawn(move || {
                    let current = active.fetch_add(1, Ordering::SeqCst) + 1;
                    peak.fetch_max(current, Ordering::SeqCst);
                    std::thread::sleep(std::time::Duration::from_millis(50));
                    active.fetch_sub(1, Ordering::SeqCst);
                })
                .await
            }));
        }

        for h in handles {
            h.await.unwrap();
        }

        assert_eq!(peak.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn available_permits_reflects_state() {
        let dispatcher = RayonDispatcher::new(2, None);
        assert_eq!(dispatcher.available_permits(), 2);

        let (tx, rx) = tokio::sync::oneshot::channel::<()>();
        let d = dispatcher.clone();
        let handle = tokio::spawn(async move {
            d.spawn(move || {
                let _ = rx.blocking_recv();
            })
            .await
        });

        // Give the spawn time to acquire the permit
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        assert_eq!(dispatcher.available_permits(), 1);

        tx.send(()).unwrap();
        handle.await.unwrap();
        assert_eq!(dispatcher.available_permits(), 2);
    }

    #[tokio::test]
    async fn try_spawn_returns_ok_on_success() {
        let dispatcher = RayonDispatcher::new(2, Some(Duration::from_secs(5)));
        let result = dispatcher.try_spawn(|| 42).await;
        assert_eq!(result.unwrap(), Some(42));
    }

    #[tokio::test]
    async fn try_spawn_returns_ok_none_on_panic() {
        let dispatcher = RayonDispatcher::new(2, Some(Duration::from_secs(5)));
        let result = dispatcher
            .try_spawn(|| {
                panic!("intentional test panic");
            })
            .await;
        assert_eq!(result.unwrap(), None::<()>);
    }

    #[tokio::test]
    async fn try_spawn_returns_err_on_timeout() {
        // 1 permit, block it with a long-running task
        let dispatcher = RayonDispatcher::new(1, Some(Duration::from_millis(10)));

        let (tx, rx) = tokio::sync::oneshot::channel::<()>();
        let (acquired_tx, acquired_rx) = tokio::sync::oneshot::channel::<()>();
        let d = dispatcher.clone();
        let _blocker = tokio::spawn(async move {
            d.spawn(move || {
                let _ = acquired_tx.send(());
                let _ = rx.blocking_recv();
            })
            .await
        });

        // Wait for the blocker to actually acquire the permit
        acquired_rx.await.unwrap();

        // This should timeout because the permit is held
        let result = dispatcher.try_spawn(|| 99).await;
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(err.waited >= Duration::from_millis(10));

        // Clean up
        let _ = tx.send(());
    }

    #[tokio::test]
    async fn try_spawn_delegates_to_spawn_when_no_timeout() {
        let dispatcher = RayonDispatcher::new(2, None);
        let result = dispatcher.try_spawn(|| "hello").await;
        assert_eq!(result.unwrap(), Some("hello"));
    }
}
