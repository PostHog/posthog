use anyhow::{Context, Result};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::mpsc::{Receiver, Sender};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

use crate::checkpoint::{export::CheckpointExporter, CheckpointConfig};
use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::DeduplicationStore;
use crate::store_manager::StoreManager;

const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";
const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";

pub const CHECKPOINT_NAME_PREFIX: &str = "chkpt";

/// Manages checkpointing and periodic flushing for all deduplication stores
pub struct CheckpointManager {
    config: CheckpointConfig,

    /// Reference to the store manager
    store_manager: Arc<StoreManager>,

    // Checkpoint export module - if populated, locally checkpointed partitions will be backed up remotely
    exporter: Arc<Option<Box<CheckpointExporter>>>,

    checkpoint_sender: Sender<CheckpointRequest>,

    checkpoint_receiver: Arc<Receiver<CheckpointRequest>>,

    /// Cancellation token for the flush task
    cancel_token: CancellationToken,

    /// Handles to the checkpoint task loop and async checkpoint spawner
    checkpoint_tasks: Vec<JoinHandle<()>>,
}

impl CheckpointManager {
    /// Create a new checkpoint manager
    pub fn new(
        config: CheckpointConfig,
        store_manager: Arc<StoreManager>,
        exporter: Option<Box<CheckpointExporter>>,
    ) -> Self {
        info!(
            max_concurrent_checkpoints = config.max_concurrent_checkpoints,
            exporting = exporter.is_some(),
            "Creating checkpoint manager",
        );

        let exporter = Arc::new(exporter);
        let (checkpoint_sender, checkpoint_receiver) = channel(config.max_concurrent_checkpoints);

        Self {
            config,
            store_manager,
            exporter: exporter,
            checkpoint_sender,
            checkpoint_receiver: Arc::new(checkpoint_receiver),
            cancel_token: CancellationToken::new(),
            checkpoint_tasks: Vec::new(),
        }
    }

