//! Periodic merge-CF garbage-collection tick.
//!
//! Each tick reads the clock once, derives the marker/tombstone cutoffs (`now − retention`), and
//! routes one `MergeCfGc` to every owned partition's worker. Computing the cutoffs here — not in the
//! worker — keeps the worker clock-free, like [`DispatchSweeper`](crate::sweep::DispatchSweeper)'s
//! `due_before_ms`.

use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;

use crate::consumers::events::EventDispatcher;
use crate::sweep::Sweeper;

type Clock = Arc<dyn Fn() -> i64 + Send + Sync>;

/// A [`Sweeper`] that routes a merge-CF GC tick to every owned partition each cycle.
///
/// Holds the two retention floors (marker / tombstone). On each tick it reads the clock once and
/// derives `now − retention` cutoffs, so a single tick uses one consistent `now` across all CFs.
#[derive(Clone)]
pub struct MergeGcSweeper {
    dispatcher: Arc<EventDispatcher>,
    marker_retention_ms: i64,
    tombstone_retention_ms: i64,
    now_ms: Clock,
}

impl MergeGcSweeper {
    pub fn new(
        dispatcher: Arc<EventDispatcher>,
        marker_retention_ms: i64,
        tombstone_retention_ms: i64,
    ) -> Self {
        Self::with_clock(
            dispatcher,
            marker_retention_ms,
            tombstone_retention_ms,
            Arc::new(|| Utc::now().timestamp_millis()),
        )
    }

    pub fn with_clock(
        dispatcher: Arc<EventDispatcher>,
        marker_retention_ms: i64,
        tombstone_retention_ms: i64,
        now_ms: Clock,
    ) -> Self {
        Self {
            dispatcher,
            marker_retention_ms,
            tombstone_retention_ms,
            now_ms,
        }
    }

    /// `(marker_cutoff_ms, tombstone_cutoff_ms)` for `now`. `saturating_sub` keeps it total: a clock
    /// with `now < retention` yields a far-negative cutoff — below every real timestamp, i.e.
    /// "nothing expired" (the safe direction) — rather than overflowing.
    fn cutoffs(&self, now_ms: i64) -> (i64, i64) {
        (
            now_ms.saturating_sub(self.marker_retention_ms),
            now_ms.saturating_sub(self.tombstone_retention_ms),
        )
    }
}

#[async_trait]
impl Sweeper for MergeGcSweeper {
    async fn run_once(&self) {
        let (marker_cutoff_ms, tombstone_cutoff_ms) = self.cutoffs((self.now_ms)());
        self.dispatcher
            .route_merge_gc(marker_cutoff_ms, tombstone_cutoff_ms)
            .await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::partitions::{OffsetTracker, PartitionRouter};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::{CohortStore, OffloadConfig, OffloadMode, StoreConfig, StoreHandle};
    use crate::workers::MergeWorkerDeps;

    fn dispatcher() -> (TempDir, Arc<EventDispatcher>) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let handle = StoreHandle::new(
            store,
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        );
        let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([])));
        let sink: Arc<dyn MembershipSink> = Arc::new(CaptureSink::new());
        let dispatcher = EventDispatcher::new(
            PartitionRouter::new(64),
            Arc::new(OffsetTracker::new()),
            handle,
            catalog,
            sink,
            MergeWorkerDeps::capture(),
        );
        (dir, Arc::new(dispatcher))
    }

    #[test]
    fn cutoffs_subtract_each_retention_floor_from_now() {
        let (_dir, dispatcher) = dispatcher();
        let sweeper = MergeGcSweeper::new(dispatcher, 1_000, 3_000);
        assert_eq!(sweeper.cutoffs(10_000), (9_000, 7_000));
    }

    #[test]
    fn cutoffs_saturate_when_retention_exceeds_now() {
        let (_dir, dispatcher) = dispatcher();
        let sweeper = MergeGcSweeper::new(dispatcher, i64::MAX, i64::MAX);
        let (marker, tombstone) = sweeper.cutoffs(0);
        assert!(
            marker < 0 && tombstone < 0,
            "far-negative = nothing expired"
        );
    }

    #[tokio::test]
    async fn run_once_routes_to_owned_partitions_without_panicking() {
        let (_dir, dispatcher) = dispatcher();
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let sweeper = MergeGcSweeper::with_clock(
            dispatcher.clone(),
            1_000,
            3_000,
            Arc::new(|| 1_700_000_000_000),
        );
        sweeper.run_once().await;
    }

    #[tokio::test]
    async fn run_once_with_no_owned_partitions_is_a_noop() {
        let (_dir, dispatcher) = dispatcher();
        let sweeper = MergeGcSweeper::new(dispatcher, 1_000, 3_000);
        sweeper.run_once().await;
    }
}
