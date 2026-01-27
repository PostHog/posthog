use std::sync::{Arc, Mutex};

use anyhow::Result;
use async_trait::async_trait;
use dashmap::DashSet;
use futures::future::join_all;
use rdkafka::TopicPartitionList;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

use crate::checkpoint::import::CheckpointImporter;
use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_context::{ConsumerCommand, ConsumerCommandSender};
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::{shutdown_workers, PartitionRouter};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::metrics_const::{
    REBALANCE_CHECKPOINT_IMPORT_COUNTER, REBALANCE_RESUME_PARTITIONS_FILTERED,
    REBALANCE_RESUME_SKIPPED_ALL_REVOKED,
};
use crate::rebalance_coordinator::RebalanceCoordinator;
use crate::store_manager::StoreManager;

/// Rebalance handler that coordinates store cleanup and partition workers
pub struct ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    rebalance_coordinator: Arc<RebalanceCoordinator>,
    router: Option<Arc<PartitionRouter<T, P>>>,
    offset_tracker: Arc<OffsetTracker>,
    /// Partitions pending cleanup - added on revoke, removed on assign
    /// This tracks which partitions should be cleaned up vs which were re-assigned
    pending_cleanup: DashSet<Partition>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    /// Cancellation token for the current rebalance's async work.
    /// When a new rebalance starts, the old token is cancelled and a new one is created.
    /// This allows cancelling inflight checkpoint imports when partitions are reassigned.
    current_rebalance_token: Mutex<CancellationToken>,
}

