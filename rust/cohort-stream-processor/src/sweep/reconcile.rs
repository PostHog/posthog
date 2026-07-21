//! Periodic bounded-progress ticks for admitted reconcile snapshots.

use std::sync::Arc;

use async_trait::async_trait;

use crate::consumers::events::EventDispatcher;
use crate::sweep::Sweeper;
use crate::workers::ReconcileBacklog;

/// Routes one reconcile page to each active partition only while this pod owns queued work.
pub struct ReconcileDrainSweeper {
    dispatcher: Arc<EventDispatcher>,
    backlog: Arc<ReconcileBacklog>,
}

impl ReconcileDrainSweeper {
    pub fn new(dispatcher: Arc<EventDispatcher>, backlog: Arc<ReconcileBacklog>) -> Self {
        Self {
            dispatcher,
            backlog,
        }
    }

    fn has_work(&self) -> bool {
        !self.backlog.is_empty()
    }
}

#[async_trait]
impl Sweeper for ReconcileDrainSweeper {
    async fn run_once(&self) {
        if !self.has_work() {
            return;
        }
        // B6's live-lag pause belongs here, before fan-out, so admitted jobs keep their deferred
        // offsets while maintenance reads are paused without waking every partition worker.
        self.dispatcher.route_reconcile_drain().await;
    }
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;
    use uuid::Uuid;

    use cohort_core::filters::{CohortId, TeamId};
    use cohort_core::seed::{BehavioralShapeHash, ReconcileTile, RunId};

    use crate::filters::{CatalogHandle, FilterCatalog};
    use crate::partitions::{OffsetTracker, PartitionRouter};
    use crate::producer::{CaptureSink, MembershipSink};
    use crate::store::{CohortStore, OffloadConfig, OffloadMode, StoreConfig, StoreHandle};
    use crate::workers::reconcile::ReconcileQueue;
    use crate::workers::MergeWorkerDeps;

    use super::*;

    fn dispatcher() -> (TempDir, Arc<EventDispatcher>, StoreHandle) {
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
            handle.clone(),
            catalog,
            sink,
            MergeWorkerDeps::capture(),
        );
        (dir, Arc::new(dispatcher), handle)
    }

    #[tokio::test]
    async fn idle_short_circuit_arms_only_while_a_job_is_owned() {
        let (_dir, dispatcher, handle) = dispatcher();
        let backlog = Arc::new(ReconcileBacklog::default());
        let sweeper = ReconcileDrainSweeper::new(dispatcher, backlog.clone());
        assert!(!sweeper.has_work());
        sweeper.run_once().await;

        let tracker = OffsetTracker::new();
        tracker.mark_dispatched(0, 6);
        let mut queue = ReconcileQueue::new(0, backlog, handle);
        queue.enqueue(
            ReconcileTile::new(
                TeamId(7),
                CohortId(1),
                BehavioralShapeHash::parse("shape-v1").unwrap(),
                RunId(Uuid::nil()),
            ),
            tracker.defer(0, 5),
        );

        assert!(sweeper.has_work());
        sweeper.run_once().await;
        drop(queue);
        assert!(!sweeper.has_work());
    }
}
