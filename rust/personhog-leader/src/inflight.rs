use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;

/// Per-partition inflight request counter used by the handoff protocol to
/// prove that all writes this pod ever acked are durably in Kafka.
///
/// Because `produce_person_changelog` awaits the Kafka delivery future before
/// the handler returns success, "no inflight handlers for partition p" implies
/// "every write for p that this pod ever acknowledged is in Kafka."
///
/// Callers obtain a guard via `begin(partition)` and drop it when the handler
/// completes; the handoff protocol calls `wait_until_empty(partition)` to
/// block until all inflight handlers have returned.
#[derive(Default)]
pub struct InflightTracker {
    partitions: DashMap<u32, Arc<AtomicUsize>>,
}

impl InflightTracker {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn begin(self: &Arc<Self>, partition: u32) -> InflightGuard {
        let counter = self
            .partitions
            .entry(partition)
            .or_insert_with(|| Arc::new(AtomicUsize::new(0)))
            .clone();
        counter.fetch_add(1, Ordering::AcqRel);
        InflightGuard { counter }
    }

    /// Block until no inflight handlers remain for the partition. Polls at
    /// `poll_interval`; intended for handoff-time drain, not hot paths.
    pub async fn wait_until_empty(&self, partition: u32, poll_interval: Duration) {
        loop {
            let count = self
                .partitions
                .get(&partition)
                .map(|c| c.load(Ordering::Acquire))
                .unwrap_or(0);
            if count == 0 {
                return;
            }
            tokio::time::sleep(poll_interval).await;
        }
    }

    #[cfg(test)]
    pub fn count(&self, partition: u32) -> usize {
        self.partitions
            .get(&partition)
            .map(|c| c.load(Ordering::Acquire))
            .unwrap_or(0)
    }
}

/// RAII guard returned by `InflightTracker::begin`. Decrements the counter on
/// drop, including drops from panics or early returns.
pub struct InflightGuard {
    counter: Arc<AtomicUsize>,
}

impl Drop for InflightGuard {
    fn drop(&mut self) {
        self.counter.fetch_sub(1, Ordering::AcqRel);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn begin_and_drop_track_count() {
        let tracker = Arc::new(InflightTracker::new());
        assert_eq!(tracker.count(7), 0);

        let g1 = tracker.begin(7);
        let g2 = tracker.begin(7);
        assert_eq!(tracker.count(7), 2);

        drop(g1);
        assert_eq!(tracker.count(7), 1);
        drop(g2);
        assert_eq!(tracker.count(7), 0);
    }

    #[tokio::test]
    async fn wait_until_empty_returns_immediately_when_zero() {
        let tracker = Arc::new(InflightTracker::new());
        tokio::time::timeout(
            Duration::from_secs(1),
            tracker.wait_until_empty(42, Duration::from_millis(10)),
        )
        .await
        .expect("should return immediately");
    }

    #[tokio::test]
    async fn wait_until_empty_blocks_then_wakes() {
        let tracker = Arc::new(InflightTracker::new());
        let guard = tracker.begin(3);

        let t = Arc::clone(&tracker);
        let handle = tokio::spawn(async move {
            t.wait_until_empty(3, Duration::from_millis(10)).await;
        });

        // Give the task a moment to start and observe count > 0
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert!(!handle.is_finished());

        drop(guard);
        handle.await.unwrap();
    }

    #[tokio::test]
    async fn partitions_are_independent() {
        let tracker = Arc::new(InflightTracker::new());
        let _g = tracker.begin(1);
        tracker.wait_until_empty(2, Duration::from_millis(10)).await;
        assert_eq!(tracker.count(1), 1);
    }
}