impl<T, P> ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(
        store_manager: Arc<StoreManager>,
        rebalance_coordinator: Arc<RebalanceCoordinator>,
        offset_tracker: Arc<OffsetTracker>,
        checkpoint_importer: Option<Arc<CheckpointImporter>>,
    ) -> Self {
        Self {
            store_manager,
            rebalance_coordinator,
            router: None,
            offset_tracker,
            pending_cleanup: DashSet::new(),
            checkpoint_importer,
            current_rebalance_token: Mutex::new(CancellationToken::new()),
        }
    }

    pub fn with_router(
        store_manager: Arc<StoreManager>,
        rebalance_coordinator: Arc<RebalanceCoordinator>,
        router: Arc<PartitionRouter<T, P>>,
        offset_tracker: Arc<OffsetTracker>,
        checkpoint_importer: Option<Arc<CheckpointImporter>>,
    ) -> Self {
        Self {
            store_manager,
            rebalance_coordinator,
            router: Some(router),
            offset_tracker,
            pending_cleanup: DashSet::new(),
            checkpoint_importer,
            current_rebalance_token: Mutex::new(CancellationToken::new()),
        }
    }

    /// Set up a single partition: import checkpoint and create store.
    /// This is called concurrently for all assigned partitions.
    ///
    /// The cancellation token is checked before expensive operations.
    /// If cancelled (due to a new rebalance), the function returns early.
    async fn async_setup_single_partition(
        &self,
        partition: &Partition,
        cancel_token: &CancellationToken,
    ) {
        // Check if cancelled before starting
        if cancel_token.is_cancelled() {
            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                "Checkpoint import cancelled - new rebalance started"
            );
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "cancelled",
            )
            .increment(1);
            return;
        }

        // Skip if partition was revoked during async setup (it's in pending_cleanup)
        if self.pending_cleanup.contains(partition) {
            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                "Skipping store creation - partition was revoked during async setup"
            );
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "skipped",
                "reason" => "partition_revoked",
            )
            .increment(1);
            return;
        }

        // Skip if store already exists
        if self
            .store_manager
            .get(partition.topic(), partition.partition_number())
            .is_some()
        {
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "skipped",
                "reason" => "store_exists",
            )
            .increment(1);
            return;
        }

        // Try to import checkpoint from S3 directly into store directory
        if let Some(ref importer) = self.checkpoint_importer {
            // Check cancellation before starting potentially long S3 download
            if cancel_token.is_cancelled() {
                info!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    "Checkpoint import cancelled before S3 download - new rebalance started"
                );
                metrics::counter!(
                    REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                    "result" => "cancelled",
                )
                .increment(1);
                return;
            }

            match importer
                .import_checkpoint_for_topic_partition_cancellable(
                    partition.topic(),
                    partition.partition_number(),
                    Some(cancel_token),
                )
                .await
            {
                Ok(path) => {
                    // Check cancellation after S3 download completes
                    if cancel_token.is_cancelled() {
                        info!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            "Checkpoint import cancelled after S3 download - new rebalance started"
                        );
                        metrics::counter!(
                            REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                            "result" => "cancelled",
                        )
                        .increment(1);
                        // Clean up the downloaded files since we won't use them
                        match tokio::fs::remove_dir_all(&path).await {
                            Ok(_) => {}
                            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                            Err(e) => {
                                warn!(
                                    "Failed to clean up cancelled checkpoint download at {}: {}",
                                    path.display(),
                                    e
                                );
                            }
                        }
                        return;
                    }

                    // OK now we need to register the new store with the manager
                    match self.store_manager.restore_imported_store(
                        partition.topic(),
                        partition.partition_number(),
                        &path,
                    ) {
                        Ok(_) => {
                            metrics::counter!(
                                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                                "result" => "success",
                            )
                            .increment(1);
                            info!(
                                topic = partition.topic(),
                                partition = partition.partition_number(),
                                path = %path.display(),
                                "Imported checkpoint for partition"
                            );

                            // no need to fall through to get-or-create flow
                            return;
                        }
                        Err(e) => {
                            metrics::counter!(
                                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                                "result" => "failed",
                                "reason" => "restore",
                            )
                            .increment(1);
                            error!(
                                topic = partition.topic(),
                                partition = partition.partition_number(),
                                error = %e,
                                "Failed to restore checkpoint",
                            );
                        }
                    }
                }
                Err(e) => {
                    metrics::counter!(
                        REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                        "result" => "failed",
                        "reason" => "import",
                    )
                    .increment(1);
                    warn!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        error = %e,
                        "Failed to import checkpoint for partition"
                    );
                }
            }
        } else {
            metrics::counter!(
                REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                "result" => "skipped",
                "reason" => "disabled",
            )
            .increment(1);
        }

        // Check cancellation before creating store
        if cancel_token.is_cancelled() {
            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                "Store creation cancelled - new rebalance started"
            );
            return;
        }

        // Create the store (will use imported checkpoint files if present)
        if let Err(e) = self
            .store_manager
            .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
            .await
        {
            error!(
                "Failed to pre-create store for partition {}:{}: {}",
                partition.topic(),
                partition.partition_number(),
                e
            );
            // Don't fail - the processor will retry on first message
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

        // Cancel any inflight async work from a previous rebalance.
        // This prevents wasted work when partitions are rapidly reassigned.
        {
            let mut token = self.current_rebalance_token.lock().unwrap();
            token.cancel();
            info!("Cancelling any in-flight async rebalance work");
            // Create a new token for this rebalance
            *token = CancellationToken::new();
        }

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

        // Increment rebalancing counter SYNCHRONOUSLY before async work is queued
        // This ensures no gap where orphan cleanup could run
        self.rebalance_coordinator.start_rebalancing();
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

    async fn async_setup_assigned_partitions(
        &self,
        partitions: &TopicPartitionList,
        consumer_command_tx: &ConsumerCommandSender,
    ) -> Result<()> {
        // Create guard that will decrement rebalancing counter on drop (even on panic)
        // This ensures cleanup happens even if this function panics or is cancelled
        let _rebalancing_guard = self.rebalance_coordinator.rebalancing_guard();

        // Get a clone of the cancellation token for this rebalance.
        // If a new rebalance starts, this token will be cancelled.
        let cancel_token = {
            let token = self.current_rebalance_token.lock().unwrap();
            token.clone()
        };

        let partition_infos: Vec<Partition> = partitions
            .elements()
            .into_iter()
            .map(Partition::from)
            .collect();

        info!(
            "Setting up {} assigned partitions (async) - partitions are PAUSED until stores are ready",
            partition_infos.len()
        );

        // Check if already cancelled before starting work
        if cancel_token.is_cancelled() {
            info!("Async partition setup cancelled before starting - new rebalance occurred");
            // Don't send resume - the new rebalance will handle it
            return Ok(());
        }

        // Pre-create stores for assigned partitions in parallel (scatter)
        // Partitions are paused, so no messages will be delivered until we resume
        let setup_futures = partition_infos
            .iter()
            .map(|p| self.async_setup_single_partition(p, &cancel_token));
        join_all(setup_futures).await;

        // Check if cancelled after all setup completed
        // If cancelled, a new rebalance started and will handle resuming
        if cancel_token.is_cancelled() {
            info!(
                "Async partition setup cancelled after completion - not sending resume (new rebalance will handle it)"
            );
            return Ok(());
        }

        // Filter out partitions that were revoked during async setup
        // (they're in pending_cleanup, meaning they were revoked and shouldn't be resumed)
        let owned_partitions: Vec<&Partition> = partition_infos
            .iter()
            .filter(|p| !self.pending_cleanup.contains(*p))
            .collect();

        let filtered_count = partition_infos.len() - owned_partitions.len();
        if filtered_count > 0 {
            info!(
                filtered_count = filtered_count,
                remaining_count = owned_partitions.len(),
                "Filtered revoked partitions from Resume command"
            );
            metrics::counter!(REBALANCE_RESUME_PARTITIONS_FILTERED)
                .increment(filtered_count as u64);
        }

        // If all partitions were revoked, skip sending Resume entirely
        if owned_partitions.is_empty() {
            info!("All assigned partitions were revoked during async setup - skipping resume");
            metrics::counter!(REBALANCE_RESUME_SKIPPED_ALL_REVOKED).increment(1);
            return Ok(());
        }

        // Build TopicPartitionList from owned partitions only
        let mut resume_tpl = TopicPartitionList::new();
        for p in &owned_partitions {
            resume_tpl.add_partition(p.topic(), p.partition_number());
        }

        info!(
            "All {} stores ready - sending resume command to consumer",
            owned_partitions.len()
        );

        if let Err(e) = consumer_command_tx.send(ConsumerCommand::Resume(resume_tpl)) {
            error!("Failed to send resume command after store setup: {}", e);
            return Err(anyhow::anyhow!("Failed to send resume command: {}", e));
        }

        // Guard automatically decrements rebalancing counter when dropped here
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
        // Note: rebalance_coordinator.start_rebalancing() is called in setup_assigned_partitions()
        // (sync callback) to ensure no gap before async work is queued.
        // The rebalance_coordinator's counter is the single source of truth.
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Sync callbacks complete, async cleanup may continue");
        // Note: rebalance_coordinator counter is decremented via RebalancingGuard
        // at the end of async_setup_assigned_partitions (ensures panic safety).
        // The rebalance_coordinator's rebalancing counter is the single source of truth.

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
    use crate::test_utils::create_test_coordinator;
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
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        // Test handler without router
        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker.clone(),
                None,
            );
        assert!(handler.router.is_none());

        // Test handler with router
        let processor = Arc::new(TestProcessor);
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));
        let handler_with_router = ProcessorRebalanceHandler::with_router(
            store_manager,
            coordinator,
            router.clone(),
            offset_tracker,
            None,
        );
        assert!(handler_with_router.router.is_some());
    }

    #[tokio::test]
    async fn test_rebalance_handler_manages_workers() {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(
            store_manager,
            coordinator,
            router.clone(),
            offset_tracker,
            None,
        );

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
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(
            store_manager.clone(),
            coordinator,
            router.clone(),
            offset_tracker,
            None,
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
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator));

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
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let processor = Arc::new(TestProcessor);
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));
        let router = Arc::new(PartitionRouter::new(
            processor,
            offset_tracker.clone(),
            PartitionRouterConfig::default(),
        ));

        let handler = ProcessorRebalanceHandler::with_router(
            store_manager.clone(),
            coordinator,
            router.clone(),
            offset_tracker,
            None,
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
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator));

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

    #[tokio::test]
    async fn test_cancellation_token_cancelled_on_new_rebalance() {
        // Test that calling setup_assigned_partitions cancels the previous token
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(store_manager, coordinator, offset_tracker, None);

        // Get initial token
        let initial_token = {
            let token = handler.current_rebalance_token.lock().unwrap();
            token.clone()
        };
        assert!(
            !initial_token.is_cancelled(),
            "Initial token should not be cancelled"
        );

        // First assignment
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Initial token should now be cancelled
        assert!(
            initial_token.is_cancelled(),
            "Initial token should be cancelled after new rebalance"
        );

        // Get new token
        let new_token = {
            let token = handler.current_rebalance_token.lock().unwrap();
            token.clone()
        };
        assert!(
            !new_token.is_cancelled(),
            "New token should not be cancelled"
        );

        // Another rebalance should cancel the new token
        handler.setup_assigned_partitions(&partitions);
        assert!(
            new_token.is_cancelled(),
            "New token should be cancelled after another rebalance"
        );
    }

    #[tokio::test]
    async fn test_async_setup_sends_resume_command() {
        // Test that async_setup_assigned_partitions sends a Resume command
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator,
                offset_tracker,
                None,
            );

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // First do sync setup (required before async setup)
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Now do async setup - should send Resume command
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Check that Resume command was sent
        let command = rx.try_recv().expect("Should have received a command");
        match command {
            ConsumerCommand::Resume(resume_partitions) => {
                assert_eq!(
                    resume_partitions.count(),
                    2,
                    "Resume command should contain all assigned partitions"
                );
            }
        }

        // Verify stores were created
        assert_eq!(
            store_manager.get_active_store_count(),
            2,
            "Two stores should have been created"
        );
    }

    #[tokio::test]
    async fn test_async_setup_skips_resume_when_cancelled() {
        // Test that async_setup_assigned_partitions does NOT send Resume when cancelled
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(store_manager, coordinator, offset_tracker, None);

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // First do sync setup
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Cancel the token before async setup completes (simulating a new rebalance)
        {
            let token = handler.current_rebalance_token.lock().unwrap();
            token.cancel();
        }

        // Create a new token (as would happen in a real rebalance)
        {
            let mut token = handler.current_rebalance_token.lock().unwrap();
            *token = CancellationToken::new();
        }

        // Async setup should detect cancellation and NOT send Resume
        // (But note: the token was already cloned at the start, so this tests
        // the case where cancellation happens BEFORE async_setup_assigned_partitions runs)
        // We need to test the case where the token is already cancelled when the function starts

        // Get the current token and cancel it
        let current_token = {
            let token = handler.current_rebalance_token.lock().unwrap();
            token.clone()
        };
        current_token.cancel();

        // Now async setup should detect cancellation
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Should NOT have received a command (cancelled before sending)
        assert!(
            rx.try_recv().is_err(),
            "Should NOT have received a Resume command when cancelled"
        );
    }

    #[tokio::test]
    async fn test_resume_filters_revoked_partitions() {
        // Test that async_setup_assigned_partitions filters out partitions
        // that were revoked during async setup (are in pending_cleanup)
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator,
                offset_tracker,
                None,
            );

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // Assign partitions 0, 1, 2
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 2, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Simulate partition 1 being revoked during async setup
        // (add it to pending_cleanup as would happen in setup_revoked_partitions)
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Now do async setup - should filter out partition 1 from Resume
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Check that Resume command was sent with only partitions 0 and 2
        let command = rx.try_recv().expect("Should have received a command");
        match command {
            ConsumerCommand::Resume(resume_partitions) => {
                assert_eq!(
                    resume_partitions.count(),
                    2,
                    "Resume command should only contain non-revoked partitions (0 and 2)"
                );
                // Verify the specific partitions
                let elements = resume_partitions.elements();
                let partition_nums: Vec<i32> = elements.iter().map(|e| e.partition()).collect();
                assert!(
                    partition_nums.contains(&0),
                    "Partition 0 should be in Resume"
                );
                assert!(
                    partition_nums.contains(&2),
                    "Partition 2 should be in Resume"
                );
                assert!(
                    !partition_nums.contains(&1),
                    "Partition 1 should NOT be in Resume (was revoked)"
                );
            }
        }

        // Verify only stores for partitions 0 and 2 were created
        // (partition 1 was revoked, so its store was unregistered)
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for partition 0 should exist"
        );
        assert!(
            store_manager.get("test-topic", 1).is_none(),
            "Store for partition 1 should NOT exist (was revoked)"
        );
        assert!(
            store_manager.get("test-topic", 2).is_some(),
            "Store for partition 2 should exist"
        );
    }

    #[tokio::test]
    async fn test_resume_skipped_when_all_partitions_revoked() {
        // Test that Resume is skipped entirely when all assigned partitions
        // were revoked during async setup
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(store_manager, coordinator, offset_tracker, None);

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // Assign partition 0
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Revoke partition 0 (simulating it being reassigned to another consumer)
        handler.setup_revoked_partitions(&partitions);

        // Now do async setup - should skip Resume entirely
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Should NOT have received a Resume command (all partitions were revoked)
        assert!(
            rx.try_recv().is_err(),
            "Should NOT have received a Resume command when all partitions were revoked"
        );
    }

    #[tokio::test]
    async fn test_async_setup_skips_store_creation_for_revoked_partition() {
        // Test that async_setup_single_partition explicitly skips store creation
        // when the partition is in pending_cleanup (was revoked during async setup).
        // This is separate from Resume filtering - we want to verify that no
        // resources are wasted creating stores for partitions we don't own.
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_coordinator();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator,
                offset_tracker,
                None,
            );

        // Create command channel
        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();

        // Assign partitions 0 and 1
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Before async setup, revoke partition 1 (simulating overlapping rebalance)
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Verify partition 1 is in pending_cleanup
        assert!(
            handler
                .pending_cleanup
                .contains(&Partition::new("test-topic".to_string(), 1)),
            "Partition 1 should be in pending_cleanup"
        );

        // Now run async setup - this should skip store creation for partition 1
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Verify: store for partition 0 should exist (was not revoked)
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for partition 0 should exist (not revoked)"
        );

        // Verify: store for partition 1 should NOT exist (was revoked, creation skipped)
        assert!(
            store_manager.get("test-topic", 1).is_none(),
            "Store for partition 1 should NOT exist (revoked during async setup, creation skipped)"
        );

        // Verify: the partition directory should not exist either
        let partition_1_dir = temp_dir.path().join("test-topic_1");
        assert!(
            !partition_1_dir.exists(),
            "Partition 1 directory should not exist (store creation was skipped)"
        );
    }
}
