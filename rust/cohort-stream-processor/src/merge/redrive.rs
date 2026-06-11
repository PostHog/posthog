//! [`RedriveSweeper`]: the periodic pending-transfer redrive tick (TDD §4.5.1, D3).
//!
//! Lives in the merge module — not [`crate::sweep`] — so the sweep stays merge-free; it reuses
//! only the sweep's timer ([`run_sweep_loop`](crate::sweep::run_sweep_loop)) and its [`Sweeper`]
//! seam. Each tick routes a [`RedrivePendingTransfers`](crate::partitions::shuffle_message::ShuffleMessage::RedrivePendingTransfers)
//! to every owned partition's worker, which re-produces any `cf_pending_transfers` entries
//! stranded by inline-retry exhaustion (see
//! [`handle_redrive`](crate::workers::merge_path::handle_redrive)).

use std::sync::Arc;

use async_trait::async_trait;

use crate::consumers::events::EventDispatcher;
use crate::sweep::Sweeper;

/// A [`Sweeper`] that routes a redrive tick to every owned partition each cycle. Carries no clock —
/// unlike the eviction sweep there is no cutoff to compute; the worker's outbox scan is the whole
/// tick. The no-spawn / benign-`RouteError` reasoning lives on
/// [`EventDispatcher::route_redrive`].
pub struct RedriveSweeper {
    dispatcher: Arc<EventDispatcher>,
}

impl RedriveSweeper {
    pub fn new(dispatcher: Arc<EventDispatcher>) -> Self {
        Self { dispatcher }
    }
}

#[async_trait]
impl Sweeper for RedriveSweeper {
    async fn run_once(&self) {
        self.dispatcher.route_redrive().await;
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
    use crate::workers::MergeWorkerDeps;

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
            MergeWorkerDeps::capture(),
        );
        (dir, Arc::new(dispatcher))
    }

    #[tokio::test]
    async fn run_once_routes_to_owned_partitions_without_panicking() {
        // Owned partitions with no spawned worker: each tick is a benign dropped RouteError (no
        // worker ⇒ nothing was staged this tenure), so run_once must complete cleanly.
        let (_dir, dispatcher) = dispatcher();
        dispatcher.assign_partition(0);
        dispatcher.assign_partition(1);

        let sweeper = RedriveSweeper::new(dispatcher.clone());
        sweeper.run_once().await;
    }

    #[tokio::test]
    async fn run_once_with_no_owned_partitions_is_a_noop() {
        let (_dir, dispatcher) = dispatcher();
        let sweeper = RedriveSweeper::new(dispatcher);
        sweeper.run_once().await;
    }
}
