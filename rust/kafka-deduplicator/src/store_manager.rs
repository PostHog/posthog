use anyhow::{Context, Result};
use dashmap::DashMap;
use std::path::PathBuf;
use tracing::{debug, error, info, warn};

use crate::kafka::types::Partition;
use crate::rocksdb::deduplication_store::{DeduplicationStore, DeduplicationStoreConfig};

/// Manages the lifecycle of deduplication stores, handling concurrent access
/// and creation in a thread-safe manner.
///
/// The StoreManager ensures that:
/// - Only one store exists per partition
/// - Store creation is atomic and handles race conditions
/// - Parent directories are created as needed
/// - Failed store creations are properly handled
pub struct StoreManager {
    /// Map of partition to deduplication store
    stores: DashMap<Partition, DeduplicationStore>,

    /// Configuration for creating new stores
    store_config: DeduplicationStoreConfig,
}

impl StoreManager {
    /// Create a new store manager with the given configuration
    pub fn new(store_config: DeduplicationStoreConfig) -> Self {
        Self {
            stores: DashMap::new(),
            store_config,
        }
    }

    /// Get an existing store for a partition, if it exists
    pub fn get(&self, topic: &str, partition: i32) -> Option<DeduplicationStore> {
        let partition_key = Partition::new(topic.to_string(), partition);
        self.stores.get(&partition_key).map(|entry| entry.clone())
    }

    /// Get or create a deduplication store for a specific partition
    ///
    /// This method handles concurrent access safely:
    /// - If the store exists, it returns it immediately
    /// - If the store doesn't exist, it creates it atomically
    /// - If multiple workers try to create the same store, only one succeeds
    pub async fn get_or_create(&self, topic: &str, partition: i32) -> Result<DeduplicationStore> {
        let partition_key = Partition::new(topic.to_string(), partition);

        // Fast path: check if store already exists
        if let Some(store) = self.stores.get(&partition_key) {
            debug!(
                "Using existing deduplication store for partition {}:{}",
                topic, partition
            );
            return Ok(store.clone());
        }

        // Slow path: need to create the store
        // DashMap's entry API ensures only one worker creates the store
        let result = self
            .stores
            .entry(partition_key.clone())
            .or_try_insert_with(|| {
                // Generate store path inside the closure so only the creating thread generates it
                let store_path = self.build_store_path(topic, partition);
                // Ensure parent directory exists
                // Note: This is inside the closure so only the creating thread does this
                self.ensure_directory_exists(&store_path)?;
                info!(
                    "Creating new deduplication store for partition {}:{} at path: {}",
                    topic, partition, store_path
                );

                let mut partition_config = self.store_config.clone();
                partition_config.path = PathBuf::from(&store_path);

                DeduplicationStore::new(partition_config, topic.to_string(), partition)
                    .with_context(|| {
                        format!(
                            "Failed to create deduplication store for {topic}:{partition} at path {store_path}",                            
                        )
                    })
            });

        match result {
            Ok(entry) => {
                info!("Successfully created deduplication store for partition {topic}:{partition}",);
                Ok(entry.clone())
            }
            Err(e) => {
                // This could happen if:
                // 1. Another worker created the store between our check and creation
                // 2. RocksDB failed to open/create the database

                // Check if another worker succeeded
                if let Some(store) = self.stores.get(&partition_key) {
                    warn!(
                        "Store for {}:{} was created by another worker, using existing store",
                        topic, partition
                    );
                    Ok(store.clone())
                } else {
                    // Real failure - no one succeeded in creating the store
                    // Build the complete error chain
                    let mut error_chain = vec![format!("{:?}", e)];
                    let mut source = e.source();
                    while let Some(err) = source {
                        error_chain.push(format!("Caused by: {err:?}"));
                        source = err.source();
                    }

                    error!(
                        "Failed to create store for {}:{} - {}",
                        topic,
                        partition,
                        error_chain.join(" -> ")
                    );

                    Err(e)
                }
            }
        }
    }