    /// Start the periodic flush task
    pub fn start(&mut self) {
        if self.checkpoint_tasks.len() > 0 {
            warn!("Checkpoint manager already started");
            return;
        }

        info!(
            "Starting checkpoint manager with interval: {:?}",
            self.config.checkpoint_interval
        );

        let store_manager = self.store_manager.clone();
        let cancel_recv_loop = self.cancel_token.child_token();
        let checkpoint_interval = self.config.checkpoint_interval.clone();

        for task_id in 1..=self.config.max_concurrent_checkpoints {
            let local_task_id = task_id;
            let local_rx: Receiver<Partition> = self.checkpoint_receiver.clone().unwrap();
            let recv_handle = tokio::spawn(async move {
                loop {
                    tokio::select! {
                        _ = cancel_recv_loop.cancelled() => {
                            info!(local_task_id, "Checkpoint manager: receive loop shutting down");
                            break;
                        },

                        msg = self.checkpoint_receiver.recv() => {
                            match msg {
                                Some(partition) => {
                                    // TODO(eli): maybe don't worry about return values here?
                                    if let Err(e) = self.checkpoint_partition(partition).await {
                                        error!(local_task_id, "Checkpoint submission failed for store {}:{}: {}", partition.topic(), partition.partition_number(), e);
                                    }
                                }
                                None => {
                                    debug!(local_task_id, "Checkpoint manager: receiver closed, receive loop shutting down");
                                    break;
                                }
                            }
                        }
                    }
                }
            });
            self.checkpoint_tasks.push(recv_handle);
        }

        let submit_handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(checkpoint_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            // Skip first tick to avoid immediate flush
            interval.tick().await;

            loop {
                tokio::select! {
                    _ = cancel.cancelled() => {
                        info!("Checkpoint manager: submit loop shutting down");
                        break;
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

                        info!("Checkpoint manager: submit loop: checkpoint attempt for {} stores", store_count);

                        // Snapshot all entries to avoid holding locks
                        let partitions: Vec<Partition> = stores
                            .iter()
                            .map(|entry| entry.key().clone())
                            .collect();

                        // Flush, checkpoint, and update metrics for each known store.
                        // if we block here, we can miss a few ticks it's OK. If upon
                        // successful receipt this partition's store is no longer owned
                        // by the StoreManager, the receiver will bail out and continue
                        for partition in partitions {
                            tokio::select! {
                                _ = cancel.cancelled() => {
                                    info!("Checkpoint manager: inner submit loop shutting down after send attempt for {}:{}", partition.topic(), partition.partition_number());
                                    break;
                                }
                                result = self.checkpoint_sender.send(partition) => {
                                    match result {
                                        Ok(()) => {
                                            info!("Checkpoint submitted for store {}:{}", partition.topic(), partition.partition_number());
                                        }
                                        Err(e) => {
                                            error!("Checkpoint submission failed for store {}:{}: {}", partition.topic(), partition.partition_number(), e);
                                        }
                                    }
                                }
                            }
                        }
                        info!("Completed periodic flush for {} stores", store_count);
                    }
                }
            }
        });
        self.checkpoint_tasks.push(submit_handle);
    }

    /// Stop the checkpoint manager
    pub async fn stop(&mut self) {
        info!("Stopping checkpoint manager");

        // Cancel the task
        self.cancel_token.cancel();

        // Wait for tasks to complete
        for handle in self.checkpoint_tasks.drain(..) {
            if let Err(e) = handle.await {
                warn!("Checkpoint manager task failed to join cleanly: {}", e);
            }
        }

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

    /// Create a checkpoint for a specific partition; returns an error or the
    /// remote key prefix of the exported checkpoint if successful, or None if
    /// the export failed. TODO(eli): STRAIGHTEN OUT RETURN VALUES THIS IS STUPID
    pub async fn checkpoint_partition(&self, partition: &Partition) -> Result<Option<String>> {
        let start_time = Instant::now();

        let store = match self.store_manager.stores().get(&partition) {
            Some(entry) => entry.value(),

            None => {
                return Err(anyhow::anyhow!(
                    "Store not found for {}:{}",
                    partition.topic(),
                    partition.partition_number(),
                ))
            }
        };

        info!(
            "Checkpoint for {}:{} => creating local checkpoint at: {:?}",
            partition.topic(),
            partition.partition_number(),
            checkpoint_path
        );

        // Create checkpoint directory with timestamp (microseconds for uniqueness)
        // and ensure the checkpoint name is unique and lexicographically sortable
        let checkpoint_timestamp = self.generate_checkpoint_timestamp();
        let checkpoint_name = self.build_checkpoint_name(&partition, checkpoint_timestamp);
        let local_checkpoint_path =
            PathBuf::from(&self.config.local_checkpoint_dir).join(&checkpoint_name);

        // Ensure local checkpoint directory exists
        tokio::fs::create_dir_all(&self.config.local_checkpoint_dir)
            .await
            .context("Failed to create local checkpoint directory")?;

        // this creates the local RocksDB checkpoint
        match store.create_checkpoint_with_metadata(local_checkpoint_path) {
            Ok(sst_files) => {
                let checkpoint_duration = start_time.elapsed();
                metrics::histogram!(CHECKPOINT_DURATION_HISTOGRAM)
                    .record(checkpoint_duration.as_secs_f64());

                // Get checkpoint size
                let checkpoint_size = self.get_directory_size(&local_checkpoint_path).await?;
                metrics::histogram!(CHECKPOINT_SIZE_HISTOGRAM).record(checkpoint_size as f64);

                info!(
                    "Checkpoint for {}:{} => created local checkpoint at {:?} with {} SST files",
                    partition.topic(),
                    partition.partition_number(),
                    &local_checkpoint_path,
                    sst_files.len()
                );
            }

            Err(e) => {
                // Build the complete error chain
                let mut error_chain = vec![format!("{:?}", e)];
                let mut source = e.source();
                while let Some(err) = source {
                    error_chain.push(format!("Caused by: {err:?}"));
                    source = err.source();
                }

                error!(
                    "Checkpoint for {}:{} => failed local checkpoint at {:?}: {}",
                    partition.topic(),
                    partition.partition_number(),
                    &local_checkpoint_path,
                    error_chain.join(" -> ")
                );

                return Err(anyhow::anyhow!(error_chain.join(" -> ")));
            }
        }

        // Update metrics
        if let Err(e) = store.update_metrics() {
            warn!("Checkpoint for {}:{} => after local checkpoint at {:?}: failed store metrics update: {}",
            partition.topic(),
            partition.partition_number(),
            &local_checkpoint_path,
            e);
        }

        info!(
            "Checkpoint for {}:{} => creating remote checkpoint from source: {:?}",
            partition.topic(),
            partition.partition_number(),
            &local_checkpoint_path
        );

        match self.exporter.as_ref() {
            Some(exporter) => {
                // TODO(eli): log error here so return can be handled with ? operator by caller
                return exporter
                    .export_checkpoint(&local_checkpoint_path, &checkpoint_name, &store)
                    .await;
            }

            None => {
                warn!(
                    "Checkpoint for {}:{} at {:?} => no exporter configured, skipping upload",
                    partition.topic(),
                    partition.partition_number(),
                    checkpoint_path
                );

                Ok(None)
            }
        }
    }

    // TODO(eli): discussed breaking this in to path-like elements but so far
    // I'm leaning towards keeping it a single directory name. It's sortable,
    // simple to work with, and maintains a 1:1 mapping between local paths under
    // base dir and S3 snapshot paths under bucket key prefix. Can revisit if needed
    fn build_checkpoint_name(&self, partition: &Partition, checkpoint_timestamp: u128) -> String {
        format!(
            "{}_{}_{}_{:018}",
            CHECKPOINT_NAME_PREFIX,
            partition.topic(),
            partition.partition_number(),
            checkpoint_timestamp
        )
    }

    // Generates a UNIX epoch timestamp in microseconds as a u128
    fn generate_checkpoint_timestamp(&self) -> Result<u128> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("failed to generate checkpoint timestamp")?
            .as_micros()
    }

    async fn get_directory_size(&self, path: &Path) -> Result<u64> {
        let mut total_size = 0u64;
        let mut stack = vec![path.to_path_buf()];

        while let Some(current_path) = stack.pop() {
            let mut entries = tokio::fs::read_dir(&current_path)
                .await
                .with_context(|| format!("Failed to read directory: {current_path:?}"))?;

            while let Some(entry) = entries.next_entry().await? {
                let path = entry.path();
                let metadata = entry.metadata().await?;

                if metadata.is_dir() {
                    stack.push(path);
                } else {
                    total_size += metadata.len();
                }
            }
        }

        Ok(total_size)
    }

    async fn cleanup_local_checkpoints(&self) -> Result<()> {
        let checkpoint_dir = PathBuf::from(&self.config.local_checkpoint_dir);

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

        // Sort by name (which includes timestamp)
        checkpoint_dirs.sort();

        if checkpoint_dirs.len() <= self.config.max_local_checkpoints {
            return Ok(());
        }

        let dirs_to_remove = checkpoint_dirs.len() - self.config.max_local_checkpoints;

        for dir in checkpoint_dirs.into_iter().take(dirs_to_remove) {
            if let Err(e) = tokio::fs::remove_dir_all(&dir).await {
                error!("Failed to remove old checkpoint directory {:?}: {}", dir, e);
                // Continue with other removals
            } else {
                info!("Removed old checkpoint directory: {:?}", dir);
            }
        }

        Ok(())
    }
}

