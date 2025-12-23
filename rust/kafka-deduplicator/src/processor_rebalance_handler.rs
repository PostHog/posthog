use anyhow::Result;
use async_trait::async_trait;
use dashmap::DashSet;
use rdkafka::TopicPartitionList;
use std::sync::Arc;
use tracing::{error, info};

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::{shutdown_workers, PartitionRouter};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::store_manager::StoreManager;

/// Rebalance handler that coordinates store cleanup and partition workers
pub struct ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    router: Option<Arc<PartitionRouter<T, P>>>,
    offset_tracker: Arc<OffsetTracker>,
    /// Partitions pending cleanup - added on revoke, removed on assign
    /// This tracks which partitions should be cleaned up vs which were re-assigned
    pending_cleanup: DashSet<Partition>,
}

impl<T, P> ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(store_manager: Arc<StoreManager>, offset_tracker: Arc<OffsetTracker>) -> Self {
        Self {
            store_manager,
            router: None,
            offset_tracker,
            pending_cleanup: DashSet::new(),
        }
    }

    pub fn with_router(
        store_manager: Arc<StoreManager>,
        router: Arc<PartitionRouter<T, P>>,
        offset_tracker: Arc<OffsetTracker>,
    ) -> Self {
        Self {
            store_manager,
            router: Some(router),
            offset_tracker,
            pending_cleanup: DashSet::new(),
        }
    }
}

