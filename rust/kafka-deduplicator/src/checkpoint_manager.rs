use std::collections::HashSet;
use std::path::Path;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

use crate::checkpoint::{
    CheckpointConfig, CheckpointExporter, CheckpointMetadata, CheckpointWorker,
};
use crate::kafka::types::Partition;
use crate::metrics_const::CHECKPOINT_STORE_NOT_FOUND_COUNTER;
use crate::store::DeduplicationStore;
use crate::store_manager::StoreManager;

use anyhow::Result;
use chrono::Utc;
use dashmap::DashMap;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

pub enum CheckpointStatus {
    // the partition requesting a checkpoint attempt has acquired
    // the uniqueness lock and the in-flight count was below the max
    // so it is safe to proceed with it's attempt
    Ready,
    // the partition requesting a checkpoint attempt has checked
    // the uniqueness lock and found another attempt is flight.
    // this means it should skip this attempt and let the parent
    // loop continue to the next partition
    InProgress,
    // the partition requesting a checkpoint attempt has checked
    // the uniqueness lock and found the in-flight count was at the max
    // so it must wait for another checkpoint attempt to complete
    Wait,
}

/// Manages checkpointing and periodic flushing for all deduplication stores
pub struct CheckpointManager {
    config: CheckpointConfig,

    /// Reference to the store manager
    store_manager: Arc<StoreManager>,

    // Checkpoint export module - if populated, locally checkpointed partitions will be backed up remotely
    exporter: Option<Arc<CheckpointExporter>>,

    /// Cancellation token for the flush task
    cancel_token: CancellationToken,

    /// Maintains cap on number of concurrent checkpoint attempts in-flight
    /// as well as uniqueness of checkpoint attempts for a given partition
    is_checkpointing: Arc<Mutex<HashSet<Partition>>>,

    /// Handle to the checkpoint task loop
    checkpoint_task: Option<JoinHandle<()>>,
}

impl CheckpointManager {
    /// Create a new checkpoint manager
    pub fn new(
        config: CheckpointConfig,
        store_manager: Arc<StoreManager>,
        exporter: Option<Arc<CheckpointExporter>>,
    ) -> Self {
        info!(
            max_concurrent_checkpoints = config.max_concurrent_checkpoints,
            export_enabled = exporter.is_some(),
            "Creating checkpoint manager",
        );

        Self {
            config,
            store_manager,
            exporter,
            cancel_token: CancellationToken::new(),
            is_checkpointing: Arc::new(Mutex::new(HashSet::new())),
            checkpoint_task: None,
        }
    }