impl Drop for CheckpointManager {
    fn drop(&mut self) {
        // Cancel the task on drop
        self.cancel_token.cancel();

        // We can't await in drop, so the task will clean up asynchronously
        if self.checkpoint_tasks.len() > 0 {
            debug!("CheckpointManager dropped, flush task will terminate");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};
    use common_types::RawEvent;
    use std::{collections::HashMap, path::PathBuf};
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
        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        assert_eq!(manager.flush_interval, Duration::from_secs(30));
        assert!(manager.flush_task.is_none());
    }

    #[tokio::test]
    async fn test_checkpoint_manager_start_stop() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let mut manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        // Start the manager
        manager.start();
        assert!(manager.flush_task.is_some());

        // Stop the manager
        manager.stop().await;
        assert!(manager.flush_task.is_none());
    }

    #[tokio::test]
    async fn test_flush_all_empty() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

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

        let manager = CheckpointManager::new(store_manager.clone(), Duration::from_secs(30));

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

        stores.insert(Partition::new("topic1".to_string(), 0), store);

        let manager = CheckpointManager::new(store_manager.clone(), Duration::from_secs(30));

        // Create checkpoint
        let checkpoint_path = temp_dir.path().join("checkpoint");
        let result = manager
            .checkpoint_partition("topic1", 0, &checkpoint_path)
            .await;

        assert!(result.is_ok());
        assert!(checkpoint_path.exists());
    }

    #[tokio::test]
    async fn test_checkpoint_partition_not_found() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        let temp_dir = TempDir::new().unwrap();
        let checkpoint_path = temp_dir.path().join("checkpoint");

        // Should fail for non-existent partition
        let result = manager
            .checkpoint_partition("topic1", 0, &checkpoint_path)
            .await;
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Store not found"));
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
        let mut manager = CheckpointManager::new(store_manager.clone(), Duration::from_millis(100));

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
        let mut manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        // Start once
        manager.start();
        assert!(manager.flush_task.is_some());

        // Start again - should warn but not panic
        manager.start();
        assert!(manager.flush_task.is_some());

        manager.stop().await;
    }

    #[tokio::test]
    async fn test_drop_cancels_task() {
        let stores = Arc::new(StoreManager::new(DeduplicationStoreConfig {
            path: PathBuf::from("test"),
            max_capacity: 1_000_000,
        }));
        let mut manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        manager.start();
        let cancel_token = manager.cancel_token.clone();

        assert!(!cancel_token.is_cancelled());

        // Drop the manager
        drop(manager);

        // Token should be cancelled
        assert!(cancel_token.is_cancelled());
    }
}