#[async_trait]
impl<T, P> RebalanceHandler for ProcessorRebalanceHandler<T, P>
where
    T: Send + Sync + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    // ============================================
    // SETUP METHODS - Called synchronously within librdkafka callbacks
    // These run BEFORE messages can arrive/stop
    // ============================================

    fn setup_assigned_partitions(&self, partitions: &TopicPartitionList) {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!(
            "Setting up {} assigned partitions (sync)",
            partition_infos.len()
        );

        // Remove from pending cleanup - if partition was revoked then re-assigned,
        // the async cleanup should skip it
        for partition in &partition_infos {
            if self.pending_cleanup.remove(partition).is_some() {
                info!(
                    "Partition {}:{} re-assigned, removing from pending cleanup",
                    partition.topic(),
                    partition.partition_number()
                );
            }
        }

        // Create partition workers BEFORE messages can arrive
        // This is fast - just spawning tokio tasks and creating channels
        // If worker already exists (rapid re-assignment), it will be reused
        if let Some(ref router) = self.router {
            router.add_partitions(&partition_infos);
            info!(
                "Created partition workers. Active workers: {}",
                router.worker_count()
            );
        }
    }

    fn setup_revoked_partitions(&self, partitions: &TopicPartitionList) {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!(
            "Setting up {} revoked partitions (sync)",
            partition_infos.len()
        );

        // Mark partitions as pending cleanup
        // If they get re-assigned before cleanup runs, they'll be removed from this set
        for partition in &partition_infos {
            self.pending_cleanup.insert(partition.clone());
        }

        // Unregister stores from DashMap BEFORE revocation completes
        // This prevents new store creation during shutdown (Step 1 of two-step cleanup)
        // This is fast - just DashMap removes
        for partition in &partition_infos {
            self.store_manager
                .unregister_store(partition.topic(), partition.partition_number());
        }

        info!(
            "Unregistered {} stores. Active stores: {}. Pending cleanup: {}",
            partition_infos.len(),
            self.store_manager.get_active_store_count(),
            self.pending_cleanup.len()
        );
    }

    // ============================================
    // CLEANUP METHODS - Called asynchronously after callbacks return
    // For slow operations like I/O, draining queues, etc.
    // ============================================

    async fn cleanup_assigned_partitions(&self, partitions: &TopicPartitionList) -> Result<()> {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!(
            "Cleaning up {} assigned partitions (async)",
            partition_infos.len()
        );

        // TODO: We should download the checkpoint from S3 here
        // We should not allow the processor to start until the checkpoint is downloaded

        // Pre-create stores for assigned partitions
        // This reduces latency on the first message batch by having the store ready
        // If messages arrive before this completes, get_or_create in the processor
        // will handle it and emit a warning (indicating pre-creation didn't complete in time)
        for partition in &partition_infos {
            match self
                .store_manager
                .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
                .await
            {
                Ok(_) => {
                    info!(
                        "Pre-created store for partition {}:{}",
                        partition.topic(),
                        partition.partition_number()
                    );
                }
                Err(e) => {
                    error!(
                        "Failed to pre-create store for partition {}:{}: {}",
                        partition.topic(),
                        partition.partition_number(),
                        e
                    );
                    // Don't fail the whole cleanup - the processor will retry on first message
                }
            }
        }

        Ok(())
    }

    async fn cleanup_revoked_partitions(&self, partitions: &TopicPartitionList) -> Result<()> {
        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!(
            "Cleaning up {} revoked partitions (async)",
            partition_infos.len()
        );

        // Only clean up partitions that are still pending cleanup
        // If a partition was re-assigned, it was removed from pending_cleanup
        let partitions_to_cleanup: Vec<Partition> = partition_infos
            .into_iter()
            .filter(|p| {
                let should_cleanup = self.pending_cleanup.remove(p).is_some();
                if !should_cleanup {
                    info!(
                        "Skipping cleanup for {}:{} - partition was re-assigned",
                        p.topic(),
                        p.partition_number()
                    );
                }
                should_cleanup
            })
            .collect();

        if partitions_to_cleanup.is_empty() {
            info!("No partitions to clean up (all were re-assigned)");
            return Ok(());
        }

        // Shutdown partition workers - drain their queues
        // Stores are already removed from map (done in setup_revoked_partitions)
        if let Some(ref router) = self.router {
            let workers = router.remove_partitions(&partitions_to_cleanup);
            shutdown_workers(workers).await;
            info!(
                "Shut down partition workers. Active workers: {}",
                router.worker_count()
            );
        }

        // Clear offset tracking state for revoked partitions
        // This prevents stale offsets from being committed after rebalance
        for partition in &partitions_to_cleanup {
            self.offset_tracker.clear_partition(partition);
            info!(
                "Cleared offset tracker state for partition {}:{}",
                partition.topic(),
                partition.partition_number()
            );
        }

        // Now safe to delete files - workers are shut down (Step 2 of two-step cleanup)
        for partition in &partitions_to_cleanup {
            if let Err(e) = self
                .store_manager
                .cleanup_store_files(partition.topic(), partition.partition_number())
            {
                error!(
                    "Failed to cleanup files for revoked partition {}:{}: {}",
                    partition.topic(),
                    partition.partition_number(),
                    e
                );
            } else {
                info!(
                    "Cleaned up deduplication store files for revoked partition {}:{}",
                    partition.topic(),
                    partition.partition_number()
                );
            }
        }

        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        info!("Pre-rebalance: Preparing for partition changes");

        // Set rebalancing flag to prevent offset commits during rebalance
        self.offset_tracker.set_rebalancing(true);

        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Partition changes complete");

        // Clear rebalancing flag to allow offset commits again
        self.offset_tracker.set_rebalancing(false);

        // Log current stats
        let store_count = self.store_manager.stores().len();
        info!("Active deduplication stores: {}", store_count);

        if let Some(ref router) = self.router {
            info!("Active partition workers: {}", router.worker_count());
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kafka::batch_message::KafkaMessage;
    use crate::kafka::offset_tracker::OffsetTracker;
    use crate::kafka::partition_router::PartitionRouterConfig;
    use crate::store::DeduplicationStoreConfig;
    use rdkafka::Offset;
    use tempfile::TempDir;

    struct TestProcessor;

    #[async_trait]
    impl BatchConsumerProcessor<String> for TestProcessor {
        async fn process_batch(&self, _messages: Vec<KafkaMessage<String>>) -> Result<()> {
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_rebalance_handler_creation() {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let offset_tracker = Arc::new(OffsetTracker::new());

        // Test handler without router
        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(store_manager.clone(), offset_tracker.clone());
        assert!(handler.router.is_none());

        // Test handler with router
        let processor = Arc::new(TestProcessor);
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));
        let handler_with_router =
            ProcessorRebalanceHandler::with_router(store_manager, router.clone(), offset_tracker);
        assert!(handler_with_router.router.is_some());
    }

    #[tokio::test]
    async fn test_rebalance_handler_manages_workers() {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new());
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler =
            ProcessorRebalanceHandler::with_router(store_manager, router.clone(), offset_tracker);

        // Initially no workers
        assert_eq!(router.worker_count(), 0);

        // Assign partitions (sync setup creates workers)
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);
        assert_eq!(router.worker_count(), 2);

        // Revoke one partition (sync setup + async cleanup)
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_revoked_partitions(&revoked);
        handler.cleanup_revoked_partitions(&revoked).await.unwrap();
        assert_eq!(router.worker_count(), 1);

        // Cleanup
        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_rebalance_removes_stores_before_workers_shutdown() {
        // This test verifies the fix for the race condition where:
        // 1. Worker is processing messages during shutdown
        // 2. Worker calls store_manager.get_or_create() which would create a new store
        // 3. store_manager.remove() deletes the directory
        // 4. Worker's write fails with "No such file or directory"
        //
        // The fix ensures stores are removed from the map (in setup_revoked_partitions)
        // BEFORE workers are shut down (in cleanup_revoked_partitions).

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new());
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(
            store_manager.clone(),
            router.clone(),
            offset_tracker,
        );

        // Assign partition and create a store
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);
        assert_eq!(router.worker_count(), 1);

        // Create a store for the partition (simulating what happens during processing)
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Revoke the partition (sync setup removes store from map)
        handler.setup_revoked_partitions(&partitions);
        assert_eq!(store_manager.get_active_store_count(), 0);
        // Worker still exists at this point
        assert_eq!(router.worker_count(), 1);

        // Async cleanup shuts down workers and deletes files
        handler
            .cleanup_revoked_partitions(&partitions)
            .await
            .unwrap();

        // After cleanup:
        // - Worker should be shut down
        // - Files should be deleted
        assert_eq!(router.worker_count(), 0);

        // Verify files are deleted
        let partition_dir = temp_dir.path().join("test-topic_0");
        assert!(
            !partition_dir.exists(),
            "Partition directory should be deleted after revocation"
        );
    }

    #[tokio::test]
    async fn test_rebalance_store_not_found_during_shutdown() {
        // This test verifies that after stores are removed from the map,
        // any attempt to get_or_create will return an error rather than
        // creating a new store that would be immediately deleted.

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));

        // Create a store
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Unregister store (Step 1 of two-step cleanup)
        store_manager.unregister_store("test-topic", 0);
        assert_eq!(store_manager.get_active_store_count(), 0);

        // Verify we can still create a new store if needed
        // (this would happen if partition is re-assigned)
        store_manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(store_manager.get_active_store_count(), 1);

        // Cleanup
        store_manager.remove("test-topic", 0).unwrap();
    }

    #[tokio::test]
    async fn test_rapid_revoke_assign_does_not_remove_new_worker() {
        // This test verifies that when a partition is rapidly revoked and re-assigned,
        // the cleanup for the revocation does NOT remove the newly created worker.
        //
        // Scenario:
        // 1. Partition 0 is assigned (worker created)
        // 2. Partition 0 is revoked (store removed from map)
        // 3. Partition 0 is immediately re-assigned (NEW worker created)
        // 4. Async cleanup for step 2 runs - should NOT remove the new worker

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new());
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(
            store_manager.clone(),
            router.clone(),
            offset_tracker,
        );

        // Step 1: Initial assignment
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);
        assert_eq!(router.worker_count(), 1);

        // Step 2: Revoke (sync - removes store from map)
        handler.setup_revoked_partitions(&partitions);

        // Step 3: Immediate re-assign (sync - creates NEW worker)
        handler.setup_assigned_partitions(&partitions);
        assert_eq!(router.worker_count(), 1); // Still have 1 worker (the new one)

        // Step 4: Async cleanup for the revoke runs
        // This should detect that partition 0 is now assigned and skip cleanup
        handler
            .cleanup_revoked_partitions(&partitions)
            .await
            .unwrap();

        // The new worker should still exist!
        assert_eq!(
            router.worker_count(),
            1,
            "New worker should NOT be removed by stale revocation cleanup"
        );

        // Cleanup
        let workers = router.shutdown_all();
        shutdown_workers(workers).await;
    }

    #[tokio::test]
    async fn test_cleanup_store_files_after_unregister_store() {
        // Test the two-step cleanup process:
        // Step 1: unregister_store() - closes RocksDB, removes from map
        // Step 2: cleanup_store_files() - deletes files from disk

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store_manager = Arc::new(StoreManager::new(store_config));

        // Create a store (this creates the directory)
        store_manager.get_or_create("test-topic", 0).await.unwrap();

        let partition_dir = temp_dir.path().join("test-topic_0");
        assert!(partition_dir.exists(), "Partition directory should exist");

        // Step 1: Unregister store (store is dropped, RocksDB is closed)
        store_manager.unregister_store("test-topic", 0);
        assert_eq!(store_manager.get_active_store_count(), 0);

        // Directory should still exist (files not deleted yet)
        assert!(
            partition_dir.exists(),
            "Partition directory should still exist after unregister_store"
        );

        // Step 2: Cleanup the files
        store_manager.cleanup_store_files("test-topic", 0).unwrap();

        // Directory should be deleted
        assert!(
            !partition_dir.exists(),
            "Partition directory should be deleted after cleanup_store_files"
        );
    }
}
