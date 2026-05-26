//! Stage-wide concurrency primitives.
//!
//! Stages reach for a [`StageConcurrencyLimiter`] when they need an actual
//! ceiling on parallel work that holds across every batch flowing through the
//! stage on a single pod. The limiter wraps an `Arc<Semaphore>`, so cloning it
//! into per-item futures keeps the configured `capacity` honest no matter how
//! many `process()` calls fan out concurrently.
//!
//! [`run_buffered`] is the per-item driver most stages want: it takes a `Vec`
//! of inputs and an async closure that produces one output per input, runs up
//! to `capacity` of them at once, preserves input order in the returned `Vec`,
//! and short-circuits on the first `StageError`. Stages with item-fold or
//! batch-barrier semantics can call [`StageConcurrencyLimiter::acquire`]
//! directly and hold a permit around their own work.

use std::future::Future;
use std::sync::Arc;

use futures::stream::{self, StreamExt, TryStreamExt};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::StageError;

/// Shared cap on the number of in-flight stage operations.
///
/// The cap is a property of the stage instance, not of a single `process()`
/// call. Two concurrent batches running through the same stage share the same
/// permit pool, so the configured `capacity` is the actual ceiling on parallel
/// work regardless of how many batches the orchestrator hands the stage.
#[derive(Clone, Debug)]
pub struct StageConcurrencyLimiter {
    capacity: usize,
    semaphore: Arc<Semaphore>,
}

impl StageConcurrencyLimiter {
    /// Build a limiter with `capacity` permits (rounded up to at least one so
    /// the limiter never deadlocks at zero capacity).
    pub fn new(capacity: usize) -> Self {
        let capacity = capacity.max(1);
        Self {
            capacity,
            semaphore: Arc::new(Semaphore::new(capacity)),
        }
    }

    pub fn capacity(&self) -> usize {
        self.capacity
    }

    pub fn available_permits(&self) -> usize {
        self.semaphore.available_permits()
    }

    /// Acquire one permit, blocking the caller until one is free. The returned
    /// guard releases the permit on drop.
    pub async fn acquire(&self) -> Result<OwnedSemaphorePermit, StageError> {
        self.semaphore
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| StageError::Internal("stage concurrency limiter closed".to_string()))
    }
}

/// Run `f` against every item in `items` with up to `limiter.capacity()`
/// futures in flight at once.
///
/// Each per-item future acquires one permit from `limiter` before its body
/// runs, so the cap applies across concurrent calls to `run_buffered`. The
/// returned `Vec` preserves input order. The first per-item error short
/// circuits the rest of the work.
pub async fn run_buffered<I, O, F, Fut>(
    limiter: &StageConcurrencyLimiter,
    items: Vec<I>,
    mut f: F,
) -> Result<Vec<O>, StageError>
where
    I: Send + 'static,
    O: Send + 'static,
    F: FnMut(I) -> Fut + Send,
    Fut: Future<Output = Result<O, StageError>> + Send + 'static,
{
    let capacity = limiter.capacity();
    let futures: Vec<_> = items
        .into_iter()
        .map(|item| {
            let limiter = limiter.clone();
            let fut = f(item);
            async move {
                let _permit = limiter.acquire().await?;
                fut.await
            }
        })
        .collect();

    stream::iter(futures)
        .buffered(capacity)
        .try_collect::<Vec<_>>()
        .await
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use super::*;

    #[derive(Default)]
    struct InFlightProbe {
        in_flight: AtomicUsize,
        max_in_flight: AtomicUsize,
    }

    impl InFlightProbe {
        fn enter(&self) {
            let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            let mut peak = self.max_in_flight.load(Ordering::SeqCst);
            while now > peak {
                match self.max_in_flight.compare_exchange(
                    peak,
                    now,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                ) {
                    Ok(_) => break,
                    Err(current) => peak = current,
                }
            }
        }

        fn exit(&self) {
            self.in_flight.fetch_sub(1, Ordering::SeqCst);
        }

        fn peak(&self) -> usize {
            self.max_in_flight.load(Ordering::SeqCst)
        }
    }

    #[tokio::test]
    async fn run_buffered_caps_in_flight_within_a_single_call() {
        let probe = Arc::new(InFlightProbe::default());
        let limiter = StageConcurrencyLimiter::new(3);

        let probe_for_closure = probe.clone();
        let outputs = run_buffered(&limiter, (0..10).collect(), move |item| {
            let probe = probe_for_closure.clone();
            async move {
                probe.enter();
                tokio::time::sleep(Duration::from_millis(20)).await;
                probe.exit();
                Ok::<_, StageError>(item)
            }
        })
        .await
        .unwrap();

        assert_eq!(outputs, (0..10).collect::<Vec<_>>());
        assert_eq!(
            probe.peak(),
            3,
            "limiter capacity is the within-call ceiling"
        );
    }

    #[tokio::test]
    async fn run_buffered_shares_the_cap_across_concurrent_calls() {
        // Two concurrent `run_buffered` calls against the same limiter must
        // share its permits — otherwise the knob lies whenever a stage fans
        // out into multiple batches at once.
        let probe = Arc::new(InFlightProbe::default());
        let limiter = StageConcurrencyLimiter::new(2);

        let run_one = |start: i32| {
            let limiter = limiter.clone();
            let probe = probe.clone();
            async move {
                run_buffered(&limiter, (start..start + 5).collect(), move |item| {
                    let probe = probe.clone();
                    async move {
                        probe.enter();
                        tokio::time::sleep(Duration::from_millis(20)).await;
                        probe.exit();
                        Ok::<_, StageError>(item)
                    }
                })
                .await
            }
        };

        let (left, right) = tokio::join!(run_one(0), run_one(100));

        assert_eq!(left.unwrap(), (0..5).collect::<Vec<_>>());
        assert_eq!(right.unwrap(), (100..105).collect::<Vec<_>>());
        assert_eq!(
            probe.peak(),
            2,
            "shared limiter must cap concurrent run_buffered calls together"
        );
    }

    #[tokio::test]
    async fn run_buffered_short_circuits_on_error() {
        let limiter = StageConcurrencyLimiter::new(4);
        let result = run_buffered(&limiter, vec![1, 2, 3, 4], |item| async move {
            if item == 2 {
                Err(StageError::Transient("boom".to_string()))
            } else {
                Ok(item)
            }
        })
        .await;

        assert!(matches!(result, Err(StageError::Transient(_))));
    }

    #[tokio::test]
    async fn capacity_is_at_least_one() {
        let limiter = StageConcurrencyLimiter::new(0);
        assert_eq!(limiter.capacity(), 1);
        let _permit = limiter.acquire().await.unwrap();
    }
}
