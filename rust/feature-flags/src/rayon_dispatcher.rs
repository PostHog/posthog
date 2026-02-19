use std::sync::Arc;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

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
}

impl RayonDispatcher {
    pub fn new(max_concurrent_batches: usize) -> Self {
        Self {
            semaphore: Arc::new(Semaphore::new(max_concurrent_batches)),
        }
    }

    /// Dispatches `work` to the Rayon pool with bounded concurrency.
    ///
    /// 1. Acquires a semaphore permit (suspends if the pool is saturated).
    /// 2. Sends the closure to Rayon via `rayon::spawn`.
    /// 3. Returns the result through a `tokio::sync::oneshot` channel.
    /// 4. Releases the permit **after** the Rayon work completes.
    ///
    /// Returns `None` if the Rayon task panicked (dropped the oneshot sender).
    pub async fn spawn<F, R>(&self, work: F) -> Option<R>
    where
        F: FnOnce() -> R + Send + 'static,
        R: Send + 'static,
    {
        let permit = self.acquire().await;
        let (tx, rx) = tokio::sync::oneshot::channel();

        rayon::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work));
            if let Ok(value) = result {
                drop(tx.send(value));
            }
            // On panic: tx is dropped without sending → rx yields None via .ok()
            drop(permit);
        });

        rx.await.ok()
    }

    /// Number of permits not currently held. Useful for saturation metrics.
    pub fn available_permits(&self) -> usize {
        self.semaphore.available_permits()
    }

    async fn acquire(&self) -> OwnedSemaphorePermit {
        self.semaphore
            .clone()
            .acquire_owned()
            .await
            .expect("rayon dispatcher semaphore closed — this is a bug")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[tokio::test]
    async fn spawn_returns_result() {
        let dispatcher = RayonDispatcher::new(2);
        let result = dispatcher.spawn(|| 42).await;
        assert_eq!(result, Some(42));
    }

    #[tokio::test]
    async fn spawn_returns_none_on_panic() {
        let dispatcher = RayonDispatcher::new(2);
        let result = dispatcher
            .spawn(|| {
                panic!("intentional test panic");
            })
            .await;
        assert_eq!(result, None::<()>);
    }

    #[tokio::test]
    async fn permits_bound_concurrency() {
        let dispatcher = RayonDispatcher::new(1);
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
        let dispatcher = RayonDispatcher::new(2);
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
}