    /// Remove a store from management and clean up its files (used during partition rebalancing)
    ///
    /// This method:
    /// - Removes the store from the map
    /// - Drops the store (closing RocksDB)
    /// - Deletes the store's files from disk (best effort)
    pub fn remove(&self, topic: &str, partition: i32) -> Result<()> {
        let partition_key = Partition::new(topic.to_string(), partition);

        // Remove the store from the map
        if let Some((_, store)) = self.stores.remove(&partition_key) {
            info!(
                "Removing deduplication store for partition {}:{}",
                topic, partition
            );

            // Get the actual store path from the store instance (it has the timestamp)
            let store_path = store.get_db_path().display().to_string();

            // Drop the store explicitly to close RocksDB
            drop(store);

            // Best effort deletion of the store directory
            // We don't fail if this doesn't work - the directory might already be gone
            // or might be recreated by a concurrent operation
            let path_buf = PathBuf::from(&store_path);
            if path_buf.exists() {
                match std::fs::remove_dir_all(&path_buf) {
                    Ok(_) => {
                        info!(
                            "Deleted store directory for partition {}:{} at path {}",
                            topic, partition, store_path
                        );
                    }
                    Err(e) => {
                        // Log but don't fail - this might happen if another process
                        // is already recreating the store
                        warn!(
                            "Failed to remove store directory for {}:{} at path {}: {}. This is usually harmless.",
                            topic, partition, store_path, e
                        );
                    }
                }
            }
        }

        Ok(())
    }

    /// Get a reference to the underlying stores map
    /// Used by checkpoint manager and rebalance handler
    pub fn stores(&self) -> &DashMap<Partition, DeduplicationStore> {
        &self.stores
    }

    pub fn get_active_store_count(&self) -> usize {
        self.stores.len()
    }

    /// Shutdown all stores cleanly
    ///
    /// This closes all RocksDB instances but does NOT delete the files
    /// (since they may be needed when the service restarts)
    pub async fn shutdown(&self) {
        info!("Shutting down all deduplication stores");

        // Clear the map, which will drop all stores
        self.stores.clear();

        info!("All deduplication stores have been closed");
    }

    /// Build the path for a store based on topic and partition
    /// Each store gets a unique timestamp-based subdirectory to avoid conflicts
    fn build_store_path(&self, topic: &str, partition: i32) -> String {
        // Create a unique subdirectory for this store instance
        let timestamp = chrono::Utc::now().timestamp_millis();
        format!(
            "{}/{}_{}/{}",
            self.store_config.path.display(),
            topic.replace('/', "_"),
            partition,
            timestamp
        )
    }

    /// Ensure the parent directory for a store path exists
    fn ensure_directory_exists(&self, store_path: &str) -> Result<()> {
        let path_buf = PathBuf::from(store_path);

        // RocksDB will create the final directory, we just need the parent
        if let Some(parent) = path_buf.parent() {
            if !parent.exists() {
                std::fs::create_dir_all(parent).with_context(|| {
                    format!("Failed to create parent directory: {}", parent.display())
                })?;
                info!("Created parent directory: {}", parent.display());
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::RawEvent;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_get_or_create_store() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024, // 1GB
        };

        let manager = StoreManager::new(config);

        // First creation should succeed
        let store1 = manager.get_or_create("test-topic", 0).await.unwrap();

        // Second call should return the same store
        let store2 = manager.get_or_create("test-topic", 0).await.unwrap();

        // Stores should be the same instance - verify by checking they share state
        // Add an event to store1
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Add event through store1
        assert!(store1.handle_event_with_raw(&event).unwrap());

        // Event should be seen as duplicate in store2 (proving they're the same store)
        assert!(!store2.handle_event_with_raw(&event).unwrap());
    }

    #[tokio::test]
    async fn test_concurrent_store_creation() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
        };

        let manager = Arc::new(StoreManager::new(config));

        // Spawn multiple tasks trying to create the same store
        let mut handles = vec![];
        for _ in 0..10 {
            let manager_clone = manager.clone();
            let handle =
                tokio::spawn(
                    async move { manager_clone.get_or_create("concurrent-topic", 42).await },
                );
            handles.push(handle);
        }

        // All should succeed and return the same store
        let mut stores = vec![];
        for handle in handles {
            let store = handle.await.unwrap().unwrap();
            stores.push(store);
        }

        // All stores should be the same instance - verify by checking they share state
        // Add an event through the first store
        let event = RawEvent {
            event: "concurrent_test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("concurrent_user".to_string())),
            token: Some("concurrent_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Add event through first store
        assert!(stores[0].handle_event_with_raw(&event).unwrap());

        // All other stores should see it as duplicate (proving they're the same store)
        for store in &stores[1..] {
            assert!(!store.handle_event_with_raw(&event).unwrap());
        }
    }
}