    /// Start the periodic flush task, returning the inner worker
    /// threads' health reporter flag for bubbling up failures
    pub fn start(&mut self) -> Option<Arc<AtomicBool>> {
        if self.checkpoint_task.is_some() {
            warn!("Checkpoint manager already started");
            return None;
        }
        let health_reporter = Arc::new(AtomicBool::new(true));

        info!(
            "Starting checkpoint manager with interval: {:?}",
            self.config.checkpoint_interval
        );

        // clones we can reuse as bases within the checkpoint submission loop
        // without involving "self" and moving it into the loop
        let submit_loop_config = self.config.clone();
        let store_manager = self.store_manager.clone();
        let exporter = self.exporter.clone();
        let cancel_submit_loop_token = self.cancel_token.child_token();

        // loop-local counter for individual worker task logging
        let mut worker_task_id = 1_u32;

        // loop-local state variables
        let is_checkpointing = self.is_checkpointing.clone();
        // Track checkpoint counter and metadata per partition in a single map for atomic updates
        let checkpoint_state: Arc<DashMap<Partition, (u32, CheckpointMetadata)>> =
            Arc::new(DashMap::new());
        let checkpoint_health_reporter = health_reporter.clone();

        let checkpoint_task_handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(submit_loop_config.checkpoint_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            // Skip first tick to avoid immediate flush
            interval.tick().await;

            'outer: loop {
                tokio::select! {
                    _ = cancel_submit_loop_token.cancelled() => {
                        info!("Checkpoint manager: submit loop shutting down");
                        break 'outer;
                    }

                    // the inner loop can block but if we miss a few ticks before
                    // completing the full partition loop, it's OK
                    _ = interval.tick() => {
                        let candidates: Vec<Partition> = store_manager
                            .stores()
                            .iter()
                            .map(|entry| entry.key().clone())
                            .collect();
                        let store_count = candidates.len();
                        if store_count == 0 {
                            debug!("No stores to flush");
                            continue;
                        }
                        info!("Checkpoint manager: attempting checkpoint submission for {} stores", store_count);

                        // Attempt to checkpoint each partitions' backing store in
                        // the candidate list. If the store is no longer owned by
                        // the StoreManager, or a checkpoint is already in-flight
                        // for the given partition, we skip it and continue. If the
                        // gating lock (is_checkpointing) is at max capacity, we block
                        // at this iteration of 'inner loop until the another attempt
                        // completes and a new slot opens up
                        'inner: for partition in candidates {
                            let partition_tag = partition.to_string();

                            // wait for a slot to become available in the gating loop.
                            // if the attempt is cleared to proceed, the is_checkpointing
                            // lock will have atomically registered the partition as in-flight
                            let mut gate_interval = tokio::time::interval(submit_loop_config.checkpoint_gate_interval);
                            'gate: loop {
                                let status = tokio::select! {
                                    _ = cancel_submit_loop_token.cancelled() => {
                                        info!(partition = partition_tag, "Checkpoint manager: checkpoint manager shutting down, skipping");
                                        break 'outer;
                                    }

                                    _ = gate_interval.tick() => {
                                        Self::get_checkpoint_status(&submit_loop_config, &partition, &is_checkpointing).await
                                    }
                                };
                                match status {
                                    CheckpointStatus::Ready => {
                                        debug!(partition = partition_tag, "Checkpoint manager: checkpoint is ready, proceeding");
                                        break 'gate;
                                    }
                                    CheckpointStatus::InProgress => {
                                        debug!(partition = partition_tag, "Checkpoint manager: checkpoint already in progress, skipping");
                                        continue 'inner;
                                    }
                                    CheckpointStatus::Wait => {
                                        debug!(partition = partition_tag, "Checkpoint manager: max in-flight checkpoints reached, waiting for open slot");
                                        // continue into next iter of gate loop since we should not proceed
                                    }
                                }
                            }

                            // clone required manager-owned structures for the next worker instance
                            // to avoid race conditions - the worker must acquire protected values
                            // when the thread executes, and mark it's own completion
                            let worker_is_checkpointing = is_checkpointing.clone();
                            let worker_checkpoint_state = checkpoint_state.clone();
                            let worker_store_manager = store_manager.clone();
                            let worker_exporter = exporter.as_ref().map(|e| e.clone());
                            let worker_cancel_token = cancel_submit_loop_token.child_token();
                            let attempt_timestamp = Utc::now();
                            let worker_local_base_dir = Path::new(&submit_loop_config.local_checkpoint_dir);
                            let worker_full_upload_interval = submit_loop_config.checkpoint_full_upload_interval;
                            let worker_remote_namespace = submit_loop_config.s3_key_prefix.clone();
                            let worker_partition = partition.clone();

                            // create worker with unique task ID and partition target helper
                            worker_task_id += 1;
                            let worker = CheckpointWorker::new(
                                worker_task_id,
                                worker_local_base_dir,
                                worker_remote_namespace,
                                worker_partition,
                                attempt_timestamp,
                                worker_exporter,
                            );

                            // for now, we don't bother to track the handles of spawned workers
                            // because each worker represents one best-effort checkpoint attempt
                            let _result = tokio::spawn(async move {
                                // best effort to bail if the checkpoint manager shut
                                // down before the worker thread started executing...
                                if tokio::time::timeout(Duration::from_millis(1), worker_cancel_token.cancelled()).await.is_ok() {
                                    info!(partition = partition_tag, "Checkpoint worker thread: inner submit loop shutting down, skipping worker execution");
                                    {
                                        let mut is_checkpointing_guard = worker_is_checkpointing.lock().await;
                                        is_checkpointing_guard.remove(&partition);
                                    }
                                    return Ok(None);
                                }

                                // best efort to bail if the partition is no longer owned by the
                                // store manager when the worker thread has started executing
                                let target_store = match worker_store_manager.get(partition.topic(), partition.partition_number()) {
                                    Some(store) => store,

                                    _ => {
                                        metrics::counter!(CHECKPOINT_STORE_NOT_FOUND_COUNTER).increment(1);
                                        warn!(partition = partition_tag, "Checkpoint worker thread: partition no longer owned by store manager, skipping");
                                        // free the slot up since we're skipping this round and/or shutting down the process
                                        {
                                            let mut is_checkpointing_guard = worker_is_checkpointing.lock().await;
                                            is_checkpointing_guard.remove(&partition);
                                        }
                                        return Ok(None);
                                    }
                                };

                                // Get previous checkpoint state (counter and metadata) for this partition.
                                let (counter, prev_metadata) = worker_checkpoint_state
                                    .get(&partition)
                                    .map(|entry| (entry.0, Some(entry.1.clone())))
                                    .unwrap_or((0, None));

                                // Determine if we should perform a full or incremental checkpoint.
                                // Supply CheckpointWorker::checkpoint_partition with last successful
                                // checkpoint attempt on this partition to perform and incremental
                                let mut incremental_or_full: Option<&CheckpointMetadata> = prev_metadata.as_ref();
                                if worker_full_upload_interval == 0 || counter % worker_full_upload_interval == 0 {
                                    info!(
                                        partition = partition_tag,
                                        full_upload_interval = worker_full_upload_interval,
                                        current_index = counter,
                                        "Checkpoint worker thread: performing full checkpoint");
                                    incremental_or_full = None;
                                } else {
                                    info!(
                                        partition = partition_tag,
                                        full_upload_interval = worker_full_upload_interval,
                                        current_index = counter,
                                        "Checkpoint worker thread: performing incremental checkpoint");
                                }

                                // Execute checkpoint operation with previous metadata for deduplication
                                let result = worker.checkpoint_partition(&target_store, incremental_or_full).await;

                                // handle releasing locks and reporting outcome
                                let status = match &result {
                                    Ok(Some(new_checkpoint_info)) => {
                                        // Update counter and metadata atomically on success
                                        worker_checkpoint_state.insert(partition.clone(), (counter + 1, new_checkpoint_info.metadata.clone()));
                                        "success"
                                    },
                                    Ok(None) => "skipped",
                                    Err(e) => {
                                        error!(partition = partition_tag, "Checkpoint worker thread: attempt failed: {}", e);
                                        "error"
                                    },
                                };
                                info!(worker_task_id, partition = partition_tag, result = status,
                                    "Checkpoint worker thread: attempt completed");

                                // release the in-flight lock regardless of outcome to free the slot
                                {
                                    let mut is_checkpointing_guard = worker_is_checkpointing.lock().await;
                                    is_checkpointing_guard.remove(&partition);
                                }

                                result
                            });
                        } // end 'inner partition loop

                        info!("Checkpoint manager: completed checkpoint attempt loop for {} stores", store_count);
                    } // end 'outer interval tick loop
                } // end tokio::select! block
            } // end 'outer loop

            info!("Checkpoint manager: submit loop shutting down");
            checkpoint_health_reporter.store(false, Ordering::SeqCst);
        });
        self.checkpoint_task = Some(checkpoint_task_handle);

        Some(health_reporter.clone())
    }

    /// Stop the checkpoint manager
    pub async fn stop(&mut self) {
        info!("Checkpoint manager: starting graceful shutdown...");

        // Cancel the task
        info!("Checkpoint manager: cancelling checkpoint manager task token...");
        self.cancel_token.cancel();

        // Stop in-flight submissions to the checkpoint workers immediately
        info!("Checkpoint manager: stopping in-flight checkpoint submissions...");
        if let Some(task) = self.checkpoint_task.take() {
            task.abort();
        }

        let mut fail_interval =
            tokio::time::interval(self.config.checkpoint_worker_shutdown_timeout);
        let mut probe_interval = tokio::time::interval(Duration::from_secs(1));
        loop {
            tokio::select! {
                _ = fail_interval.tick() => {
                    warn!("Checkpoint manager: graceful shutdown - timed out awaiting in-flight checkpoints");
                    break;
                }

                _ = probe_interval.tick() => {
                    let inflight_count = self.is_checkpointing.lock().await.len();
                    if inflight_count == 0 {
                        info!("Checkpoint manager: graceful shutdown - in-flight checkpoints completed");
                        break;
                    } else {
                        info!(inflight_count, "Checkpoint manager: graceful shutdown - awaiting in-flight checkpoints...");
                    }
                }
            }
        }

        info!("Checkpoint manager: graceful shutdown completed");
    }

    pub fn export_enabled(&self) -> bool {
        self.exporter.is_some()
    }

    /// Trigger an immediate flush of all stores (currenty used only in tests)
    pub async fn flush_all(&self) -> Result<()> {
        info!("Triggering manual flush of all stores");

        let snapshot: Vec<(Partition, DeduplicationStore)> = self
            .store_manager
            .stores()
            .iter()
            .map(|entry| {
                let (partition, store) = entry.pair();
                (partition.clone(), store.clone())
            })
            .collect();

        let worker_id = 1;
        for (partition, store) in snapshot {
            let worker = CheckpointWorker::new(
                worker_id,
                Path::new(&self.config.local_checkpoint_dir),
                self.config.s3_key_prefix.clone(),
                partition.clone(),
                Utc::now(),
                None,
            );

            worker.checkpoint_partition(&store, None).await?;
        }

        Ok(())
    }

    async fn get_checkpoint_status(
        config: &CheckpointConfig,
        partition: &Partition,
        is_checkpointing: &Arc<Mutex<HashSet<Partition>>>,
    ) -> CheckpointStatus {
        let mut is_checkpointing_guard = is_checkpointing.lock().await;

        if is_checkpointing_guard.contains(partition) {
            return CheckpointStatus::InProgress;
        }

        if is_checkpointing_guard.len() < config.max_concurrent_checkpoints {
            is_checkpointing_guard.insert(partition.clone());
            return CheckpointStatus::Ready;
        }

        CheckpointStatus::Wait
    }
}

