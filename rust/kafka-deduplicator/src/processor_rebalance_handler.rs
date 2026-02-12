use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use futures::future::{join_all, Shared};
use rdkafka::TopicPartitionList;
use tokio::task::JoinHandle;
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
    CHECKPOINT_IMPORT_CANCELLED_CLEANUP_COUNTER, PARTITION_STORE_FALLBACK_EMPTY,
    PARTITION_STORE_SETUP_SKIPPED, REBALANCE_CHECKPOINT_IMPORT_COUNTER,
    REBALANCE_PARTITION_STATE_CHANGE, REBALANCE_RESUME_SKIPPED_NO_OWNED,
};
use crate::rebalance_tracker::RebalanceTracker;
use crate::store_manager::StoreManager;

/// Type alias for the shared task handle. The closure maps JoinHandle's Result to ()
/// so it can be Clone (required by Shared).
type SharedTaskHandle =
    Shared<futures::future::Map<JoinHandle<()>, fn(Result<(), tokio::task::JoinError>) -> ()>>;

/// Tracks a partition setup task with its cancellation token.
///
/// The `Shared` future allows multiple async_setup calls to await the same task.
/// The `CancellationToken` allows cancelling ONLY this partition's download on revoke.
struct PartitionSetupTask {
    /// None = claimed but task not yet spawned, Some = task spawned and awaitable
    handle: Option<SharedTaskHandle>,
    cancel_token: CancellationToken,
}

/// Coordinates store cleanup and partition workers across rebalances.
///
/// Ownership lives in RebalanceTracker. This handler updates it and drives resume vs cleanup.
/// Setup tasks are tracked here (not in RebalanceTracker): only this handler spawns/awaits them
/// and needs StoreManager to detect stale entries.
pub struct ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    store_manager: Arc<StoreManager>,
    rebalance_tracker: Arc<RebalanceTracker>,
    router: Option<Arc<PartitionRouter<T, P>>>,
    offset_tracker: Arc<OffsetTracker>,
    checkpoint_importer: Option<Arc<CheckpointImporter>>,
    /// Max parallel directory deletions during rebalance cleanup
    rebalance_cleanup_parallelism: usize,
    /// In-flight checkpoint import tasks (per partition). Cancel on revoke; await before resume; stale entries allow re-claim.
    partition_setup_tasks: DashMap<Partition, PartitionSetupTask>,
    /// Reason a partition got a fallback empty store (no_importer | import_failed | import_cancelled) for metrics.
    partition_fallback_reasons: Arc<DashMap<Partition, &'static str>>,
}

