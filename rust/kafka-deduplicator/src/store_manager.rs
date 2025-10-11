use anyhow::{Context, Result};
use dashmap::DashMap;
use std::fmt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

use crate::kafka::types::Partition;
use crate::metrics::MetricsHelper;
use crate::metrics_const::{
    CLEANUP_BYTES_FREED_HISTOGRAM, CLEANUP_DURATION_HISTOGRAM, CLEANUP_OPERATIONS_COUNTER,
};
use crate::store::{DeduplicationStore, DeduplicationStoreConfig};

/// Information about folder sizes on disk
#[derive(Debug, Clone)]
struct FolderInfo {
    name: String,
    size_bytes: u64,
    subfolder_count: usize,
}

impl FolderInfo {
    fn size_mb(&self) -> f64 {
        self.size_bytes as f64 / (1024.0 * 1024.0)
    }
}

impl fmt::Display for FolderInfo {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {:.2} MB", self.name, self.size_mb())
    }
}

/// Information about assigned partitions
#[derive(Debug, Clone)]
struct AssignedPartition {
    topic: String,
    partition: i32,
}

impl fmt::Display for AssignedPartition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}", self.topic, self.partition)
    }
}

/// Combined cleanup status information
#[derive(Debug)]
struct CleanupStatus {
    assigned_partitions: Vec<AssignedPartition>,
    folder_info: Vec<FolderInfo>,
    total_disk_usage_mb: f64,
}

impl fmt::Display for CleanupStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Format partitions as a compact list
        let partitions: Vec<String> = self
            .assigned_partitions
            .iter()
            .map(|p| p.to_string())
            .collect();

        // Format folder info as compact list with sizes and subfolder counts
        let folders: Vec<String> = self
            .folder_info
            .iter()
            .map(|fi| {
                format!(
                    "{}({} subdirs):{:.2}MB",
                    fi.name,
                    fi.subfolder_count,
                    fi.size_mb()
                )
            })
            .collect();

        write!(
            f,
            "CleanupStatus {{ partitions: [{}], folders: [{}], total_disk_mb: {:.2}, partition_count: {}, folder_count: {} }}",
            partitions.join(", "),
            folders.join(", "),
            self.total_disk_usage_mb,
            self.assigned_partitions.len(),
            self.folder_info.len()
        )
    }
}

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

    /// Flag to prevent concurrent cleanup operations
    cleanup_running: AtomicBool,
}

