use anyhow::{Context, Result};
use dashmap::DashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

use crate::kafka::types::Partition;
use crate::metrics::MetricsHelper;
use crate::rocksdb::metrics_consts::*;
use crate::store::{DeduplicationStore, DeduplicationStoreConfig};

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

    /// Metrics helper for global metrics
    metrics: MetricsHelper,
}

impl StoreManager {
    /// Create a new store manager with the given configuration
    pub fn new(store_config: DeduplicationStoreConfig) -> Self {
        let metrics = MetricsHelper::new().with_label("service", "kafka-deduplicator");

        Self {
            stores: DashMap::new(),
            store_config,
            metrics,
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

    /// Cleanup old entries across all stores to maintain global capacity
    ///
    /// This method checks the total size across all stores and triggers cleanup
    /// on individual stores if the global capacity is exceeded. Cleanup is distributed
    /// across all stores by removing a percentage of each store's time range.
    pub fn cleanup_old_entries_if_needed(&self) -> Result<u64> {
        let start_time = Instant::now();

        // If max_capacity is 0, no cleanup needed (unlimited)
        if self.store_config.max_capacity == 0 {
            return Ok(0);
        }

        // Calculate total size across all stores
        let mut total_size = 0u64;
        for entry in self.stores.iter() {
            let store = entry.value();
            // Get size of all column families for this store
            if let Ok(size) = store.get_total_size() {
                total_size += size;
            }
        }

        // Check if we're under capacity
        if total_size <= self.store_config.max_capacity {
            return Ok(0); // Under capacity, no cleanup needed
        }

        info!(
            "Global store size {} exceeds max capacity {}, triggering cleanup",
            total_size, self.store_config.max_capacity
        );

        // We need to clean up - target 80% of max capacity
        let target_size = (self.store_config.max_capacity as f64 * 0.8) as u64;
        let bytes_to_free = total_size.saturating_sub(target_size);

        // Calculate cleanup percentage based on how much we need to free
        // If we need to free 20% of total size, clean up 20% of time range from each store
        let cleanup_percentage = (bytes_to_free as f64 / total_size as f64).min(0.3); // Cap at 30% max

        info!(
            "Cleaning up {:.1}% of time range from each store (need to free {} bytes)",
            cleanup_percentage * 100.0,
            bytes_to_free
        );

        // Cleanup stores with the calculated percentage
        let mut total_bytes_freed = 0u64;

        // Clean up all stores with the same percentage to ensure fair distribution
        for entry in self.stores.iter() {
            let store = entry.value();
            match store.cleanup_old_entries_with_percentage(cleanup_percentage) {
                Ok(bytes_freed) => {
                    total_bytes_freed += bytes_freed;
                    if bytes_freed > 0 {
                        info!(
                            "Freed {} bytes from store {}:{}",
                            bytes_freed,
                            store.get_topic(),
                            store.get_partition()
                        );
                    }
                }
                Err(e) => {
                    warn!(
                        "Failed to cleanup store {}:{}: {}",
                        store.get_topic(),
                        store.get_partition(),
                        e
                    );
                }
            }
        }

        // Emit cleanup metrics
        let duration = start_time.elapsed();
        self.metrics
            .counter(CLEANUP_OPERATIONS_COUNTER)
            .increment(1);
        self.metrics
            .histogram(CLEANUP_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());
        self.metrics
            .histogram(CLEANUP_BYTES_FREED_HISTOGRAM)
            .record(total_bytes_freed as f64);

        info!(
            "Global cleanup completed: freed {} bytes in {:?}",
            total_bytes_freed, duration
        );

        Ok(total_bytes_freed)
    }

    /// Check if cleanup is needed based on current global size
    pub fn needs_cleanup(&self) -> bool {
        if self.store_config.max_capacity == 0 {
            return false;
        }

        let mut total_size = 0u64;
        for entry in self.stores.iter() {
            if let Ok(size) = entry.value().get_total_size() {
                total_size += size;
            }
        }

        total_size > self.store_config.max_capacity
    }

    /// Start a periodic cleanup task that runs in the background
    /// Returns a handle that can be used to stop the task
    pub fn start_periodic_cleanup(
        self: Arc<Self>,
        cleanup_interval: Duration,
    ) -> CleanupTaskHandle {
        let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel();
        let manager = self;

        let handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(cleanup_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            info!(
                "Started periodic cleanup task with interval of {:?}",
                cleanup_interval
            );

            loop {
                tokio::select! {
                    _ = interval.tick() => {
                        debug!("Running periodic cleanup check");

                        if manager.needs_cleanup() {
                            info!("Global capacity exceeded, triggering cleanup");
                            match manager.cleanup_old_entries_if_needed() {
                                Ok(bytes_freed) => {
                                    if bytes_freed > 0 {
                                        info!("Periodic cleanup freed {} bytes", bytes_freed);
                                    }
                                }
                                Err(e) => {
                                    error!("Periodic cleanup failed: {}", e);
                                }
                            }
                        } else {
                            debug!("No cleanup needed, stores within capacity");
                        }
                    }
                    _ = &mut shutdown_rx => {
                        info!("Cleanup task received shutdown signal");
                        break;
                    }
                }
            }

            info!("Cleanup task shutting down");
        });

        CleanupTaskHandle {
            handle,
            shutdown_tx: Some(shutdown_tx),
        }
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

/// Handle for the cleanup task that allows graceful shutdown
pub struct CleanupTaskHandle {
    handle: JoinHandle<()>,
    shutdown_tx: Option<tokio::sync::oneshot::Sender<()>>,
}

impl CleanupTaskHandle {
    /// Stop the cleanup task gracefully
    pub async fn stop(mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
        }

        match tokio::time::timeout(Duration::from_secs(5), self.handle).await {
            Ok(Ok(())) => info!("Cleanup task shut down successfully"),
            Ok(Err(e)) => warn!("Cleanup task failed: {}", e),
            Err(_) => warn!("Cleanup task shutdown timed out"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::RawEvent;
    use std::sync::Arc;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_global_capacity_management() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 100, // Very small capacity to test the logic
        };

        let manager = Arc::new(StoreManager::new(config));

        // Test that needs_cleanup works correctly
        assert!(
            !manager.needs_cleanup(),
            "Should not need cleanup when empty"
        );

        // Create stores
        let store1 = manager.get_or_create("test-topic", 0).await.unwrap();
        let _store2 = manager.get_or_create("test-topic", 1).await.unwrap();

        // Add some events
        for i in 0..10 {
            let event = RawEvent {
                uuid: Some(uuid::Uuid::new_v4()),
                event: format!("test_event_{i}"),
                distinct_id: Some(serde_json::Value::String(format!("user_{i}"))),
                token: Some("test_token".to_string()),
                timestamp: Some("2021-01-01T00:00:00Z".to_string()),
                properties: std::collections::HashMap::new(),
                ..Default::default()
            };
            store1.handle_event_with_raw(&event).unwrap();
        }

        // Test that cleanup can be called without error
        let result = manager.cleanup_old_entries_if_needed();
        assert!(result.is_ok(), "Cleanup should not error");

        // Test with zero capacity
        let zero_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 0,
        };
        let zero_manager = Arc::new(StoreManager::new(zero_config));
        assert!(
            !zero_manager.needs_cleanup(),
            "Should never need cleanup with zero capacity"
        );
    }

    #[tokio::test]
    async fn test_periodic_cleanup_task() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 5_000, // Small capacity
        };

        let manager = Arc::new(StoreManager::new(config));

        // Start periodic cleanup with short interval for testing
        let cleanup_handle = manager.clone().start_periodic_cleanup(
            Duration::from_millis(100), // Very short interval for testing
        );

        // Create a store and add data
        let store = manager.get_or_create("test-topic", 0).await.unwrap();

        // Add old events that should be cleaned up
        for i in 0..50 {
            let event = RawEvent {
                uuid: Some(uuid::Uuid::new_v4()),
                event: "test_event".to_string(),
                distinct_id: Some(serde_json::Value::String(format!("user_{i}"))),
                token: Some("test_token".to_string()),
                timestamp: Some("2021-01-01T00:00:00Z".to_string()), // Old timestamp
                properties: std::collections::HashMap::from([(
                    "data".to_string(),
                    serde_json::json!(format!("value_{}", i)),
                )]),
                ..Default::default()
            };
            store.handle_event_with_raw(&event).unwrap();
        }

        store.flush().unwrap();

        // Wait for cleanup task to run at least once
        tokio::time::sleep(Duration::from_millis(200)).await;

        // Stop the cleanup task
        cleanup_handle.stop().await;
    }

    #[tokio::test]
    async fn test_cleanup_task_graceful_shutdown() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1_000_000,
        };

        let manager = Arc::new(StoreManager::new(config));

        // Start cleanup task
        let cleanup_handle = manager.clone().start_periodic_cleanup(
            Duration::from_secs(60), // Long interval
        );

        // Give it time to start
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Stop should complete quickly even with long interval
        let start = std::time::Instant::now();
        cleanup_handle.stop().await;
        let elapsed = start.elapsed();

        // Should shutdown within the timeout (5 seconds)
        assert!(elapsed < Duration::from_secs(6));
    }

    #[tokio::test]
    async fn test_cleanup_with_zero_capacity() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 0, // Unlimited capacity
        };

        let manager = Arc::new(StoreManager::new(config));

        // Should never need cleanup with unlimited capacity
        assert!(!manager.needs_cleanup());

        // Cleanup should return 0 bytes freed
        let bytes_freed = manager.cleanup_old_entries_if_needed().unwrap();
        assert_eq!(bytes_freed, 0);
    }

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
