//! Periodic pending-transfer redrive tick.
//!
//! Each tick routes a `RedrivePendingTransfers` to every owned partition's worker, which
//! re-produces any `cf_pending_transfers` entries stranded by inline-retry exhaustion.

use std::sync::Arc;

use async_trait::async_trait;

use crate::consumers::events::EventDispatcher;
use crate::sweep::Sweeper;

/// A [`Sweeper`] that routes a redrive tick to every owned partition each cycle.
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
