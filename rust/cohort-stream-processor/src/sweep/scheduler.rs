//! The periodic sweep timer and its [`Sweeper`] seam, plus the safety-margin → cutoff bridge.
//!
//! The eviction queue is per-worker (one [`EvictionQueue`](super::EvictionQueue) per partition
//! worker), so the timer itself owns no state. Each tick it asks a [`Sweeper`] to run one pass.

use std::time::{Duration, Instant};

use async_trait::async_trait;
use metrics::{counter, histogram};
use tokio::time::MissedTickBehavior;
use tokio_util::sync::CancellationToken;
use tracing::{debug, info};

use crate::observability::metrics::{SWEEP_CYCLES_TOTAL, SWEEP_CYCLE_DURATION_SECONDS};

/// One sweep pass. Behind a trait so [`run_sweep_loop`] is testable with an in-process fake.
///
/// Implementations must not panic: a panic in `run_once` would abort the timer task and stop all
/// future sweeps. Any per-partition failure should be handled and counted inside the impl.
#[async_trait]
pub trait Sweeper: Send + Sync {
    /// Perform one sweep cycle: evict every key whose deadline has passed (minus the safety margin).
    async fn run_once(&self);
}

/// The cutoff a worker passes to [`EvictionQueue::pop_due`](super::EvictionQueue::pop_due): a key is
/// due once its deadline is strictly before `now_ms − safety_margin_ms`.
///
/// Centralizes the only arithmetic in the sweep so the queue stays pure. `saturating_sub` keeps it
/// total: a test clock with `now_ms < safety_margin_ms` yields a far-negative cutoff — below every
/// real (positive) deadline, i.e. "nothing due", the safe direction — instead of overflowing.
pub fn due_before_ms(now_ms: i64, safety_margin_ms: i64) -> i64 {
    now_ms.saturating_sub(safety_margin_ms)
}

/// Drive the periodic sweep until `cancel` fires, invoking `sweeper.run_once()` once per tick and
/// recording [`SWEEP_CYCLES_TOTAL`] + [`SWEEP_CYCLE_DURATION_SECONDS`], both labelled by `loop_name`.
///
/// `loop_name` (`eviction`|`redrive`|`merge_gc`|`checkpoint`|`store_stats`) labels the cycle metrics
/// so the concurrent loops — same timer machinery, different cadences — stay distinguishable.
///
/// - **`MissedTickBehavior::Skip`**: if a sweep runs long or the task is starved, the timer drops the
///   ticks it slept through rather than firing a catch-up burst — one sweep then resumes on the
///   normal cadence.
/// - **`biased` select, cancel first**: a shutdown requested mid-interval is honored before the next
///   tick. An in-flight `run_once` is never interrupted — `select!` only races the two *futures*, so
///   once `run_once` is being polled it runs to completion before the loop re-checks `cancel`.
pub async fn run_sweep_loop<S: Sweeper>(
    sweeper: S,
    interval: Duration,
    loop_name: &'static str,
    cancel: CancellationToken,
) {
    let mut ticker = tokio::time::interval(interval);
    ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
    info!(
        interval_ms = interval.as_millis(),
        loop_name, "sweep loop started"
    );

    loop {
        tokio::select! {
            biased;
            _ = cancel.cancelled() => {
                info!(loop_name, "sweep loop stopping on shutdown signal");
                break;
            }
            _ = ticker.tick() => {
                let started = Instant::now();
                sweeper.run_once().await;
                histogram!(SWEEP_CYCLE_DURATION_SECONDS, "loop" => loop_name)
                    .record(started.elapsed().as_secs_f64());
                counter!(SWEEP_CYCLES_TOTAL, "loop" => loop_name).increment(1);
                debug!(loop_name, "sweep cycle completed");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use super::*;

    #[derive(Clone, Default)]
    struct CountingSweeper {
        count: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl Sweeper for CountingSweeper {
        async fn run_once(&self) {
            self.count.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[test]
    fn due_before_subtracts_the_margin() {
        assert_eq!(due_before_ms(1_000, 300), 700);
        assert_eq!(due_before_ms(300, 300), 0, "now == margin → cutoff 0");
        assert_eq!(due_before_ms(i64::MAX, 0), i64::MAX);
    }

    #[test]
    fn due_before_saturates_when_margin_exceeds_now() {
        // now small, margin huge → far-negative cutoff, no overflow panic. Below any real deadline,
        // so the queue holds everything (the safe "nothing due" direction).
        let cutoff = due_before_ms(0, i64::MAX);
        assert!(cutoff < 0);
        assert_eq!(cutoff, 0_i64.saturating_sub(i64::MAX));
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn sweep_loop_runs_once_per_interval() {
        let sweeper = CountingSweeper::default();
        let count = sweeper.count.clone();
        let cancel = CancellationToken::new();
        let interval = Duration::from_secs(30);

        let handle = tokio::spawn(run_sweep_loop(sweeper, interval, "test", cancel.clone()));

        // `tokio::time::interval`'s first tick fires immediately, so the loop sweeps once at startup.
        tokio::task::yield_now().await;
        assert_eq!(count.load(Ordering::SeqCst), 1, "immediate first tick");

        // Each subsequent interval triggers exactly one more sweep — no catch-up bursts.
        for expected in 2..=5 {
            tokio::time::advance(interval).await;
            tokio::task::yield_now().await;
            assert_eq!(count.load(Ordering::SeqCst), expected);
        }

        cancel.cancel();
        handle.await.expect("sweep loop exits cleanly on cancel");
    }

    #[tokio::test(flavor = "current_thread", start_paused = true)]
    async fn sweep_loop_stops_on_cancel_and_runs_no_further() {
        let sweeper = CountingSweeper::default();
        let count = sweeper.count.clone();
        let cancel = CancellationToken::new();
        let interval = Duration::from_secs(30);

        let handle = tokio::spawn(run_sweep_loop(sweeper, interval, "test", cancel.clone()));
        tokio::task::yield_now().await;
        assert_eq!(count.load(Ordering::SeqCst), 1);

        cancel.cancel();
        handle.await.expect("sweep loop exits cleanly on cancel");
        let after_cancel = count.load(Ordering::SeqCst);

        // Time advancing past the cancel must not produce more sweeps — the loop is gone.
        tokio::time::advance(interval * 10).await;
        tokio::task::yield_now().await;
        assert_eq!(count.load(Ordering::SeqCst), after_cancel);
    }
}
