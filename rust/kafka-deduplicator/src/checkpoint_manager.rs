use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use tokio::sync::{Mutex, Semaphore};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

use crate::checkpoint::{export::CheckpointExporter, CheckpointConfig};
use crate::kafka::types::Partition;
use crate::store::DeduplicationStore;
use crate::store_manager::StoreManager;

const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";
const CHECKPOINT_FILE_COUNT_HISTOGRAM: &str = "checkpoint_file_count";
const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";
const CHECKPOINT_WORKER_STATUS_COUNTER: &str = "checkpoint_worker_status";

pub const CHECKPOINT_NAME_PREFIX: &str = "chkpt_";

#[derive(Debug, Clone, PartialEq, Eq, Hash, Copy)]
pub enum CheckpointMode {
    Full,
    Incremental,
}

impl CheckpointMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            CheckpointMode::Full => "full",
            CheckpointMode::Incremental => "incremental",
        }
    }
}

/// Worker that handles checkpoint processing for individual partitions
pub struct CheckpointWorker {
    /// Worker ID for logging
    worker_id: u32,

    mode: CheckpointMode,

    partition: Partition,

    /// Configuration
    config: CheckpointConfig,

    /// Reference to the store manager
    store: DeduplicationStore,

    /// Checkpoint export module
    exporter: Option<Arc<CheckpointExporter>>,
}

impl CheckpointWorker {
    pub fn new(
        worker_id: u32,
        config: CheckpointConfig,
        mode: CheckpointMode,
        partition: Partition,
        store: DeduplicationStore,
        exporter: Option<Arc<CheckpointExporter>>,
    ) -> Self {
        Self {
            worker_id,
            mode,
            partition,
            config,
            store,
            exporter,
        }
    }

    /// Perform a checkpoint for the given (assumed active) partition and store
    pub async fn checkpoint_partition(&self) -> Result<Option<String>> {
        let start_time = Instant::now();
        let partition_tag = self.partition.to_string();

        // Create checkpoint directory with timestamp (microseconds for uniqueness)
        // and ensure the checkpoint name is unique and lexicographically sortable
        let checkpoint_timestamp = self.generate_checkpoint_timestamp()?;
        let checkpoint_name = self.build_checkpoint_name(checkpoint_timestamp);
        let local_checkpoint_path =
            PathBuf::from(&self.config.local_checkpoint_dir).join(&checkpoint_name);
        let local_path_tag = local_checkpoint_path.to_string_lossy().to_string();

        info!(
            self.worker_id,
            partition = partition_tag,
            local_path = local_path_tag,
            checkpoint_mode = self.mode.as_str(),
            "Checkpoint worker: initializing checkpoint"
        );

        // Ensure local checkpoint directory exists - results observed internally, safe to bubble up
        self.create_partition_checkpoint_directory(&partition_tag, &local_path_tag)
            .await?;

        // this creates the local RocksDB checkpoint - results observed internally, safe to bubble up
        self.create_local_partition_checkpoint(
            &local_checkpoint_path,
            start_time,
            &partition_tag,
            &local_path_tag,
        )
        .await?;

        // update store metrics - this can fail without blocking the checkpoint attempt
        if let Err(e) = self.store.update_metrics() {
            warn!(
                self.worker_id,
                partition = partition_tag,
                local_path = local_path_tag,
                checkpoint_mode = self.mode.as_str(),
                "Checkpoint worker: failed store metrics update after local chekcpoint: {}",
                e
            );
        }

        // export the checkpoint - observed internally, safe to return result
        self.export_checkpoint(
            &local_checkpoint_path,
            &checkpoint_name,
            &partition_tag,
            &local_path_tag,
        )
        .await
    }

    async fn create_partition_checkpoint_directory(
        &self,
        partition_tag: &str,
        local_path_tag: &str,
    ) -> Result<()> {
        if let Err(e) = tokio::fs::create_dir_all(&self.config.local_checkpoint_dir)
            .await
            .context("Failed to create local checkpoint directory")
        {
            let tags = [
                ("mode", self.mode.as_str()),
                ("result", "error"),
                ("cause", "create_local_dir"),
            ];
            metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
            error!(
                self.worker_id,
                partition = partition_tag,
                local_path = local_path_tag,
                checkpoint_mode = self.mode.as_str(),
                "Failed to create local checkpoint directory: {}",
                e
            );

            return Err(anyhow::anyhow!(e));
        }

        Ok(())
    }