impl<T, P> ProcessorRebalanceHandler<T, P>
where
    T: Send + 'static,
    P: BatchConsumerProcessor<T> + 'static,
{
    pub fn new(
        store_manager: Arc<StoreManager>,
        rebalance_tracker: Arc<RebalanceTracker>,
        offset_tracker: Arc<OffsetTracker>,
        checkpoint_importer: Option<Arc<CheckpointImporter>>,
        rebalance_cleanup_parallelism: usize,
    ) -> Self {
        Self {
            store_manager,
            rebalance_tracker,
            router: None,
            offset_tracker,
            checkpoint_importer,
            rebalance_cleanup_parallelism,
            partition_setup_tasks: DashMap::new(),
            partition_fallback_reasons: Arc::new(DashMap::new()),
        }
    }

    pub fn with_router(
        store_manager: Arc<StoreManager>,
        rebalance_tracker: Arc<RebalanceTracker>,
        router: Arc<PartitionRouter<T, P>>,
        offset_tracker: Arc<OffsetTracker>,
        checkpoint_importer: Option<Arc<CheckpointImporter>>,
        rebalance_cleanup_parallelism: usize,
    ) -> Self {
        Self {
            store_manager,
            rebalance_tracker,
            router: Some(router),
            offset_tracker,
            checkpoint_importer,
            rebalance_cleanup_parallelism,
            partition_setup_tasks: DashMap::new(),
            partition_fallback_reasons: Arc::new(DashMap::new()),
        }
    }

    // ============================================
    // PARTITION SETUP TASK TRACKING
    // ============================================

    /// Claim a partition for setup (fresh or by replacing a stale entry).
    /// Returns false if a store already exists or a task is still running.
    /// Stale = task finished but no store (revoke/fail/cancel); we replace it to retry import.
    fn try_claim_partition_setup(
        &self,
        partition: &Partition,
        cancel_token: CancellationToken,
    ) -> bool {
        match self.partition_setup_tasks.entry(partition.clone()) {
            Entry::Vacant(e) => {
                // Fresh claim - no existing entry
                e.insert(PartitionSetupTask {
                    handle: None,
                    cancel_token,
                });
                true
            }
            Entry::Occupied(mut e) => {
                let task = e.get();
                let store_exists = self
                    .store_manager
                    .get(partition.topic(), partition.partition_number())
                    .is_some();

                // peek() returns Some if resolved, None if still pending
                let task_completed = task
                    .handle
                    .as_ref()
                    .map(|h| h.peek().is_some())
                    .unwrap_or(false); // None = not spawned yet, treat as running

                if store_exists {
                    // Task succeeded, keep entry
                    false
                } else if task_completed {
                    // Task completed but no store → stale entry (task bailed), safe to replace
                    e.get().cancel_token.cancel();
                    e.insert(PartitionSetupTask {
                        handle: None,
                        cancel_token,
                    });
                    debug!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        "Replaced stale setup task entry (task completed, no store)"
                    );
                    true
                } else {
                    // Task still running, let it finish
                    debug!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        "Setup task already in progress, skipping"
                    );
                    false
                }
            }
        }
    }

    /// Attach task handle after spawn (call only when try_claim_partition_setup returned true). Shared so multiple callers can await.
    fn finalize_partition_setup(&self, partition: &Partition, handle: JoinHandle<()>) {
        use futures::future::FutureExt;

        // Helper function to discard JoinHandle result (must be fn, not closure, for type matching)
        fn discard_result(_: Result<(), tokio::task::JoinError>) {}

        if let Some(mut task) = self.partition_setup_tasks.get_mut(partition) {
            // Map the JoinHandle result to () so it's Clone (required for Shared)
            let shared_handle = handle.map(discard_result as fn(_) -> ()).shared();
            task.handle = Some(shared_handle);
        }
    }

    /// Setup task handle for a partition (None if not yet finalized or missing). Clone is awaitable by multiple callers.
    fn get_setup_task(&self, partition: &Partition) -> Option<SharedTaskHandle> {
        self.partition_setup_tasks
            .get(partition)
            .and_then(|t| t.handle.clone())
    }

    /// Cancel and remove setup tasks for revoked partitions (stops in-flight S3 downloads).
    fn cancel_setup_tasks(&self, partitions: &[Partition]) {
        for partition in partitions {
            if let Some((_, task)) = self.partition_setup_tasks.remove(partition) {
                // Cancel the token - S3 download will stop at next chunk
                task.cancel_token.cancel();
                // Handle is dropped, task continues but we won't wait for it
            }
            self.partition_fallback_reasons.remove(partition);
        }
    }

    /// Remove setup task entry after awaiting (cleanup).
    fn complete_setup_task(&self, partition: &Partition) {
        self.partition_setup_tasks.remove(partition);
    }

    // ============================================
    // PARTITION SETUP TASK SPAWNING
    // ============================================

    /// Spawn checkpoint import for one partition. Per-partition cancel token stops S3 on revoke.
    /// Fallback empty store is created in finalize_rebalance_cycle. Partial/orphan files: importer
    /// deletes dir at start; orphan cleaner handles cancelled downloads.
    fn spawn_partition_setup_task(
        &self,
        partition: Partition,
        cancel_token: CancellationToken,
    ) -> tokio::task::JoinHandle<()> {
        let store_manager = self.store_manager.clone();
        let coordinator = self.rebalance_tracker.clone();
        let importer = self.checkpoint_importer.clone();
        let fallback_reasons = Arc::clone(&self.partition_fallback_reasons);

        tokio::spawn(async move {
            // === CHECKPOINT 1: Before starting ===
            if cancel_token.is_cancelled() || !coordinator.is_partition_owned(&partition) {
                metrics::counter!(
                    PARTITION_STORE_SETUP_SKIPPED,
                    "reason" => if cancel_token.is_cancelled() { "cancelled" } else { "not_owned" },
                )
                .increment(1);
                fallback_reasons.insert(partition.clone(), "import_cancelled");
                return;
            }

            // Skip if store already exists (handles rapid revoke→assign race)
            if store_manager
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

            // Try checkpoint import WITH per-partition cancellation token
            // RAII cleanup guard handles partial downloads on failure/timeout/cancel
            // Fallback empty store creation is handled centrally at resume time.
            if let Some(ref importer) = importer {
                match importer
                    .import_checkpoint_for_topic_partition_cancellable(
                        partition.topic(),
                        partition.partition_number(),
                        Some(&cancel_token), // Per-partition token - stops S3 download on revoke
                    )
                    .await
                {
                    Ok(path) => {
                        // === CHECKPOINT 2: After download completes ===
                        // Check if we should skip registration (token cancelled or ownership lost)
                        let is_cancelled = cancel_token.is_cancelled();
                        let is_owned = coordinator.is_partition_owned(&partition);

                        if is_cancelled || !is_owned {
                            let reason = if is_cancelled {
                                "cancelled"
                            } else {
                                "not_owned"
                            };
                            metrics::counter!(
                                PARTITION_STORE_SETUP_SKIPPED,
                                "reason" => reason,
                            )
                            .increment(1);
                            fallback_reasons.insert(partition.clone(), "import_cancelled");

                            // Clean up the successfully imported directory since we can't use it.
                            // With unique Utc::now() timestamps, each import attempt creates a new path,
                            // so there's no collision risk with a new task - it will create its own directory.
                            if path.exists() {
                                match std::fs::remove_dir_all(&path) {
                                    Ok(_) => {
                                        metrics::counter!(
                                            CHECKPOINT_IMPORT_CANCELLED_CLEANUP_COUNTER,
                                            "result" => "success",
                                        )
                                        .increment(1);
                                        info!(
                                            topic = partition.topic(),
                                            partition = partition.partition_number(),
                                            path = %path.display(),
                                            reason = reason,
                                            "Cleaned up unused checkpoint import"
                                        );
                                    }
                                    Err(e) => {
                                        metrics::counter!(
                                            CHECKPOINT_IMPORT_CANCELLED_CLEANUP_COUNTER,
                                            "result" => "failed",
                                        )
                                        .increment(1);
                                        warn!(
                                            topic = partition.topic(),
                                            partition = partition.partition_number(),
                                            path = %path.display(),
                                            error = %e,
                                            "Failed to clean up checkpoint import, orphan cleaner will handle it"
                                        );
                                    }
                                }
                            }
                            return;
                        }

                        // Register imported store
                        match store_manager.restore_imported_store(
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
                                    "Failed to restore checkpoint"
                                );
                                fallback_reasons.insert(partition.clone(), "import_failed");
                            }
                        }
                    }
                    Err(e) => {
                        // Only log if not cancelled (expected during revoke)
                        if !cancel_token.is_cancelled() {
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
                                "Failed to import checkpoint"
                            );
                            fallback_reasons.insert(partition.clone(), "import_failed");
                        } else {
                            fallback_reasons.insert(partition.clone(), "import_cancelled");
                        }
                    }
                }
            } else {
                metrics::counter!(
                    REBALANCE_CHECKPOINT_IMPORT_COUNTER,
                    "result" => "skipped",
                    "reason" => "disabled",
                )
                .increment(1);
                fallback_reasons.insert(partition.clone(), "no_importer");
            }
        })
    }

    /// End of rebalance cycle (counter 0 or we're last): await all import tasks; if no new rebalance,
    /// create fallback stores for owned partitions without stores, delete unowned dirs, resume consumption.
    /// When `we_are_finalizing_last`, we were called before decrement (count still 1); proceed only if count == 1
    /// so is_rebalancing() stays true during finalize and orphan/capacity cleanup skips.
    async fn finalize_rebalance_cycle(
        &self,
        consumer_command_tx: &ConsumerCommandSender,
        we_are_finalizing_last: bool,
    ) -> Result<()> {
        info!("Finalizing rebalance cycle - awaiting import tasks");

        // Step 1: Await all pending import tasks in parallel
        let owned_partitions = self.rebalance_tracker.get_owned_partitions();
        let task_futures: Vec<(Partition, SharedTaskHandle)> = owned_partitions
            .iter()
            .filter_map(|p| {
                let p = p.clone();
                self.get_setup_task(&p).map(|h| (p, h))
            })
            .collect();
        let (partitions, handles): (Vec<_>, Vec<_>) = task_futures.into_iter().unzip();
        let _ = join_all(handles).await; // Ignore panic results - tasks handle their own errors
        for partition in &partitions {
            self.complete_setup_task(partition);
        }

        // Snapshot owned before count check to avoid TOCTOU if a new rebalance starts; steps 3–5 use this snapshot.
        let owned = self.rebalance_tracker.get_owned_partitions();

        // Step 2: If new rebalance started while awaiting, skip. (we_are_finalizing_last: proceed iff count == 1; else iff count == 0.)
        let count = self.rebalance_tracker.rebalancing_count();
        let should_skip = if we_are_finalizing_last {
            count != 1
        } else {
            count != 0
        };
        if should_skip {
            info!("New rebalance started during finalize - skipping fallback stores, cleanup and resume");
            return Ok(());
        }

        // Step 3: Create fallback stores for any owned partitions that don't have a registered store
        // This handles cases where checkpoint import failed, was cancelled, or was disabled
        for partition in &owned {
            if self
                .store_manager
                .get(partition.topic(), partition.partition_number())
                .is_none()
            {
                let reason = self
                    .partition_fallback_reasons
                    .remove(partition)
                    .map(|(_, r)| r)
                    .unwrap_or("unknown");
                match self
                    .store_manager
                    .get_or_create_for_rebalance(partition.topic(), partition.partition_number())
                    .await
                {
                    Ok(_) => {
                        metrics::counter!(PARTITION_STORE_FALLBACK_EMPTY, "reason" => reason)
                            .increment(1);
                        warn!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            reason = reason,
                            "Created fallback empty store - deduplication quality may be degraded"
                        );
                    }
                    Err(e) => {
                        error!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            error = %e,
                            "Failed to create fallback store - processor will retry on first message"
                        );
                    }
                }
            }
        }

        // Step 4: Delete unowned partition dirs (scan disk; delete anything not in owned). Catches orphans.
        if let Err(e) = self
            .store_manager
            .cleanup_unowned_partition_directories(&owned, self.rebalance_cleanup_parallelism)
            .await
        {
            warn!(
                error = %e,
                "Partition directory cleanup failed - orphan cleaner will handle it"
            );
        }

        // Step 5: Resume consumption
        if owned.is_empty() {
            info!("No owned partitions to resume");
            metrics::counter!(REBALANCE_RESUME_SKIPPED_NO_OWNED).increment(1);
        } else {
            let mut resume_tpl = TopicPartitionList::new();
            for p in &owned {
                resume_tpl.add_partition(p.topic(), p.partition_number());
            }
            info!(
                owned_count = owned.len(),
                "Resuming all owned partitions (rebalance cycle complete)"
            );
            if let Err(e) = consumer_command_tx.send(ConsumerCommand::Resume(resume_tpl)) {
                error!("Failed to send resume command after store setup: {}", e);
                return Err(anyhow::anyhow!("Failed to send resume command: {}", e));
            }
        }

        Ok(())
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

        // Record per-partition assignment metrics for observability
        for partition in &partition_infos {
            metrics::counter!(
                REBALANCE_PARTITION_STATE_CHANGE,
                "topic" => partition.topic().to_string(),
                "partition" => partition.partition_number().to_string(),
                "op" => "assign",
            )
            .increment(1);
        }

        // Add to owned partitions FIRST (coordinator is the source of truth)
        // If partition was revoked then re-assigned, this adds it back
        self.rebalance_tracker
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
        self.rebalance_tracker.start_rebalancing();

        // NOTE: Per-partition setup tasks are spawned in async_setup_assigned_partitions,
        // not here (sync callback can't do async work like checkpoint import)
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

        // Record per-partition revocation metrics for observability
        for partition in &partition_infos {
            metrics::counter!(
                REBALANCE_PARTITION_STATE_CHANGE,
                "topic" => partition.topic().to_string(),
                "partition" => partition.partition_number().to_string(),
                "op" => "revoke",
            )
            .increment(1);
        }

        // Remove from owned partitions (coordinator is the source of truth)
        // This happens BEFORE async cleanup, so cleanup can check ownership
        self.rebalance_tracker
            .remove_owned_partitions(&partition_infos);

        // CANCEL and remove setup tasks for revoked partitions
        // This immediately cancels any in-flight S3 downloads to save cost/time
        // Tasks will also check is_partition_owned() as a backup
        self.cancel_setup_tasks(&partition_infos);

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
        consumer_command_tx: &ConsumerCommandSender,
    ) -> Result<()> {
        // Get ALL owned partitions (not just incremental from this rebalance)
        // This handles retained partitions across overlapping rebalances
        let owned_partitions = self.rebalance_tracker.get_owned_partitions();

        debug!(
            owned_count = owned_partitions.len(),
            "Async setup starting - spawning tasks for owned partitions"
        );

        // Spawn setup tasks for partitions that don't have one yet.
        // Uses atomic two-phase registration to prevent race conditions where overlapping
        // rebalances could both spawn tasks for the same partition.
        // NOTE: We do NOT await these tasks here - that's deferred to finalize_rebalance_cycle
        for partition in &owned_partitions {
            let cancel_token = CancellationToken::new();
            // Atomically claim the partition - if stale entry exists, it will be replaced
            if self.try_claim_partition_setup(partition, cancel_token.clone()) {
                // We claimed it - now spawn the task and finalize registration
                let handle =
                    self.spawn_partition_setup_task(partition.clone(), cancel_token.clone());
                self.finalize_partition_setup(partition, handle);
            }
            // If claim failed, either a store exists or a task is still running
        }

        // If we're the last rebalance (count == 1), run finalize BEFORE decrementing so is_rebalancing()
        // stays true during finalize. That prevents orphan/capacity cleanup from deleting dirs we're setting up.
        let is_last = self.rebalance_tracker.rebalancing_count() == 1;
        if is_last {
            self.finalize_rebalance_cycle(consumer_command_tx, true)
                .await?;
            self.rebalance_tracker.finish_rebalancing();
        } else {
            self.rebalance_tracker.finish_rebalancing();
            if !self.rebalance_tracker.is_rebalancing() {
                self.finalize_rebalance_cycle(consumer_command_tx, false)
                    .await?;
            } else {
                debug!(
                    "Rebalance async setup complete, but other rebalances still in progress - deferring finalize"
                );
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

        // Only clean up partitions that are NOT currently owned
        // If a partition was re-assigned, it's now owned and shouldn't be cleaned up
        let partitions_to_cleanup = self
            .rebalance_tracker
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

        // File cleanup is handled by finalize_rebalance_cycle at end of the rebalance cycle.
        // This uses disk scan + owned_partitions to delete unowned directories.

        info!(
            cleaned_count = partitions_to_cleanup.len(),
            "Revoked partition cleanup completed (files will be cleaned at end of cycle)"
        );

        Ok(())
    }

    async fn on_pre_rebalance(&self) -> Result<()> {
        // Note: rebalance_tracker.start_rebalancing() is called in setup_assigned_partitions()
        // (sync callback) to ensure no gap before async work is queued.
        // The rebalance_tracker's counter is the single source of truth.
        Ok(())
    }

    async fn on_post_rebalance(&self) -> Result<()> {
        info!("Post-rebalance: Sync callbacks complete, async cleanup may continue");
        // Note: rebalance_tracker counter is decremented via finish_rebalancing()
        // at the end of async_setup_assigned_partitions.
        // The rebalance_tracker's rebalancing counter is the single source of truth.

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
    use crate::test_utils::create_test_tracker;
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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        // Test handler without router
        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker.clone(),
                None,
                16, // rebalance_cleanup_parallelism
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
            16, // rebalance_cleanup_parallelism
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
        let coordinator = create_test_tracker();
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
            16, // rebalance_cleanup_parallelism
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
        // This test verifies that stores are removed from the map (in setup_revoked_partitions)
        // BEFORE workers are shut down (in cleanup_revoked_partitions).
        //
        // Note: File cleanup is handled by finalize_rebalance_cycle at end of cycle,
        // NOT during cleanup_revoked_partitions. This avoids race conditions with rapid revoke→assign.

        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_tracker();
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
            16, // rebalance_cleanup_parallelism
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

        // Async cleanup shuts down workers (files are deleted in finalize_rebalance_cycle)
        handler
            .cleanup_revoked_partitions(&partitions)
            .await
            .unwrap();

        // After cleanup:
        // - Worker should be shut down
        // - Store should be unregistered from map
        // - Files still exist (will be cleaned in finalize_rebalance_cycle)
        assert_eq!(router.worker_count(), 0);

        // Files are NOT immediately deleted - finalize_rebalance_cycle handles this
        let partition_dir = temp_dir.path().join("test-topic_0");
        assert!(
            partition_dir.exists(),
            "Partition directory still exists (orphan cleaner will handle cleanup)"
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
        let coordinator = create_test_tracker();
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
        let coordinator = create_test_tracker();
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
            16, // rebalance_cleanup_parallelism
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
        let coordinator = create_test_tracker();
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
    async fn test_per_partition_task_cancellation() {
        // Test that revoke cancels the per-partition setup task
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager,
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
            );

        // First assignment
        let mut partitions = rdkafka::TopicPartitionList::new();
        partitions
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();

        handler.setup_assigned_partitions(&partitions);

        // Verify partition is owned
        let p0 = Partition::new("test-topic".to_string(), 0);
        assert!(
            coordinator.is_partition_owned(&p0),
            "Partition should be owned after assign"
        );

        // Revoke should remove ownership and cancel any setup tasks
        handler.setup_revoked_partitions(&partitions);

        // Verify partition is no longer owned
        assert!(
            !coordinator.is_partition_owned(&p0),
            "Partition should not be owned after revoke"
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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator,
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
    async fn test_overlapping_rebalances_only_last_sends_resume() {
        // Test that when multiple rebalances overlap, only the last one sends Resume.
        // This tests the counter-based coordination.
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager,
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
            );

        // Create command channel
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

        // First rebalance - assign partition 0
        let mut partitions_a = rdkafka::TopicPartitionList::new();
        partitions_a
            .add_partition_offset("test-topic", 0, Offset::Beginning)
            .unwrap();
        handler.setup_assigned_partitions(&partitions_a);

        // Second rebalance - assign partition 1 (overlapping, before A's async completes)
        let mut partitions_b = rdkafka::TopicPartitionList::new();
        partitions_b
            .add_partition_offset("test-topic", 1, Offset::Beginning)
            .unwrap();
        handler.setup_assigned_partitions(&partitions_b);

        // Counter should be 2 (two rebalances in progress)
        assert!(
            coordinator.is_rebalancing(),
            "Should be rebalancing with counter > 0"
        );

        // First async setup completes - should NOT send Resume (counter still > 0)
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

        // No Resume yet (counter is still 1)
        // Give a moment for any potential Resume to be sent
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;

        // Counter should be 1 now
        assert!(
            coordinator.is_rebalancing(),
            "Should still be rebalancing (one more to go)"
        );

        // Second async setup completes - should send Resume (counter == 0)
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

        // Should have received exactly one Resume command (from the last rebalance)
        let cmd = rx.try_recv().expect("Should have received Resume command");
        let ConsumerCommand::Resume(tpl) = cmd;
        // Should resume both partitions
        assert_eq!(tpl.count(), 2, "Should resume all owned partitions");

        // No more commands
        assert!(
            rx.try_recv().is_err(),
            "Should only receive one Resume command"
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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager,
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
        let coordinator = create_test_tracker();
        let store_manager = Arc::new(StoreManager::new(store_config, coordinator.clone()));
        let offset_tracker = Arc::new(OffsetTracker::new(coordinator.clone()));

        let handler: ProcessorRebalanceHandler<String, TestProcessor> =
            ProcessorRebalanceHandler::new(
                store_manager.clone(),
                coordinator.clone(),
                offset_tracker,
                None,
                16, // rebalance_cleanup_parallelism
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
        handler.async_setup_assigned_partitions(&tx).await.unwrap();

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