impl Drop for CheckpointManager {
    fn drop(&mut self) {
        // Cancel the task on drop
        self.cancel_token.cancel();

        // Stop checkpoint submission loop
        if self.checkpoint_task.is_some() {
            debug!("Checkpoint manager dropped: flush task will terminate");
            if let Some(task) = self.checkpoint_task.take() {
                task.abort();
            }
        }

        // in-flight workers will be interrupted immediately here if they aren't completed
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::checkpoint::{CheckpointPlan, CheckpointUploader};
    use crate::store::{
        DeduplicationStore, DeduplicationStoreConfig, TimestampKey, TimestampMetadata,
    };
    use async_trait::async_trait;
    use common_types::RawEvent;
    use std::{collections::HashMap, path::PathBuf, time::Duration};
    use tempfile::TempDir;

    /// Filesystem-based uploader for testing - copies files to a local export directory
    #[derive(Debug)]
    struct FilesystemUploader {
        export_base_dir: PathBuf,
    }

    impl FilesystemUploader {
        fn new(export_base_dir: PathBuf) -> Self {
            Self { export_base_dir }
        }
    }

    #[async_trait]
    impl CheckpointUploader for FilesystemUploader {
        async fn upload_checkpoint_with_plan(&self, plan: &CheckpointPlan) -> Result<Vec<String>> {
            // simulate remote upload path with local temp dir
            let dest_dir = self
                .export_base_dir
                .join(plan.info.get_remote_attempt_path());
            tokio::fs::create_dir_all(&dest_dir).await?;

            // Upload only new files from local file path to local "upload" dir
            // with remote file path appended, including remote namespace
            let mut uploaded_files = Vec::new();
            for local_file in &plan.files_to_upload {
                let src_filepath = &local_file.local_path;
                let dest_filepath = self
                    .export_base_dir
                    .join(plan.info.get_file_key(&local_file.filename));
                tokio::fs::copy(src_filepath, &dest_filepath).await?;
                uploaded_files.push(dest_filepath.to_string_lossy().to_string());
            }

            // Write metadata.json to local "upload" dir w/remote metadata
            // file path appended, including remote namespace
            let metadata_path = self.export_base_dir.join(plan.info.get_metadata_key());
            let metadata_json = plan.info.metadata.to_json()?;
            tokio::fs::write(&metadata_path, metadata_json.into_bytes()).await?;
            uploaded_files.push(metadata_path.to_string_lossy().to_string());

            Ok(uploaded_files)
        }

        async fn is_available(&self) -> bool {
            true
        }
    }

    fn create_test_store_manager() -> Arc<StoreManager> {
        let config = DeduplicationStoreConfig {
            path: TempDir::new().unwrap().path().to_path_buf(),
            max_capacity: 1_000_000,
        };
        Arc::new(StoreManager::new(config))
    }

    fn create_test_store(topic: &str, partition: i32) -> DeduplicationStore {
        let config = DeduplicationStoreConfig {
            path: TempDir::new().unwrap().path().to_path_buf(),
            max_capacity: 1_000_000,
        };
        DeduplicationStore::new(config.clone(), topic.to_string(), partition).unwrap()
    }

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::now_v7()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String(uuid::Uuid::now_v7().to_string())),
            token: Some(uuid::Uuid::now_v7().to_string()),
            properties: HashMap::new(),
            ..Default::default()
        }
    }

    fn find_local_checkpoint_files(base_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut checkpoint_files = Vec::new();
        let mut stack = vec![base_dir.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let entries = std::fs::read_dir(&current_path)?;

            for entry in entries {
                let entry = entry?;
                let path = entry.path();

                if path.is_file() {
                    checkpoint_files.push(path);
                } else if path.is_dir() {
                    stack.push(path);
                }
            }
        }

        Ok(checkpoint_files)
    }

    #[tokio::test]
    async fn test_checkpoint_manager_creation() {
        let stores = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), stores.clone(), None);

        assert!(manager.checkpoint_task.is_none());
        assert_eq!(manager.config.checkpoint_interval, Duration::from_secs(30));

        assert!(manager.exporter.is_none());
    }

    #[tokio::test]
    async fn test_checkpoint_manager_start_stop() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Start the manager
        manager.start();
        assert!(manager.checkpoint_task.is_some());

        // Stop the manager
        manager.stop().await;
        assert!(manager.checkpoint_task.is_none());
    }

    #[tokio::test]
    async fn test_flush_all_empty() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Flushing empty stores should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_flush_all_with_stores() {
        // Add some test stores
        let store_manager = create_test_store_manager();
        let store1 = create_test_store("flush_all_with_stores", 0);
        let store2 = create_test_store("flush_all_with_stores", 1);

        // Add events to the stores
        let event = create_test_event();
        // Add test data directly to stores
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store1.put_timestamp_record(&key, &metadata).unwrap();
        store2.put_timestamp_record(&key, &metadata).unwrap();

        // add dedup stores to manager
        let stores = store_manager.stores();
        stores.insert(
            Partition::new("flush_all_with_stores".to_string(), 0),
            store1,
        );
        stores.insert(
            Partition::new("flush_all_with_stores".to_string(), 1),
            store2,
        );

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Flush all should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_checkpoint_partition_not_found() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(50),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // no Partition is created and associated with the store manager,
        // so the ChekcpointManager task loop should find no Partitions to
        // execute CheckpointWorkers against
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Should fail for non-existent topic partition.
        // run the manager checkpoint loop for a few cycles
        manager.start();
        tokio::time::sleep(Duration::from_millis(200)).await;
        manager.stop().await;

        // the top-level checkpoints directory will exist in test b/c its a temp dir
        // but no partitions will have been checkpointed so no subdirs or files will exist
        let expected_base_path = Path::new(&config.local_checkpoint_dir);
        assert!(expected_base_path.exists());
        let files_found = find_local_checkpoint_files(expected_base_path).unwrap();
        assert!(files_found.is_empty());
    }

    #[tokio::test]
    async fn test_periodic_flush_and_export_task() {
        let store_manager = create_test_store_manager();
        let store = create_test_store("test_periodic_flush_task", 0);

        // Add an event
        let event1 = create_test_event();
        let key1 = TimestampKey::from(&event1);
        let metadata1 = TimestampMetadata::new(&event1);
        store.put_timestamp_record(&key1, &metadata1).unwrap();
        let event2 = create_test_event();
        let key2 = TimestampKey::from(&event2);
        let metadata2 = TimestampMetadata::new(&event2);
        store.put_timestamp_record(&key2, &metadata2).unwrap();

        // Create manager with short interval for testing and filesystem exporter
        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let tmp_export_dir = TempDir::new().unwrap();

        let uploader = Box::new(FilesystemUploader::new(tmp_export_dir.path().to_path_buf()));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(100),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            s3_key_prefix: "test".to_string(),
            ..Default::default()
        };
        let exporter = Arc::new(CheckpointExporter::new(uploader));

        let partition = Partition::new("test_periodic_flush_task".to_string(), 0);
        let stores = store_manager.stores();
        stores.insert(partition.clone(), store);

        let mut manager =
            CheckpointManager::new(config.clone(), store_manager.clone(), Some(exporter));

        // Start the manager
        let health_reporter = manager.start();
        assert!(health_reporter.is_some());

        // Wait for a few flush cycles
        tokio::time::sleep(Duration::from_millis(200)).await;

        // Stop the manager
        manager.stop().await;

        // service task threads are still healthy and running
        assert!(health_reporter.unwrap().load(Ordering::SeqCst));

        // Verify that files were exported to the export directory
        let export_files = find_local_checkpoint_files(tmp_export_dir.path()).unwrap();
        assert!(!export_files.is_empty());
        assert!(export_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with("CURRENT")));
        assert!(export_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("MANIFEST")));
        assert!(export_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("OPTIONS")));
        assert!(export_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".sst")));
        assert!(export_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".log")));

        // there should be one or more checkpoint attempt directories in the export directory
        let checkpoint_attempts = export_files
            .iter()
            .map(|p| p.parent().unwrap())
            .collect::<HashSet<_>>();
        assert!(!checkpoint_attempts.is_empty());
    }

    #[tokio::test]
    async fn test_double_start() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Start once - should return reporter
        let health_reporter = manager.start();
        assert!(health_reporter.is_some());
        assert!(manager.checkpoint_task.is_some());

        // Start again - should warn but not panic
        let health_reporter = manager.start();
        assert!(health_reporter.is_none());
        assert!(manager.checkpoint_task.is_some());

        manager.stop().await;
    }

    #[tokio::test]
    async fn test_drop_cancels_task() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        manager.start();
        let cancel_token = manager.cancel_token.clone();

        assert!(!cancel_token.is_cancelled());

        // Drop the manager
        drop(manager);

        // Token should be cancelled
        assert!(cancel_token.is_cancelled());
    }

    #[tokio::test]
    async fn test_max_inflight_checkpoints() {
        // Add some test stores
        let store_manager = create_test_store_manager();
        let stores = store_manager.stores();

        for i in 1..=6 {
            let event = create_test_event();
            let part = Partition::new("max_inflight_checkpoints".to_string(), i);
            let store = create_test_store(part.topic(), part.partition_number());
            let key = TimestampKey::from(&event);
            let metadata = TimestampMetadata::new(&event);
            store.put_timestamp_record(&key, &metadata).unwrap();
            stores.insert(part, store);
        }

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let tmp_export_dir = TempDir::new().unwrap();

        // configure moderate checkpoints with reasonable intervals and filesystem exporter
        let uploader = Box::new(FilesystemUploader::new(tmp_export_dir.path().to_path_buf()));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(50), // Submit frequent checkpoints during test run
            max_concurrent_checkpoints: 2,
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            s3_key_prefix: "test".to_string(),
            ..Default::default()
        };
        let exporter = Arc::new(CheckpointExporter::new(uploader));

        // start the manager and produce some exported checkpoint files
        let mut manager =
            CheckpointManager::new(config.clone(), store_manager.clone(), Some(exporter));
        manager.start();

        // Give the manager time to start checkpointing
        tokio::time::sleep(Duration::from_millis(100)).await;

        let mut hit_expected_cap = false;
        let mut never_above_zero = true;
        let start = std::time::Instant::now();
        let timeout = Duration::from_secs(3);

        while start.elapsed() < timeout {
            let inflight = manager.is_checkpointing.lock().await.len();
            if inflight == config.max_concurrent_checkpoints {
                hit_expected_cap = true;
            }
            if inflight > config.max_concurrent_checkpoints {
                panic!("Inflight count exceeded expected cap, got: {inflight}",);
            }
            if inflight == 0 {
                never_above_zero = false;
            }

            // Small sleep to prevent busy waiting
            tokio::time::sleep(Duration::from_millis(10)).await;
        }

        assert!(
            hit_expected_cap,
            "Expected to hit the concurrent checkpoint cap of {}",
            config.max_concurrent_checkpoints
        );
        assert!(
            !never_above_zero,
            "Expected to see some checkpointing activity"
        );

        manager.stop().await;

        let found_files = find_local_checkpoint_files(tmp_export_dir.path()).unwrap();
        assert!(!found_files.is_empty());
    }
}