impl StoreManager {
    /// Create a new store manager with the given configuration
    pub fn new(store_config: DeduplicationStoreConfig) -> Self {
        let metrics = MetricsHelper::new().with_label("service", "kafka-deduplicator");

        Self {
            stores: DashMap::new(),
            store_config,
            metrics,
            cleanup_running: AtomicBool::new(false),
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
    /// - Deletes ALL files for this partition from disk (including old timestamp directories)
    pub fn remove(&self, topic: &str, partition: i32) -> Result<()> {
        let partition_key = Partition::new(topic.to_string(), partition);

        // Remove the store from the map
        if let Some((_, store)) = self.stores.remove(&partition_key) {
            info!(
                "Removing deduplication store for partition {}:{}",
                topic, partition
            );

            // Drop the store explicitly to close RocksDB before deleting files
            drop(store);
        }

        // Delete the entire topic_partition directory (not just the current timestamp subdirectory)
        // This ensures we clean up all historical data for this partition
        let partition_dir = format!(
            "{}/{}_{}",
            self.store_config.path.display(),
            topic.replace('/', "_"),
            partition
        );

        let partition_path = PathBuf::from(&partition_dir);
        if partition_path.exists() {
            match std::fs::remove_dir_all(&partition_path) {
                Ok(_) => {
                    info!(
                        "Deleted entire partition directory for {}:{} at path {}",
                        topic, partition, partition_dir
                    );
                }
                Err(e) => {
                    // Log but don't fail - this might happen if another process
                    // is already recreating the store
                    warn!(
                        "Failed to remove partition directory for {}:{} at path {}: {}. This is usually harmless.",
                        topic, partition, partition_dir, e
                    );
                }
            }
        } else {
            debug!(
                "Partition directory for {}:{} doesn't exist at path {}",
                topic, partition, partition_dir
            );
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
        // Try to acquire cleanup lock - if another cleanup is running, skip this one
        if self
            .cleanup_running
            .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .is_err()
        {
            debug!("Cleanup already running, skipping this cycle");
            return Ok(0);
        }

        // Ensure we release the lock when we're done
        let _guard = CleanupGuard {
            flag: &self.cleanup_running,
        };

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
                        "Failed to cleanup store {}:{}: {:#}",
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
        // Log folder sizes and assigned partitions
        self.log_folder_sizes_and_partitions();

        if self.store_config.max_capacity == 0 {
            return false;
        }

        let mut total_size = 0u64;
        for entry in self.stores.iter() {
            if let Ok(size) = entry.value().get_total_size() {
                total_size += size;
            }
        }

        info!(
            "Total size of all stores: {} bytes, max capacity: {} bytes",
            total_size, self.store_config.max_capacity
        );
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
                        info!("Cleanup task tick - running periodic cleanup check");

                        // First, clean up orphaned directories (unassigned partitions)
                        match manager.cleanup_orphaned_directories() {
                            Ok(0) => {
                                debug!("No orphaned directories found");
                            }
                            Ok(bytes_freed) => {
                                info!("Cleaned up {} bytes of orphaned directories", bytes_freed);
                            }
                            Err(e) => {
                                warn!("Failed to clean up orphaned directories: {}", e);
                            }
                        }

                        // Then check if we need capacity-based cleanup
                        if manager.needs_cleanup() {
                            info!("Global capacity exceeded, triggering cleanup");
                            match manager.cleanup_old_entries_if_needed() {
                                Ok(0) => {
                                    debug!("Cleanup skipped (may be already running or no data to clean)");
                                }
                                Ok(bytes_freed) => {
                                    info!("Periodic cleanup freed {} bytes", bytes_freed);
                                }
                                Err(e) => {
                                    error!("Periodic cleanup failed: {}", e);
                                }
                            }
                        } else {
                            info!("No cleanup needed, stores within capacity");
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

    /// Log folder sizes and assigned partitions for debugging
    fn log_folder_sizes_and_partitions(&self) {
        let status = self.get_cleanup_status();
        info!("{}", status);
    }

    /// Get cleanup status information
    fn get_cleanup_status(&self) -> CleanupStatus {
        // Get assigned partitions
        let mut assigned_partitions = Vec::new();
        for entry in self.stores.iter() {
            let partition = entry.key();
            assigned_partitions.push(AssignedPartition {
                topic: partition.topic().to_string(),
                partition: partition.partition_number(),
            });
        }

        // Sort partitions for consistent output
        assigned_partitions
            .sort_by(|a, b| a.topic.cmp(&b.topic).then(a.partition.cmp(&b.partition)));

        // Get folder sizes from filesystem
        let mut folder_info = Vec::new();
        let mut total_disk_usage_bytes = 0u64;

        if let Ok(entries) = std::fs::read_dir(&self.store_config.path) {
            for entry in entries.flatten() {
                if let Ok(metadata) = entry.metadata() {
                    if metadata.is_dir() {
                        let partition_folder_name = entry.file_name().to_string_lossy().to_string();
                        let folder_size =
                            StoreManager::get_directory_size(&entry.path()).unwrap_or(0);

                        // Count timestamped subdirectories (actual store instances)
                        let mut timestamped_stores_count = 0;
                        if let Ok(subentries) = std::fs::read_dir(entry.path()) {
                            timestamped_stores_count = subentries
                                .flatten()
                                .filter(|e| {
                                    // Check if it's a directory and looks like a timestamp
                                    e.metadata().map(|m| m.is_dir()).unwrap_or(false)
                                })
                                .count();
                        }

                        total_disk_usage_bytes += folder_size;
                        folder_info.push(FolderInfo {
                            name: partition_folder_name,
                            size_bytes: folder_size,
                            subfolder_count: timestamped_stores_count,
                        });
                    }
                }
            }

            // Sort by size descending
            folder_info.sort_by(|a, b| b.size_bytes.cmp(&a.size_bytes));
        }

        CleanupStatus {
            assigned_partitions,
            folder_info,
            total_disk_usage_mb: total_disk_usage_bytes as f64 / (1024.0 * 1024.0),
        }
    }

    /// Calculate the size of a directory recursively
    fn get_directory_size(path: &std::path::Path) -> Result<u64> {
        let mut size = 0u64;

        if let Ok(entries) = std::fs::read_dir(path) {
            for entry in entries.flatten() {
                if let Ok(metadata) = entry.metadata() {
                    if metadata.is_file() {
                        size += metadata.len();
                    } else if metadata.is_dir() {
                        size += StoreManager::get_directory_size(&entry.path()).unwrap_or(0);
                    }
                }
            }
        }

        Ok(size)
    }

    /// Clean up orphaned directories that don't belong to any assigned partition
    pub fn cleanup_orphaned_directories(&self) -> Result<u64> {
        let mut total_freed = 0u64;

        // Build a set of currently assigned partition directories
        let mut assigned_dirs = std::collections::HashSet::new();
        for entry in self.stores.iter() {
            let partition = entry.key();
            let dir_name = format!(
                "{}_{}",
                partition.topic().replace('/', "_"),
                partition.partition_number()
            );
            assigned_dirs.insert(dir_name);
        }

        info!(
            "Checking for orphaned directories. Currently assigned: {:?}",
            assigned_dirs
        );

        // Scan the store directory for all partition directories
        if let Ok(entries) = std::fs::read_dir(&self.store_config.path) {
            for entry in entries.flatten() {
                if let Ok(metadata) = entry.metadata() {
                    if metadata.is_dir() {
                        let dir_name = entry.file_name().to_string_lossy().to_string();

                        // Check if this directory matches the pattern topic_partition
                        // and is not in our assigned set
                        if dir_name.contains('_') && !assigned_dirs.contains(&dir_name) {
                            // This is an orphaned directory
                            let dir_path = entry.path();
                            let dir_size = Self::get_directory_size(&dir_path).unwrap_or(0);

                            match std::fs::remove_dir_all(&dir_path) {
                                Ok(_) => {
                                    info!(
                                        "Removed orphaned directory {} ({:.2} MB)",
                                        dir_name,
                                        dir_size as f64 / (1024.0 * 1024.0)
                                    );
                                    total_freed += dir_size;
                                }
                                Err(e) => {
                                    warn!(
                                        "Failed to remove orphaned directory {}: {}",
                                        dir_name, e
                                    );
                                }
                            }
                        }
                    }
                }
            }
        }

        if total_freed > 0 {
            info!(
                "Cleaned up {:.2} MB of orphaned directories",
                total_freed as f64 / (1024.0 * 1024.0)
            );
        } else {
            debug!("No orphaned directories found");
        }

        Ok(total_freed)
    }
}

/// Guard to ensure cleanup flag is released when dropped
struct CleanupGuard<'a> {
    flag: &'a AtomicBool,
}

impl<'a> Drop for CleanupGuard<'a> {
    fn drop(&mut self) {
        self.flag.store(false, Ordering::Release);
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
    use crate::store::{TimestampKey, TimestampMetadata};

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
            // Add test data directly to the store
            let key = TimestampKey::from(&event);
            let metadata = TimestampMetadata::new(&event);
            store1.put_timestamp_record(&key, &metadata).unwrap();
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
            // Add test data directly to the store
            let key = TimestampKey::from(&event);
            let metadata = TimestampMetadata::new(&event);
            store.put_timestamp_record(&key, &metadata).unwrap();
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
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);

        // Store1 shouldn't have it yet
        assert!(store1.get_timestamp_record(&key).unwrap().is_none());

        // Add to store1
        store1.put_timestamp_record(&key, &metadata).unwrap();

        // Now both store1 and store2 should have it (proving they're the same store instance)
        assert!(store1.get_timestamp_record(&key).unwrap().is_some());
        assert!(store2.get_timestamp_record(&key).unwrap().is_some());
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
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);

        // First store shouldn't have it yet
        assert!(stores[0].get_timestamp_record(&key).unwrap().is_none());

        // Add to first store
        stores[0].put_timestamp_record(&key, &metadata).unwrap();

        // All stores should now have it (proving they're all the same store instance)
        for store in &stores {
            assert!(store.get_timestamp_record(&key).unwrap().is_some());
        }
    }
}
