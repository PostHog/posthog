use anyhow::Result;
use dashmap::DashMap;
use std::sync::Arc;
use std::time::Duration;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};

use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::DeduplicationStore;

/// Manages checkpointing and periodic flushing for all deduplication stores
pub struct CheckpointManager {
    /// Reference to all active stores
    stores: Arc<DashMap<Partition, DeduplicationStore>>,

    /// Cancellation token for the flush task
    cancel_token: CancellationToken,

    /// Handle to the flush task
    flush_task: Option<JoinHandle<()>>,

    /// Flush interval
    flush_interval: Duration,
}

impl CheckpointManager {
    /// Create a new checkpoint manager
    pub fn new(
        stores: Arc<DashMap<Partition, DeduplicationStore>>,
        flush_interval: Duration,
    ) -> Self {
        Self {
            stores,
            cancel_token: CancellationToken::new(),
            flush_task: None,
            flush_interval,
        }
    }

    /// Start the periodic flush task
    pub fn start(&mut self) {
        if self.flush_task.is_some() {
            warn!("Checkpoint manager already started");
            return;
        }

        info!(
            "Starting checkpoint manager with flush interval: {:?}",
            self.flush_interval
        );

        let stores = self.stores.clone();
        let cancel = self.cancel_token.child_token();
        let flush_interval = self.flush_interval;

        let handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(flush_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            // Skip first tick to avoid immediate flush
            interval.tick().await;

            loop {
                tokio::select! {
                    _ = cancel.cancelled() => {
                        info!("Checkpoint manager shutting down");
                        break;
                    }
                    _ = interval.tick() => {
                        let store_count = stores.len();
                        if store_count == 0 {
                            debug!("No stores to flush");
                            continue;
                        }

                        info!("Starting periodic flush for {} stores", store_count);

                        // Snapshot all stores to avoid holding locks
                        let snapshot: Vec<(Partition, DeduplicationStore)> = stores
                            .iter()
                            .map(|entry| {
                                let (partition, store) = entry.pair();
                                (partition.clone(), store.clone())
                            })
                            .collect();

                        // Flush and update metrics for each store
                        for (partition, store) in snapshot {
                            debug!("Flushing store {}:{}", partition.topic(), partition.partition_number());

                            // Flush the store
                            if let Err(e) = store.flush() {
                                error!("Failed to flush store {}:{}: {}", partition.topic(), partition.partition_number(), e);
                                continue;
                            }

                            // Update metrics
                            if let Err(e) = store.update_metrics() {
                                warn!("Failed to update metrics for store {}:{}: {}", partition.topic(), partition.partition_number(), e);
                            }
                        }

                        info!("Completed periodic flush for {} stores", store_count);
                    }
                }
            }
        });

        self.flush_task = Some(handle);
    }

    /// Stop the checkpoint manager
    pub async fn stop(&mut self) {
        info!("Stopping checkpoint manager");

        // Cancel the task
        self.cancel_token.cancel();

        // Wait for task to complete
        if let Some(handle) = self.flush_task.take() {
            if let Err(e) = handle.await {
                warn!(
                    "Checkpoint manager flush task failed to join cleanly: {}",
                    e
                );
            }
        }

        info!("Checkpoint manager stopped");
    }

    /// Trigger an immediate flush of all stores
    pub async fn flush_all(&self) -> Result<()> {
        info!("Triggering manual flush of all stores");

        let snapshot: Vec<(Partition, DeduplicationStore)> = self
            .stores
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

    /// Create a checkpoint for a specific partition
    pub async fn checkpoint_partition(
        &self,
        topic: &str,
        partition: i32,
        checkpoint_path: &std::path::Path,
    ) -> Result<Vec<String>> {
        let key = Partition::new(topic.to_string(), partition);

        match self.stores.get(&key) {
            Some(entry) => {
                let store = entry.value();
                info!(
                    "Creating checkpoint for {}:{} at {:?}",
                    key.topic(),
                    key.partition_number(),
                    checkpoint_path
                );
                store.create_checkpoint_with_metadata(checkpoint_path)
            }
            None => Err(anyhow::anyhow!(
                "Store not found for {}:{}",
                key.topic(),
                partition
            )),
        }
    }
}

impl Drop for CheckpointManager {
    fn drop(&mut self) {
        // Cancel the task on drop
        self.cancel_token.cancel();

        // We can't await in drop, so the task will clean up asynchronously
        if self.flush_task.is_some() {
            debug!("CheckpointManager dropped, flush task will terminate");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};
    use common_types::RawEvent;
    use std::collections::HashMap;
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
        let stores = Arc::new(DashMap::new());
        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        assert_eq!(manager.flush_interval, Duration::from_secs(30));
        assert!(manager.flush_task.is_none());
    }

    #[tokio::test]
    async fn test_checkpoint_manager_start_stop() {
        let stores = Arc::new(DashMap::new());
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
        let stores = Arc::new(DashMap::new());
        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        // Flushing empty stores should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_flush_all_with_stores() {
        let stores = Arc::new(DashMap::new());

        // Add some test stores
        let (store1, _dir1) = create_test_store("topic1", 0);
        let (store2, _dir2) = create_test_store("topic1", 1);

        // Add events to the stores
        let event = create_test_event();
        store1.handle_event_with_raw(&event).unwrap();
        store2.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store1);
        stores.insert(Partition::new("topic1".to_string(), 1), store2);

        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

        // Flush all should succeed
        assert!(manager.flush_all().await.is_ok());
    }

    #[tokio::test]
    async fn test_checkpoint_partition() {
        let stores = Arc::new(DashMap::new());
        let (store, temp_dir) = create_test_store("topic1", 0);

        // Add an event to the store
        let event = create_test_event();
        store.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store);

        let manager = CheckpointManager::new(stores.clone(), Duration::from_secs(30));

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
        let stores = Arc::new(DashMap::new());
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
        let stores = Arc::new(DashMap::new());
        let (store, _dir) = create_test_store("topic1", 0);

        // Add an event
        let event = create_test_event();
        store.handle_event_with_raw(&event).unwrap();

        stores.insert(Partition::new("topic1".to_string(), 0), store);

        // Create manager with short interval for testing
        let mut manager = CheckpointManager::new(stores.clone(), Duration::from_millis(100));

        // Start the manager
        manager.start();

        // Wait for a few flush cycles
        tokio::time::sleep(Duration::from_millis(350)).await;

        // Stop the manager
        manager.stop().await;
    }

    #[tokio::test]
    async fn test_double_start() {
        let stores = Arc::new(DashMap::new());
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
        let stores = Arc::new(DashMap::new());
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
