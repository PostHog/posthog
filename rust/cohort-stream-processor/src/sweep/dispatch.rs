//! [`DispatchSweeper`]: the real [`Sweeper`] that drives one eviction cycle over the dispatcher.
//!
//! Each tick it computes the cutoff `due_before_ms = now − safety_margin` **once** and routes a
//! [`ShuffleMessage::Sweep`](crate::partitions::ShuffleMessage::Sweep) carrying it to every owned
//! partition's worker (via [`EventDispatcher::route_sweep`]), so each worker drains its own
//! [`EvictionQueue`](super::EvictionQueue) against the same clock reading. The cutoff is the queue's
//! only clock input, keeping the per-worker queues arithmetic- and clock-free.

use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;

use super::scheduler::{due_before_ms, Sweeper};
use crate::consumers::events::EventDispatcher;

/// Wall-clock provider for the cutoff. `Arc<dyn Fn>` so production uses [`Utc::now`] and tests inject
/// a fixed clock to make the cutoff deterministic.
type Clock = Arc<dyn Fn() -> i64 + Send + Sync>;

/// A [`Sweeper`] that routes a `Sweep` tick to every owned partition each cycle.
#[derive(Clone)]
pub struct DispatchSweeper {
    dispatcher: Arc<EventDispatcher>,
    safety_margin_ms: i64,
    now_ms: Clock,
}

impl DispatchSweeper {
    /// Build a sweeper over `dispatcher`, subtracting `safety_margin_ms` from wall-clock `now` to get
    /// each cycle's cutoff. Uses the system clock; [`with_clock`](Self::with_clock) injects a test one.
    pub fn new(dispatcher: Arc<EventDispatcher>, safety_margin_ms: i64) -> Self {
        Self::with_clock(
            dispatcher,
            safety_margin_ms,
            Arc::new(|| Utc::now().timestamp_millis()),
        )
    }

    /// Inject the clock — the test seam — so a fixed `now` makes the routed cutoff deterministic.
    pub fn with_clock(
        dispatcher: Arc<EventDispatcher>,
        safety_margin_ms: i64,
        now_ms: Clock,
    ) -> Self {
        Self {
            dispatcher,
            safety_margin_ms,
            now_ms,
        }
    }
}

#[async_trait]
impl Sweeper for DispatchSweeper {
    async fn run_once(&self) {
        let cutoff = due_before_ms((self.now_ms)(), self.safety_margin_ms);
        self.dispatcher.route_sweep(cutoff).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    use crate::consumers::events::EventDispatcher;
    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::partitions::{OffsetTracker, PartitionRouter};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::{CohortStore, StoreConfig};

    fn dispatcher() -> (TempDir, Arc<EventDispatcher>) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])));
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            store,
            catalog,
            sink,
        );
        (dir, Arc::new(dispatcher))
    }

    #[tokio::test]
    async fn run_once_routes_to_owned_partitions_without_panicking() {
        // Owned partitions with no spawned worker: each `Sweep` is a benign dropped RouteError, so
        // run_once must complete cleanly. Exercises the clock seam + route path end to end.
        let (_dir, dispatcher) = dispatcher();
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let sweeper = DispatchSweeper::with_clock(
            dispatcher.clone(),
            300_000,
            Arc::new(|| 1_700_000_000_000),
        );
        sweeper.run_once().await;
    }

    #[tokio::test]
    async fn run_once_with_no_owned_partitions_is_a_noop() {
        let (_dir, dispatcher) = dispatcher();
        let sweeper = DispatchSweeper::new(dispatcher, 300_000);
        sweeper.run_once().await;
    }
}