    async fn create_local_partition_checkpoint(
        &self,
        local_checkpoint_path: &PathBuf,
        start_time: Instant,
        partition_tag: &str,
        local_path_tag: &str,
    ) -> Result<()> {
        match self
            .store
            .create_checkpoint_with_metadata(local_checkpoint_path)
        {
            Ok(sst_files) => {
                let checkpoint_duration = start_time.elapsed();
                metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
                    .record(checkpoint_duration.as_secs_f64());

                metrics::histogram!(CHECKPOINT_FILE_COUNT_HISTOGRAM).record(sst_files.len() as f64);
                if let Ok(checkpoint_size) = Self::get_directory_size(local_checkpoint_path).await {
                    metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);
                }

                info!(
                    self.worker_id,
                    partition = partition_tag,
                    local_path = local_path_tag,
                    sst_file_count = sst_files.len(),
                    checkpoint_mode = self.mode.as_str(),
                    "Created local checkpoint",
                );

                Ok(())
            }

            Err(e) => {
                // Build the complete error chain
                let mut error_chain = vec![format!("{:?}", e)];
                let mut source = e.source();
                while let Some(err) = source {
                    error_chain.push(format!("Caused by: {err:?}"));
                    source = err.source();
                }

                let tags = [
                    ("mode", self.mode.as_str()),
                    ("result", "error"),
                    ("cause", "local_checkpoint"),
                ];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                error!(
                    self.worker_id,
                    partition = partition_tag,
                    local_path = local_path_tag,
                    checkpoint_mode = self.mode.as_str(),
                    "Local checkpoint failed: {}",
                    error_chain.join(" -> ")
                );

                Err(anyhow::anyhow!(error_chain.join(" -> ")))
            }
        }
    }

    async fn export_checkpoint(
        &self,
        local_checkpoint_path: &Path,
        checkpoint_name: &str,
        partition_tag: &str,
        local_path_tag: &str,
    ) -> Result<Option<String>> {
        info!(
            self.worker_id,
            partition = partition_tag,
            local_path = local_path_tag,
            checkpoint_mode = self.mode.as_str(),
            "Checkpoint worker: exporting remote checkpoint",
        );

        match self.exporter.as_ref() {
            Some(exporter) => {
                match exporter
                    .export_checkpoint(local_checkpoint_path, checkpoint_name, self.mode)
                    .await
                {
                    Ok(remote_key_prefix) => {
                        let tags = [
                            ("mode", self.mode.as_str()),
                            ("result", "success"),
                            ("export", "success"),
                        ];
                        metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                        info!(
                            self.worker_id,
                            partition = partition_tag,
                            local_path = local_path_tag,
                            remote_path = remote_key_prefix,
                            checkpoint_mode = self.mode.as_str(),
                            "Checkpoint exported successfully"
                        );

                        Ok(Some(remote_key_prefix))
                    }

                    Err(e) => {
                        let tags = [
                            ("mode", self.mode.as_str()),
                            ("result", "error"),
                            ("cause", "export"),
                        ];
                        metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                        error!(
                            self.worker_id,
                            partition = partition_tag,
                            local_path = local_path_tag,
                            checkpoint_mode = self.mode.as_str(),
                            "Checkpoint failed to export: {}",
                            e
                        );

                        Err(e)
                    }
                }
            }

            None => {
                let tags = [
                    ("mode", self.mode.as_str()),
                    ("result", "success"),
                    ("export", "skipped"),
                ];
                metrics::counter!(CHECKPOINT_WORKER_STATUS_COUNTER, &tags).increment(1);
                warn!(
                    self.worker_id,
                    partition = partition_tag,
                    local_path = local_path_tag,
                    checkpoint_mode = self.mode.as_str(),
                    "Checkpoint upload skipped: no exporter configured",
                );

                Ok(None)
            }
        }
    }

    // TODO(eli): discussed breaking this in to path-like elements but so far
    // I'm leaning towards keeping it a single directory name. It's sortable,
    // simple to work with, and maintains a 1:1 mapping between local paths under
    // base dir and S3 snapshot paths under bucket key prefix. Can revisit if needed
    fn build_checkpoint_name(&self, checkpoint_timestamp: u128) -> String {
        format!(
            "{}{}_{}_{:018}",
            CHECKPOINT_NAME_PREFIX,
            self.partition.topic(),
            self.partition.partition_number(),
            checkpoint_timestamp
        )
    }

    fn generate_checkpoint_timestamp(&self) -> Result<u128> {
        Ok(SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("failed to generate checkpoint timestamp")?
            .as_micros())
    }

    async fn get_directory_size(path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .context("Failed to read directory")?;

            while let Some(entry) = entries.next_entry().await? {
                let entry_path = entry.path();
                if entry_path.is_dir() {
                    stack.push(entry_path);
                } else {
                    let metadata = entry.metadata().await?;
                    total_size += metadata.len();
                }
            }
        }

        Ok(total_size)
    }
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

    /// Handle to the checkpoint task loop
    checkpoint_task: Option<JoinHandle<()>>,

    /// Handle to the local checkpoint directory cleanup task loop
    cleanup_task: Option<JoinHandle<()>>,
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
            checkpoint_task: None,
            cleanup_task: None,
        }
    }

    /// Start the periodic flush task
    pub fn start(&mut self) {
        if self.checkpoint_task.is_some() {
            warn!("Checkpoint manager already started");
            return;
        }

        info!(
            "Starting checkpoint manager with interval: {:?}",
            self.config.checkpoint_interval
        );

        // TODO(eli): ADD SEMAPHORE GATING TO SUBMIT LOOP THREAD BELOW!
        let _semaphore = Arc::new(Semaphore::new(self.config.max_concurrent_checkpoints));

        // clones we can reuse as bases within the checkpoint submission loop
        // without involving "self" and moving it into the loop
        let config = self.config.clone();
        let store_manager = self.store_manager.clone();
        let exporter = self.exporter.clone();
        let cancel_submit_loop_token = self.cancel_token.child_token();

        // loop-local counter for individual worker task logging
        let mut worker_task_id = 0_u32;

        // loop-local state variables. In the future, we can pass in
        // last-known values for these as recorded in checkpoint metadata
        let is_checkpointing: Arc<Mutex<HashSet<Partition>>> = Arc::new(Mutex::new(HashSet::new()));
        let checkpoint_counters: Arc<Mutex<HashMap<Partition, u32>>> =
            Arc::new(Mutex::new(HashMap::new()));

        let submit_handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(config.checkpoint_interval);
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
                        let stores = store_manager.stores();
                        let store_count = stores.len();
                        if store_count == 0 {
                            debug!("No stores to flush");
                            continue;
                        }

                        info!("Checkpoint manager: attempting checkpoint submission for {} stores", store_count);

                        // Snapshot all entries to avoid holding locks
                        let candidates: Vec<(Partition, DeduplicationStore)> = stores
                            .iter()
                            .map(|entry| (entry.key().clone(), entry.value().clone()))
                            .collect();

                        // Flush, checkpoint, and update metrics for each known store.
                        // if we block here, we can miss a few ticks it's OK. If upon
                        // successful receipt this partition's store is no longer owned
                        // by the StoreManager, the receiver will bail out and continue
                        for (partition, store) in candidates {
                            let partition_tag = partition.to_string();

                            if Self::checkpoint_in_progress(&partition, &is_checkpointing).await {
                                debug!(partition = partition_tag, "Checkpoint manager: checkpoint already in progress, skipping");
                                continue;
                            }

                            // Determine if this should be a full upload or incremental
                            let mode = Self::get_checkpoint_mode(&partition, &checkpoint_counters, &config).await;

                            // Ensure the store is still associated with this pod and store manager
                            if store_manager.get(partition.topic(), partition.partition_number()).is_none() {
                                    // TODO(eli): stat this w/tag
                                    warn!(
                                        partition = partition_tag,
                                        "Checkpoint manager: partition no longer owned by store manager, skipping"
                                    );
                                    continue;
                            }

                            // if the exporter is configured, clone it for the worker thread
                            let resolved_exporter = exporter.as_ref().map(|e| e.clone());

                            // spin up worker with unique task ID for logging
                            worker_task_id += 1;
                            let worker = CheckpointWorker::new(
                                worker_task_id,
                                config.clone(),
                                mode,
                                partition.clone(),
                                store,
                                resolved_exporter,
                            );

                            // clone things that the worker thread will need references to
                            let cancel_worker_token = cancel_submit_loop_token.child_token();

                            // TODO: for now, we don't bother to track the handles of spawned workers
                            // because each worker represents one best-effort checkpoint attempt
                            let result = tokio::spawn(async move {
                                tokio::select! {
                                    _ = cancel_worker_token.cancelled() => {
                                        info!(partition = partition_tag, "Checkpoint manager: inner submit loop shutting down");
                                        Ok(None)
                                    }

                                    result = worker.checkpoint_partition() => {
                                        let status = match &result {
                                            &Ok(Some(_)) => "success",
                                            &Ok(None) => "skipped",
                                            &Err(_) => "error",
                                        };
                                        info!(worker_task_id, partition = partition_tag, result = status,
                                            "Checkpoint manager: checkpoint attempt completed");

                                        result
                                    }
                                }
                            });

                            // release the in-flight lock regardless of outcome
                            {
                                let mut is_checkpointing_guard = is_checkpointing.lock().await;
                                is_checkpointing_guard.remove(&partition);
                            }

                            // result is observed interally and errors shouldn't bubble up here
                            // so we only care if the export was successful and we need to
                            // increment the checkpoint counter
                            if let Ok(Ok(Some(_))) = result.await {
                                // NOTE: could race another checkpoint attempt on same partition between
                                //       is_checkpointing release and this call, but we also need to
                                //       maintain lock access ordering here. May need to consider
                                //       implementing these a single lock-wrapped object...
                                {
                                    let mut counter_guard = checkpoint_counters.lock().await;
                                    let counter_for_partition = *counter_guard.get(&partition).unwrap_or(&0_u32);
                                    counter_guard.insert(partition.clone(), counter_for_partition + 1);
                                }
                            }
                        } // end partition loop

                        info!("Completed periodic checkpoint attempt for {} stores", store_count);
                    }
                } // end tokio::select! block
            } // end 'outer loop
        });
        self.checkpoint_task = Some(submit_handle);

        let cleanup_config = self.config.clone();
        let cancel_cleanup_loop_token = self.cancel_token.child_token();
        let cleanup_handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(cleanup_config.cleanup_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            // Skip first tick to avoid immediate flush
            interval.tick().await;

            loop {
                tokio::select! {
                    _ = cancel_cleanup_loop_token.cancelled() => {
                        info!("Checkpoint manager: cleanup loop shutting down");
                        break;
                    }

                    _ = interval.tick() => {
                        if let Err(e) = Self::cleanup_local_checkpoints(&cleanup_config).await {
                            error!("Checkpoint manager: failed to cleanup local checkpoints: {}", e);
                        }
                    }
                }
            }
        });
        self.cleanup_task = Some(cleanup_handle);
    }

    /// Stop the checkpoint manager
    pub async fn stop(&mut self) {
        info!("Stopping checkpoint manager");

        // Cancel the task
        self.cancel_token.cancel();

        // Stop in-flight submissions to the checkpoint workers immediately
        if let Some(task) = self.checkpoint_task.take() {
            task.abort();
        }

        // Stop local checkpoint directory cleanup task
        if let Some(task) = self.cleanup_task.take() {
            task.abort();
        }

        // TODO(eli): await is_checkpointing tasks to complete? just bail at first, see how it goes?

        info!("Checkpoint manager stopped");
    }

    /// Trigger an immediate flush of all stores
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

        for (partition, store) in snapshot {
            debug!(
                "Flushing store {}:{}",
                partition.topic(),
                partition.partition_number()
            );
            store.flush()?;
            store.update_metrics()?;
        }

        Ok(())
    }

    // use the local atomic counter for the given partition to determine
    // if this checkpoint should be full or incremental. CheckpointConfig
    // specifies the interval at which full checkpoints should be performed
    async fn get_checkpoint_mode(
        partition: &Partition,
        checkpoint_counters: &Arc<Mutex<HashMap<Partition, u32>>>,
        config: &CheckpointConfig,
    ) -> CheckpointMode {
        // Determine if this should be a full upload or incremental
        let counter_for_partition: u32;
        {
            let counter_guard = checkpoint_counters.lock().await;
            counter_for_partition = *counter_guard.get(partition).unwrap_or(&0_u32);
        }

        if counter_for_partition % config.full_upload_interval == 0 {
            CheckpointMode::Full
        } else {
            CheckpointMode::Incremental
        }
    }

    async fn checkpoint_in_progress(
        partition: &Partition,
        is_checkpointing: &Arc<Mutex<HashSet<Partition>>>,
    ) -> bool {
        let mut is_checkpointing_guard = is_checkpointing.lock().await;
        if is_checkpointing_guard.contains(partition) {
            return true;
        }

        is_checkpointing_guard.insert(partition.clone());
        false
    }

    async fn cleanup_local_checkpoints(config: &CheckpointConfig) -> Result<()> {
        let checkpoint_dir = PathBuf::from(config.local_checkpoint_dir.clone());

        if !checkpoint_dir.exists() {
            return Ok(());
        }

        let mut entries = tokio::fs::read_dir(&checkpoint_dir)
            .await
            .context("Failed to read checkpoint directory")?;

        let mut checkpoint_dirs = Vec::new();

        while let Some(entry) = entries.next_entry().await? {
            let path = entry.path();
            if path.is_dir() {
                if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                    if name.starts_with(CHECKPOINT_NAME_PREFIX) {
                        checkpoint_dirs.push(path);
                    }
                }
            }
        }

        // Sort by name (which includes timestamp) to get chronological order
        checkpoint_dirs.sort_by(|a, b| a.file_name().unwrap().cmp(b.file_name().unwrap()));

        // Keep only the most recent checkpoints
        if checkpoint_dirs.len() > config.max_local_checkpoints {
            let checkpoints_to_remove = checkpoint_dirs.len() - config.max_local_checkpoints;
            for checkpoint_dir in checkpoint_dirs.iter().take(checkpoints_to_remove) {
                let checkpoint_path = checkpoint_dir.to_string_lossy().to_string();

                if let Err(e) = tokio::fs::remove_dir_all(checkpoint_dir).await {
                    warn!(
                        checkpoint_path = checkpoint_path,
                        "Checkpoint manager: failed to remove old checkpoint: {}", e
                    );
                } else {
                    info!(
                        checkpoint_path = checkpoint_path,
                        "Checkpoint manager: removed old checkpoint"
                    );
                }
            }
        }

        Ok(())
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

        // Stop local checkpoint directorycleanup loop
        if let Some(task) = self.cleanup_task.take() {
            debug!("Checkpoint manager dropped: cleanup task will terminate");
            task.abort();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::{DeduplicationStore, DeduplicationStoreConfig};
    use common_types::RawEvent;
    use std::{collections::HashMap, path::PathBuf, time::Duration};
    use tempfile::TempDir;

    fn create_test_store(topic: &str, partition: i32) -> (DeduplicationStore, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1_000_000,
        };
        let store = DeduplicationStore::new(config, topic.to_string(), partition).unwrap();
        (store, temp_dir)
    }

    fn create_test_event() -> RawEvent {
        RawEvent {
            uuid: None,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("test_token".to_string()),
            properties: HashMap::new(),
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn test_checkpoint_manager_creation() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));

        // TODO(eli): move this to a test helper and/or default impl
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            max_concurrent_checkpoints: 1,
            full_upload_interval: 1,
            max_local_checkpoints: 1,
            local_checkpoint_dir: "test".to_string(),
            s3_bucket: "test".to_string(),
            s3_key_prefix: "test".to_string(),
            aws_region: "test".to_string(),
            s3_timeout: Duration::from_secs(30),
        };
        let manager = CheckpointManager::new(config, stores.clone(), None);

        assert_eq!(manager.config.checkpoint_interval, Duration::from_secs(30));
        assert!(manager.checkpoint_task.is_none());
        assert!(manager.exporter.is_none());
        assert!(manager.worker_tasks.is_empty());
    }

    #[tokio::test]
    async fn test_checkpoint_manager_start_stop() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config, stores.clone(), None);

        // Start the manager
        manager.start();
        assert!(manager.checkpoint_task.is_some());

        // Stop the manager
        manager.stop().await;
        assert!(manager.checkpoint_task.is_none());
    }

    #[tokio::test]
    async fn test_flush_all_empty() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config, stores.clone(), None);

        // Flushing empty stores should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_flush_all_with_stores() {
        // Add some test stores
        let (store1, _dir1) = create_test_store("topic1", 0);
        let (store2, _dir2) = create_test_store("topic1", 1);

        let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: _dir1.path().to_path_buf(),
            max_capacity: 1_000_000,
        }));
        let stores = store_manager.stores();

        // Add events to the stores
        let event = create_test_event();
        store1.handle_event_with_raw(&event).unwrap();
        store2.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store1);
        stores.insert(Partition::new("topic1".to_string(), 1), store2);

        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config, store_manager.clone(), None);

        // Flush all should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_checkpoint_partition() {
        let (store, temp_dir) = create_test_store("topic1", 0);
        let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1_000_000,
        }));
        let stores = store_manager.stores();

        // Add an event to the store
        let event = create_test_event();
        store.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store.clone());

        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Create checkpoint
        let partition = Partition::new("topic1".to_string(), 0);
        let worker = CheckpointWorker::new(
            1,
            store_manager.clone(),
            manager.exporter.clone(),
            manager.checkpoint_counters.clone(),
            manager.is_checkpointing.clone(),
            config.clone(),
        );
        let result = worker.attempt_checkpoint(partition).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_checkpoint_partition_not_found() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), stores.clone(), None);
        // Should fail for non-existent partition
        let partition = Partition::new("topic1".to_string(), 0);
        let worker = CheckpointWorker::new(
            1,
            stores.clone(),
            manager.exporter.clone(),
            manager.checkpoint_counters.clone(),
            manager.is_checkpointing.clone(),
            config.clone(),
        );
        let result = worker.attempt_checkpoint(partition).await;
        assert!(result.is_ok()); // This should return Ok(false) since partition doesn't exist
        assert!(!result.unwrap()); // Should return false for non-existent partition
    }

    #[tokio::test]
    async fn test_periodic_flush_task() {
        let (store, dir) = create_test_store("topic1", 0);
        let store_manager = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: dir.path().to_path_buf(),
            max_capacity: 1_000_000,
        }));
        let stores = store_manager.stores();

        // Add an event
        let event = create_test_event();
        store.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store);

        // Create manager with short interval for testing
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(100),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config, store_manager.clone(), None);

        // Start the manager
        manager.start();

        // Wait for a few flush cycles
        tokio::time::sleep(Duration::from_millis(350)).await;

        // Stop the manager
        manager.stop().await;
    }

    #[tokio::test]
    async fn test_double_start() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config, stores.clone(), None);

        // Start once
        manager.start();
        assert!(manager.checkpoint_task.is_some());

        // Start again - should warn but not panic
        manager.start();
        assert!(manager.checkpoint_task.is_some());

        manager.stop().await;
    }

    #[tokio::test]
    async fn test_drop_cancels_task() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config, stores.clone(), None);

        manager.start();
        let cancel_token = manager.cancel_token.clone();

        assert!(!cancel_token.is_cancelled());

        // Drop the manager
        drop(manager);

        // Token should be cancelled
        assert!(cancel_token.is_cancelled());
    }
}
