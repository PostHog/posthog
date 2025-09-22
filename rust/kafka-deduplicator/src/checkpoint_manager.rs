use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::checkpoint::{
    CheckpointConfig, CheckpointExporter, CheckpointMode, CheckpointTarget, CheckpointWorker,
    CHECKPOINT_PARTITION_PREFIX, CHECKPOINT_TOPIC_PREFIX,
};
use crate::kafka::types::Partition;
use crate::metrics_const::{CHECKPOINT_CLEANER_DELETE_ATTEMPTS, CHECKPOINT_CLEANER_DIRS_FOUND};
use crate::store::DeduplicationStore;
use crate::store_manager::StoreManager;

use anyhow::{Context, Result};
use tokio::sync::{Mutex, OwnedSemaphorePermit, Semaphore};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

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
        let mut worker_task_id = 0_u32;

        // loop-local state variables. In the future, we can pass in
        // last-known values for these as recorded in checkpoint metadata
        let is_checkpointing: Arc<Mutex<HashSet<Partition>>> = Arc::new(Mutex::new(HashSet::new()));
        let checkpoint_counters: Arc<Mutex<HashMap<Partition, u32>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let checkpoint_health_reporter = health_reporter.clone();

        let checkpoint_task_handle = tokio::spawn(async move {
            // limit parallel checkpoint attempts. This loop
            // can block when the limit is reached
            let semaphore = Arc::new(Semaphore::new(
                submit_loop_config.max_concurrent_checkpoints,
            ));

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

                            // clone the manager lock structures for this worker instance
                            let worker_is_checkpointing = is_checkpointing.clone();
                            let worker_checkpoint_counters = checkpoint_counters.clone();

                            // acquire semaphore or block here
                            let ticket: OwnedSemaphorePermit;
                            tokio::select! {
                                _ = cancel_submit_loop_token.cancelled() => {
                                    info!(partition = partition_tag, "Checkpoint manager: submit loop shutting down while awaiting permit");
                                    break 'outer;
                                }

                                result = semaphore.clone().acquire_owned() => {
                                    match result {
                                        Ok(permit) => ticket = permit,
                                        Err(e) => {
                                            error!(partition = partition_tag, "Checkpoint manager: semaphore closed, skipping with error: {}", e);
                                            continue;
                                        }
                                    }
                                }
                            }

                            if Self::checkpoint_in_progress(&partition, &is_checkpointing).await {
                                debug!(partition = partition_tag, "Checkpoint manager: checkpoint already in progress, skipping");
                                continue;
                            }

                            // Determine if this should be a full upload or incremental
                            let mode = Self::get_checkpoint_mode(&partition, &checkpoint_counters, &submit_loop_config).await;

                            // Ensure the store is still associated with this pod and store manager
                            if store_manager.get(partition.topic(), partition.partition_number()).is_none() {
                                    // TODO(eli): stat this w/tag
                                    warn!(
                                        partition = partition_tag,
                                        "Checkpoint manager: partition no longer owned by store manager, skipping"
                                    );
                                    continue;
                            }

                            let target = CheckpointTarget::new(partition.clone(), Path::new(&submit_loop_config.local_checkpoint_dir)).unwrap();
                            // if the exporter is configured, clone it for the worker thread
                            let resolved_exporter = exporter.as_ref().map(|e| e.clone());

                            // spin up worker with unique task ID for logging
                            worker_task_id += 1;
                            let worker = CheckpointWorker::new(
                                worker_task_id,
                                mode,
                                target,
                                store,
                                resolved_exporter,
                            );

                            // clone things that the worker thread will need references to
                            let cancel_worker_token = cancel_submit_loop_token.child_token();

                            // for now, we don't bother to track the handles of spawned workers
                            // because each worker represents one best-effort checkpoint attempt
                            let _result = tokio::spawn(async move {
                                // best effort to bail if the checkpoint manager shut
                                // down before the worker thread started executing...
                                if tokio::time::timeout(std::time::Duration::from_millis(1), cancel_worker_token.cancelled()).await.is_ok() {
                                    info!(partition = partition_tag, "Checkpoint manager: inner submit loop shutting down, skipping worker execution");
                                    return Ok(None);
                                }

                                // block and execute the checkpoint attempt here
                                let result = worker.checkpoint_partition().await;

                                let status = match result {
                                    Ok(Some(_)) => "success",
                                    Ok(None) => "skipped",
                                    Err(_) => "error",
                                };
                                info!(worker_task_id, partition = partition_tag, result = status,
                                    "Checkpoint manager: checkpoint attempt completed");

                                // release the permit so another checkpoint attempt can proceed
                                drop(ticket);

                                // release the in-flight lock regardless of outcome
                                {
                                    let mut is_checkpointing_guard = worker_is_checkpointing.lock().await;
                                    is_checkpointing_guard.remove(&partition);
                                }

                                // result is observed interally and errors shouldn't bubble up here
                                // so we only care if the export was successful and we need to
                                // increment the checkpoint counter
                                if let Ok(Some(_)) = result {
                                    // NOTE: could race another checkpoint attempt on same partition between
                                    //       is_checkpointing release and this call, but we must maintain
                                    //       lock access ordering. Can revisit this later if its a problem
                                    {
                                        let mut counter_guard = worker_checkpoint_counters.lock().await;
                                        let counter_for_partition = *counter_guard.get(&partition).unwrap_or(&0_u32);
                                        counter_guard.insert(partition.clone(), counter_for_partition + 1);
                                    }
                                }

                                result
                            });
                        } // end partition loop

                        info!("Completed periodic checkpoint attempt for {} stores", store_count);
                    }
                } // end tokio::select! block
            } // end 'outer loop

            checkpoint_health_reporter.store(false, Ordering::SeqCst);
        });
        self.checkpoint_task = Some(checkpoint_task_handle);

        let cleanup_config = self.config.clone();
        let cancel_cleanup_loop_token = self.cancel_token.child_token();
        let cleanup_health_reporter = health_reporter.clone();

        let cleanup_handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(cleanup_config.cleanup_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            // Skip first tick to avoid immediate cleaning pass
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

            cleanup_health_reporter.store(false, Ordering::SeqCst);
        });
        self.cleanup_task = Some(cleanup_handle);

        Some(health_reporter.clone())
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

        // TODO: await is_checkpointing tasks to complete? just bail at first, see how it goes?

        info!("Checkpoint manager stopped");
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

        // if config.full_upload_interval is 0, then we should always do full uploads
        if config.full_upload_interval == 0 {
            return CheckpointMode::Full;
        }

        // otherwise, use the atomic counter for this partition
        // and decide based on the configured interval
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
        let checkpoint_base_dir = PathBuf::from(config.local_checkpoint_dir.clone());
        if !checkpoint_base_dir.exists() {
            return Ok(());
        }

        // find all eligible checkpoint directories of form /base_dir/topic/partition/timestamp
        let candidate_dirs = Self::find_checkpoint_dirs(&checkpoint_base_dir)
            .await
            .context("Checkpoint cleaner: failed loading local checkpoint directories")?;

        // first eliminate all dirs that are older than max retention period
        let remaining_dirs = Self::remove_stale_checkpoint_dirs(config, candidate_dirs).await?;

        // next, group remaining checkpoints dirs by parent /topic/partition
        // and eliminate the oldest N past the configured retention count
        Self::remove_checkpoint_dirs_past_partition_retention(config, remaining_dirs).await
    }

    async fn find_checkpoint_dirs(current_dir: &Path) -> Result<Vec<PathBuf>> {
        let mut checkpoint_dirs = Vec::new();
        let mut stack = vec![current_dir.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path).await?;
            while let Some(entry) = entries.next_entry().await? {
                let path = entry.path();
                if path.is_dir() {
                    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                        // these will be parent directories of the checkpoints; drill down and process each
                        if name.starts_with(CHECKPOINT_TOPIC_PREFIX)
                            || name.starts_with(CHECKPOINT_PARTITION_PREFIX)
                        {
                            stack.push(path);
                        } else if name.chars().filter(|c| c.is_ascii_digit()).count() == name.len()
                        {
                            // if the name matches a 0-padded UNIX epoch timestamp in microseconds, then
                            // this is the full path to a directory containing the checkpoint files
                            checkpoint_dirs.push(path);
                        }
                    }
                }
            }
        }

        metrics::counter!(CHECKPOINT_CLEANER_DIRS_FOUND).increment(checkpoint_dirs.len() as u64);

        Ok(checkpoint_dirs)
    }

    async fn remove_checkpoint_dirs_past_partition_retention(
        config: &CheckpointConfig,
        remaining_dirs: Vec<PathBuf>,
    ) -> Result<()> {
        // group /topic/partition/timestamp dirs by parent /topic/partition
        let mut paths_by_parent: HashMap<String, Vec<PathBuf>> =
            remaining_dirs
                .into_iter()
                .fold(HashMap::new(), |mut acc, path| {
                    // due to known structure of the input paths, this shouldn't ever fail
                    let parent = path.parent().unwrap().to_string_lossy().to_string();
                    acc.entry(parent).or_default().push(path);
                    acc
                });

        // iterate on each group, sort by timestamp dir, and eliminate the oldest N
        for checkpoint_dirs in paths_by_parent.values_mut() {
            if checkpoint_dirs.len() > config.max_local_checkpoints {
                // sort by timestamp dir
                checkpoint_dirs.sort_by(|a, b| a.file_name().unwrap().cmp(b.file_name().unwrap()));

                // eliminate the oldest N snapshots from each /topic/partition group
                let checkpoints_to_remove = checkpoint_dirs.len() - config.max_local_checkpoints;
                for checkpoint_dir in checkpoint_dirs.iter().take(checkpoints_to_remove) {
                    let checkpoint_path = checkpoint_dir.to_string_lossy().to_string();

                    if let Err(e) = tokio::fs::remove_dir_all(checkpoint_dir).await {
                        let tags = [("result", "error"), ("scan_type", "partition_limit")];
                        metrics::counter!(CHECKPOINT_CLEANER_DELETE_ATTEMPTS, &tags).increment(1);
                        warn!(
                            checkpoint_path = checkpoint_path,
                            "Checkpoint cleaner: failed to remove checkpoint past partition retention limit: {}", e
                        );
                    } else {
                        let tags = [("result", "success"), ("scan_type", "partition_limit")];
                        metrics::counter!(CHECKPOINT_CLEANER_DELETE_ATTEMPTS, &tags).increment(1);
                        info!(
                            checkpoint_path = checkpoint_path,
                            "Checkpoint cleaner: removed checkpoint past partition retention limit"
                        );
                    }
                }
            }
        }

        Ok(())
    }

    async fn remove_stale_checkpoint_dirs(
        config: &CheckpointConfig,
        candidate_dirs: Vec<PathBuf>,
    ) -> Result<Vec<PathBuf>> {
        let threshold_time = SystemTime::now()
            - Duration::from_secs(config.max_checkpoint_retention_hours as u64 * 3600);
        let mut remaining_dirs = Vec::new();

        for candidate_dir in candidate_dirs.into_iter() {
            let checkpoint_path = candidate_dir.to_string_lossy().to_string();
            let checkpoint_child_dir = candidate_dir
                .file_name()
                .context("Checkpoint cleaner: failed to get checkpoint dir name")?
                .to_string_lossy()
                .to_string();

            // the directory name should be a 0-padded UNIX epoch timestamp
            // in microseconds indicating when the checkpoint was attempted
            match Self::parse_checkpoint_timestamp(&checkpoint_child_dir) {
                Ok(checkpoint_dir_created_at) => {
                    if checkpoint_dir_created_at > threshold_time {
                        remaining_dirs.push(candidate_dir);
                    } else if let Err(e) = tokio::fs::remove_dir_all(&candidate_dir).await {
                        let tags = [("result", "error"), ("scan_type", "retention_time")];
                        metrics::counter!(CHECKPOINT_CLEANER_DELETE_ATTEMPTS, &tags).increment(1);
                        warn!(
                            checkpoint_path = checkpoint_path,
                            "Checkpoint cleaner: failed to remove stale checkpoint: {}", e
                        );
                        remaining_dirs.push(candidate_dir);
                    } else {
                        let tags = [("result", "success"), ("scan_type", "retention_time")];
                        metrics::counter!(CHECKPOINT_CLEANER_DELETE_ATTEMPTS, &tags).increment(1);
                        info!(
                            checkpoint_path = checkpoint_path,
                            "Checkpoint cleaner: removed stale checkpoint"
                        );
                    }
                }

                Err(e) => {
                    let tags = [("result", "error"), ("scan_type", "invalid_timestamp")];
                    metrics::counter!(CHECKPOINT_CLEANER_DELETE_ATTEMPTS, &tags).increment(1);
                    warn!(
                        checkpoint_path = checkpoint_path,
                        "Checkpoint cleaner: failed to parse checkpoint dir name as timestamp: {}",
                        e
                    );
                    remaining_dirs.push(candidate_dir);
                }
            }
        }

        Ok(remaining_dirs)
    }

    fn parse_checkpoint_timestamp(dir_name: &str) -> Result<SystemTime> {
        let microseconds = dir_name
            .parse::<u128>()
            .context("failed to parse directory name as microsecond timestamp")?;

        let duration = Duration::from_micros(microseconds as u64);
        Ok(UNIX_EPOCH + duration)
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

        // Stop local checkpoint directory cleanup loop
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
            uuid: None,
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("test_token".to_string()),
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
                    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                        if name.starts_with(CHECKPOINT_TOPIC_PREFIX)
                            || name.starts_with(CHECKPOINT_PARTITION_PREFIX)
                            || name.chars().filter(|c| c.is_ascii_digit()).count() == name.len()
                        {
                            stack.push(path);
                        }
                    }
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
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let manager = CheckpointManager::new(config.clone(), stores.clone(), None);

        assert!(manager.checkpoint_task.is_none());
        assert_eq!(manager.config.checkpoint_interval, Duration::from_secs(30));

        assert!(manager.cleanup_task.is_none());
        assert_eq!(manager.config.cleanup_interval, Duration::from_secs(10));

        assert!(manager.exporter.is_none());
    }

    #[tokio::test]
    async fn test_checkpoint_manager_start_stop() {
        let store_manager = create_test_store_manager();

        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(30),
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Start the manager
        manager.start();
        assert!(manager.checkpoint_task.is_some());
        assert!(manager.cleanup_task.is_some());

        // Stop the manager
        manager.stop().await;
        assert!(manager.checkpoint_task.is_none());
        assert!(manager.cleanup_task.is_none());
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
        store1.handle_event_with_raw(&event).unwrap();
        store2.handle_event_with_raw(&event).unwrap();

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
            cleanup_interval: Duration::from_secs(10),
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
            cleanup_interval: Duration::from_secs(10),
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
        store.handle_event_with_raw(&event1).unwrap();
        let event2 = create_test_event();
        store.handle_event_with_raw(&event2).unwrap();

        // Create manager with short interval for testing
        let tmp_checkpoint_dir = TempDir::new().unwrap();
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(100),
            cleanup_interval: Duration::from_secs(10),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        let partition = Partition::new("test_periodic_flush_task".to_string(), 0);
        let stores = store_manager.stores();
        stores.insert(partition.clone(), store);

        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);

        // Start the manager
        let health_reporter = manager.start();
        assert!(health_reporter.is_some());

        // Wait for a few flush cycles
        tokio::time::sleep(Duration::from_millis(200)).await;

        // Stop the manager
        manager.stop().await;

        // service task threads are still healthy and running
        assert!(health_reporter.unwrap().load(Ordering::SeqCst));

        // the local checkpoints dir for the target topic partition
        // should have produced several checkpoints by now. The expected
        // parent path for checkpoints of this topic partition is this:
        let expected_checkpoint_dir = Path::new(&config.local_checkpoint_dir)
            .join(format!("{CHECKPOINT_TOPIC_PREFIX}{}", partition.topic()))
            .join(format!(
                "{CHECKPOINT_PARTITION_PREFIX}{}",
                partition.partition_number()
            ));

        // there should be lots of checkpoint files collected from
        // various attempt directories of form /<base_path>/topic/partition/timestamp
        let checkpoint_files =
            find_local_checkpoint_files(Path::new(&expected_checkpoint_dir)).unwrap();
        assert!(!checkpoint_files.is_empty());
        assert!(checkpoint_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with("CURRENT")));
        assert!(checkpoint_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("MANIFEST")));
        assert!(checkpoint_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().contains("OPTIONS")));
        assert!(checkpoint_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".sst")));
        assert!(checkpoint_files
            .iter()
            .any(|p| p.to_string_lossy().to_string().ends_with(".log")));

        // there should be one or more timstamp-based checkpoint attempt directories
        // of the form /<base_path>/topic/partition/timestamp depending on how
        // many times the task loop ran while the test slept
        let checkpoint_attempts = checkpoint_files
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
    async fn test_cleaner_task_retention_time() {
        // Add some test stores
        let store_manager = create_test_store_manager();
        let store1 = create_test_store("flush_all_with_stores", 0);
        let store2 = create_test_store("flush_all_with_stores", 1);

        // Add events to the stores
        let event = create_test_event();
        store1.handle_event_with_raw(&event).unwrap();
        store2.handle_event_with_raw(&event).unwrap();

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

        // configure frequent checkpoints and long retention, cleanup interval
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(50),
            cleanup_interval: Duration::from_secs(120),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // start the manager and produce some local checkpoint files
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);
        manager.start();
        tokio::time::sleep(Duration::from_millis(200)).await;
        manager.stop().await;

        let found_files =
            find_local_checkpoint_files(Path::new(&config.local_checkpoint_dir)).unwrap();
        assert!(!found_files.is_empty());

        // reconfigure the manager to not run checkpoints, but to clean up immediately
        // with a very recent retention time (now!)
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(120),
            cleanup_interval: Duration::from_millis(50),
            max_checkpoint_retention_hours: 0,
            max_local_checkpoints: 100, // don't come near this limit for this test!
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);
        manager.start();
        // wait for the cleanup task to run
        tokio::time::sleep(Duration::from_millis(100)).await;
        manager.stop().await;

        let found_files =
            find_local_checkpoint_files(Path::new(&config.local_checkpoint_dir)).unwrap();
        assert!(found_files.is_empty());
    }

    #[tokio::test]
    async fn test_cleaner_task_partition_count() {
        // Add some test stores
        let store_manager = create_test_store_manager();
        let store1 = create_test_store("flush_all_with_stores", 0);
        let store2 = create_test_store("flush_all_with_stores", 1);

        // Add events to the stores
        let event = create_test_event();
        store1.handle_event_with_raw(&event).unwrap();
        store2.handle_event_with_raw(&event).unwrap();

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

        // configure frequent checkpoints and long retention, cleanup interval
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_millis(50),
            cleanup_interval: Duration::from_secs(120),
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        // start the manager and produce some local checkpoint files
        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);
        manager.start();
        tokio::time::sleep(Duration::from_millis(200)).await;
        manager.stop().await;

        let found_files =
            find_local_checkpoint_files(Path::new(&config.local_checkpoint_dir)).unwrap();
        assert!(!found_files.is_empty());

        // reconfigure the manager to not run checkpoints, but to clean up immediately
        // with a very recent retention time (now!)
        let config = CheckpointConfig {
            checkpoint_interval: Duration::from_secs(120),
            cleanup_interval: Duration::from_millis(50),
            max_checkpoint_retention_hours: 24, // don't come near this limit for this test!
            max_local_checkpoints: 0,           // scorched earth
            local_checkpoint_dir: tmp_checkpoint_dir.path().to_string_lossy().to_string(),
            ..Default::default()
        };

        let mut manager = CheckpointManager::new(config.clone(), store_manager.clone(), None);
        manager.start();
        // wait for the cleanup task to run
        tokio::time::sleep(Duration::from_millis(100)).await;
        manager.stop().await;

        let found_files =
            find_local_checkpoint_files(Path::new(&config.local_checkpoint_dir)).unwrap();
        assert!(found_files.is_empty());
    }
}
