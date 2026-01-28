use std::sync::{Arc, Mutex};

use anyhow::Result;
use async_trait::async_trait;
use futures::future::join_all;
use rdkafka::TopicPartitionList;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

use crate::checkpoint::import::CheckpointImporter;
use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_context::{ConsumerCommand, ConsumerCommandSender};
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::partition_router::{shutdown_workers, PartitionRouter};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;
use crate::metrics_const::{
    PARTITION_STORE_FALLBACK_EMPTY, PARTITION_STORE_SETUP_SKIPPED, REBALANCE_ASYNC_SETUP_CANCELLED,
    REBALANCE_CHECKPOINT_IMPORT_COUNTER, REBALANCE_RESUME_SKIPPED_NO_OWNED,
};
use crate::rebalance_coordinator::RebalanceCoordinator;
use crate::store_manager::StoreManager;

/// Rebalance handler that coordinates store cleanup and partition workers.
///
/// Partition ownership is tracked in RebalanceCoordinator (the single source of truth).
/// This handler updates ownership and uses it to determine which partitions to
/// resume and which to cleanup.
pub struct ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    rebalance_coordinator: Arc<RebalanceCoordinator>,
    router: Option<Arc<PartitionRouter<T, P>>>,
    offset_tracker: Arc<OffsetTracker>,
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
            metrics::counter!(
                PARTITION_STORE_SETUP_SKIPPED,
                "reason" => "cancelled",
            )
            .increment(1);
            return;
        }

        // Skip if partition is no longer owned (was revoked during async setup)
        if !self.rebalance_coordinator.is_partition_owned(partition) {
            info!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                "Skipping store creation - partition no longer owned"
            );
            metrics::counter!(
                PARTITION_STORE_SETUP_SKIPPED,
                "reason" => "not_owned",
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

        // Track if checkpoint import was attempted and failed (for fallback metric)
        let mut checkpoint_failure_reason: Option<&str> = None;

        // Try to import checkpoint from S3 directly into store directory
        if let Some(ref importer) = self.checkpoint_importer {
            // Check cancellation before starting potentially long S3 download
            if cancel_token.is_cancelled() {
                metrics::counter!(
                    PARTITION_STORE_SETUP_SKIPPED,
                    "reason" => "cancelled",
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
                        metrics::counter!(
                            PARTITION_STORE_SETUP_SKIPPED,
                            "reason" => "cancelled",
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

                            // Checkpoint restored successfully - no need for fallback
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
                                "Failed to restore checkpoint - will create empty store",
                            );
                            checkpoint_failure_reason = Some("restore");
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
                        "Failed to import checkpoint - will create empty store"
                    );
                    checkpoint_failure_reason = Some("import");
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
            metrics::counter!(
                PARTITION_STORE_SETUP_SKIPPED,
                "reason" => "cancelled",
            )
            .increment(1);
            return;
        }

        // Create the store (empty if checkpoint import failed)
        match self
            .store_manager
            .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
            .await
        {
            Ok(_) => {
                // Track if this is a fallback to empty store after checkpoint failure
                if let Some(reason) = checkpoint_failure_reason {
                    metrics::counter!(
                        PARTITION_STORE_FALLBACK_EMPTY,
                        "checkpoint_failure_reason" => reason,
                    )
                    .increment(1);
                    warn!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        checkpoint_failure_reason = reason,
                        "Created empty store after checkpoint failure - deduplication quality degraded"
                    );
                }
            }
            Err(e) => {
                error!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    error = %e,
                    "Failed to create store - processor will retry on first message"
                );
                // Don't fail - the processor will retry on first message
            }
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
            partition_count = partition_infos.len(),
            caller = "assign_callback",
            "Setting up assigned partitions (sync)"
        );

        // Cancel any inflight async work from a previous rebalance.
        // This prevents wasted work when partitions are rapidly reassigned.
        {
            let mut token = self.current_rebalance_token.lock().unwrap();
            token.cancel();
            // Create a new token for this rebalance
            *token = CancellationToken::new();
        }

        // Add to owned partitions (coordinator is the source of truth)
        // If partition was revoked then re-assigned, this adds it back
        self.rebalance_coordinator
            .add_owned_partitions(&partition_infos);

        // Create partition workers BEFORE messages can arrive
        // This is fast - just spawning tokio tasks and creating channels
        // If worker already exists (rapid re-assignment), it will be reused
        if let Some(ref router) = self.router {
            router.add_partitions(&partition_infos);
            debug!(
                worker_count = router.worker_count(),
                "Created partition workers"
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
            partition_count = partition_infos.len(),
            caller = "revoke_callback",
            "Setting up revoked partitions (sync)"
        );

        // Remove from owned partitions (coordinator is the source of truth)
        // This happens BEFORE async cleanup, so cleanup can check ownership
        self.rebalance_coordinator
            .remove_owned_partitions(&partition_infos);

        // Unregister stores from DashMap BEFORE revocation completes
        // This prevents new store creation during shutdown (Step 1 of two-step cleanup)
        // This is fast - just DashMap removes
        for partition in &partition_infos {
            self.store_manager
                .unregister_store(partition.topic(), partition.partition_number());
        }

        debug!(
            unregistered_count = partition_infos.len(),
            active_stores = self.store_manager.get_active_store_count(),
            "Unregistered stores for revoked partitions"
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

        debug!(
            incremental_partitions = partition_infos.len(),
            current_owned = self.rebalance_coordinator.get_owned_partitions().len(),
            is_cancelled = cancel_token.is_cancelled(),
            "Async setup starting"
        );

        // If cancelled before starting, return early - new rebalance will handle everything
        // This is safe because:
        // 1. New rebalance's sync callback already updated ownership
        // 2. New rebalance's async_setup will resume ALL owned partitions
        if cancel_token.is_cancelled() {
            info!("Async setup cancelled before starting - new rebalance will handle resume");
            metrics::counter!(REBALANCE_ASYNC_SETUP_CANCELLED).increment(1);
            return Ok(());
        }

        // Pre-create stores for assigned partitions in parallel (scatter)
        // Partitions are paused, so no messages will be delivered until we resume
        let setup_futures = partition_infos
            .iter()
            .map(|p| self.async_setup_single_partition(p, &cancel_token));
        join_all(setup_futures).await;

        // Check if cancelled during setup
        if cancel_token.is_cancelled() {
            info!("Async setup cancelled during execution - new rebalance will handle resume");
            metrics::counter!(REBALANCE_ASYNC_SETUP_CANCELLED).increment(1);
            return Ok(());
        }

        // Get ALL currently owned partitions from the coordinator
        // This includes partitions from previous rebalances that weren't revoked
        // (the key fix for retained partitions across rebalances)
        let owned_partitions = self.rebalance_coordinator.get_owned_partitions();

        // If no owned partitions, skip sending Resume
        if owned_partitions.is_empty() {
            info!("No owned partitions to resume");
            metrics::counter!(REBALANCE_RESUME_SKIPPED_NO_OWNED).increment(1);
            return Ok(());
        }

        // Build TopicPartitionList from ALL owned partitions
        let mut resume_tpl = TopicPartitionList::new();
        for p in &owned_partitions {
            resume_tpl.add_partition(p.topic(), p.partition_number());
        }

        info!(
            owned_count = owned_partitions.len(),
            "Resuming all owned partitions"
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

        // Only clean up partitions that are NOT currently owned
        // If a partition was re-assigned, it's now owned and shouldn't be cleaned up
        let partitions_to_cleanup = self
            .rebalance_coordinator
            .get_unowned_partitions(&partition_infos);

        let skipped_count = partition_infos.len() - partitions_to_cleanup.len();
        if skipped_count > 0 {
            debug!(
                skipped_reassigned = skipped_count,
                "Skipped cleanup for re-assigned partitions"
            );
        }

        if partitions_to_cleanup.is_empty() {
            info!("No partitions to clean up (all were re-assigned)");
            return Ok(());
        }

        info!(
            cleanup_count = partitions_to_cleanup.len(),
            "Cleaning up revoked partitions (async)"
        );

        // Shutdown partition workers - drain their queues
        // Stores are already removed from map (done in setup_revoked_partitions)
        if let Some(ref router) = self.router {
            let workers = router.remove_partitions(&partitions_to_cleanup);
            shutdown_workers(workers).await;
            debug!(
                active_workers = router.worker_count(),
                "Shut down partition workers"
            );
        }

        // Clear offset tracking state for revoked partitions
        // This prevents stale offsets from being committed after rebalance
        for partition in &partitions_to_cleanup {
            self.offset_tracker.clear_partition(partition);
        }

        // Now safe to delete files - workers are shut down (Step 2 of two-step cleanup)
        for partition in &partitions_to_cleanup {
            if let Err(e) = self
                .store_manager
                .cleanup_store_files(partition.topic(), partition.partition_number())
            {
                error!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    error = %e,
                    "Failed to cleanup files for revoked partition"
                );
            }
        }

        info!(
            cleaned_count = partitions_to_cleanup.len(),
            "Revoked partition cleanup completed"
        );

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
    async fn test_cancelled_async_setup_does_not_resume() {
        // Test that async_setup_assigned_partitions does NOT send Resume when cancelled.
        // The new rebalance will handle resuming all owned partitions.
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

        // Cancel the token (simulating a new rebalance starting)
        let current_token = {
            let token = handler.current_rebalance_token.lock().unwrap();
            token.clone()
        };
        current_token.cancel();

        // Async setup should return early without sending Resume
        // The new rebalance will handle resuming all owned partitions
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Should NOT have received a Resume command (cancelled setup defers to new rebalance)
        assert!(
            rx.try_recv().is_err(),
            "Cancelled setup should NOT send Resume - new rebalance handles it"
        );
    }

    #[tokio::test]
    async fn test_resume_only_owned_partitions() {
        // Test that async_setup_assigned_partitions resumes only owned partitions.
        // Simulates a race condition where revoke callback runs AFTER sync setup
        // but BEFORE async setup. We pass the ORIGINAL assignment list to async setup
        // (containing a now-revoked partition) to verify ownership filtering works.
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
                coordinator.clone(),
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

        // Verify ownership via coordinator
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 2)));

        // Revoke partition 1 (removes from ownership)
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Verify partition 1 is no longer owned
        assert!(!coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));

        // Now do async setup - should resume only owned partitions (0 and 2)
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Check that Resume command contains only owned partitions
        let command = rx.try_recv().expect("Should have received a command");
        match command {
            ConsumerCommand::Resume(resume_partitions) => {
                assert_eq!(
                    resume_partitions.count(),
                    2,
                    "Resume command should only contain owned partitions (0 and 2)"
                );
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
                    "Partition 1 should NOT be in Resume (not owned)"
                );
            }
        }

        // Verify stores
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for partition 0 should exist"
        );
        assert!(
            store_manager.get("test-topic", 1).is_none(),
            "Store for partition 1 should NOT exist"
        );
        assert!(
            store_manager.get("test-topic", 2).is_some(),
            "Store for partition 2 should exist"
        );
    }

    #[tokio::test]
    async fn test_resume_skipped_when_no_owned_partitions() {
        // Test that Resume is skipped entirely when no partitions are owned
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
                store_manager,
                coordinator.clone(),
                offset_tracker,
                None,
            );

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // Assign partition 0
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));

        // Revoke partition 0 (no longer owned)
        handler.setup_revoked_partitions(&partitions);
        assert!(!coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));

        // Now do async setup - should skip Resume entirely (no owned partitions)
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Should NOT have received a Resume command (no owned partitions)
        assert!(
            rx.try_recv().is_err(),
            "Should NOT have received a Resume command when no partitions are owned"
        );
    }

    #[tokio::test]
    async fn test_async_setup_skips_store_creation_for_unowned_partition() {
        // Test that async_setup_single_partition skips store creation
        // when the partition is no longer owned (was revoked during async setup).
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
                coordinator.clone(),
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

        // Verify ownership via coordinator
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));

        // Before async setup, revoke partition 1 (simulating overlapping rebalance)
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Verify partition 1 is no longer owned
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));
        assert!(!coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));

        // Now run async setup - should skip store creation for partition 1
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        // Verify: store for partition 0 should exist (still owned)
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for partition 0 should exist (owned)"
        );

        // Verify: store for partition 1 should NOT exist (not owned, creation skipped)
        assert!(
            store_manager.get("test-topic", 1).is_none(),
            "Store for partition 1 should NOT exist (not owned, creation skipped)"
        );

        // Verify: the partition directory should not exist either
        let partition_1_dir = temp_dir.path().join("test-topic_1");
        assert!(
            !partition_1_dir.exists(),
            "Partition 1 directory should not exist (store creation was skipped)"
        );
    }

    #[tokio::test]
    async fn test_retained_partition_across_rebalance() {
        // KEY TEST: Verifies that partitions retained across rebalances are resumed.
        // Scenario: Rebalance A assigns [0, 1], then Rebalance B revokes [1] and assigns []
        // (partition 0 is retained). Partition 0 should be resumed by Rebalance B.
        //
        // This is a COMPLETE end-to-end test: A completes fully, then B interrupts.
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
                coordinator.clone(),
                offset_tracker,
                None,
            );

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // ==================== REBALANCE A ====================
        // Rebalance A: Assign [0, 1] - SYNC
        let mut partitions_a = rdkafka::TopicPartitionList::new();
        partitions_a
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        partitions_a
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_assigned_partitions(&partitions_a);

        // Verify both owned
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));

        // Rebalance A: Complete async setup - creates stores and sends Resume
        handler
            .async_setup_assigned_partitions(&partitions_a, &tx)
            .await
            .unwrap();

        // Verify A's stores were created
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "A should have created store for partition 0"
        );
        assert!(
            store_manager.get("test-topic", 1).is_some(),
            "A should have created store for partition 1"
        );

        // Drain A's Resume command
        let _ = rx.try_recv().expect("A should have sent Resume");

        // ==================== REBALANCE B ====================
        // Rebalance B starts - revoke partition 1
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Verify store 1 was unregistered (but partition 0's store still exists)
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for partition 0 should still exist"
        );
        assert!(
            store_manager.get("test-topic", 1).is_none(),
            "Store for partition 1 should be unregistered"
        );

        // Rebalance B: Assign empty (no new partitions, partition 0 is retained)
        let partitions_b = rdkafka::TopicPartitionList::new();
        handler.setup_assigned_partitions(&partitions_b); // This cancels A's token

        // Verify: partition 0 still owned, partition 1 not owned
        assert!(coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 0)));
        assert!(!coordinator.is_partition_owned(&Partition::new("test-topic".to_string(), 1)));

        // Rebalance B's async setup with empty list - should still resume partition 0!
        handler
            .async_setup_assigned_partitions(&partitions_b, &tx)
            .await
            .unwrap();

        // Should resume partition 0 (still owned) but not partition 1 (revoked)
        let command = rx
            .try_recv()
            .expect("Should have received Resume for retained partition");
        match command {
            ConsumerCommand::Resume(tpl) => {
                assert_eq!(tpl.count(), 1, "Should resume exactly 1 partition");
                let elements = tpl.elements();
                assert_eq!(elements[0].partition(), 0, "Should resume partition 0");
            }
        }

        // Verify partition 0's store still exists after B completes
        assert!(
            store_manager.get("test-topic", 0).is_some(),
            "Store for retained partition 0 should still exist"
        );
    }

    #[tokio::test]
    async fn test_ownership_across_multiple_topics() {
        // Verify ownership tracking works correctly across multiple topics
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
                coordinator.clone(),
                offset_tracker,
                None,
            );

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // Assign partitions from two different topics
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("topic-a", 0, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("topic-a", 1, Offset::Beginning)
            .unwrap();
        partitions
            .add_partition_offset("topic-b", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Verify all owned
        assert!(coordinator.is_partition_owned(&Partition::new("topic-a".to_string(), 0)));
        assert!(coordinator.is_partition_owned(&Partition::new("topic-a".to_string(), 1)));
        assert!(coordinator.is_partition_owned(&Partition::new("topic-b".to_string(), 0)));
        assert_eq!(coordinator.owned_partition_count(), 3);

        // Revoke topic-a partition 1 only
        let mut revoked = rdkafka::TopicPartitionList::new();
        revoked
            .add_partition_offset("topic-a", 1, Offset::Beginning)
            .unwrap();
        handler.setup_revoked_partitions(&revoked);

        // Verify correct ownership
        assert!(coordinator.is_partition_owned(&Partition::new("topic-a".to_string(), 0)));
        assert!(!coordinator.is_partition_owned(&Partition::new("topic-a".to_string(), 1)));
        assert!(coordinator.is_partition_owned(&Partition::new("topic-b".to_string(), 0)));
        assert_eq!(coordinator.owned_partition_count(), 2);

        // Complete async setup - should resume only owned partitions
        handler
            .async_setup_assigned_partitions(&partitions, &tx)
            .await
            .unwrap();

        let command = rx.try_recv().expect("Should have received Resume");
        match command {
            ConsumerCommand::Resume(tpl) => {
                assert_eq!(tpl.count(), 2, "Should resume 2 partitions");
                let elements = tpl.elements();
                let topics: Vec<&str> = elements.iter().map(|e| e.topic()).collect();
                assert!(topics.contains(&"topic-a"), "topic-a:0 should be resumed");
                assert!(topics.contains(&"topic-b"), "topic-b:0 should be resumed");
            }
        }

        // Verify stores created for owned partitions only
        assert!(store_manager.get("topic-a", 0).is_some());
        assert!(store_manager.get("topic-a", 1).is_none());
        assert!(store_manager.get("topic-b", 0).is_some());
    }
}
