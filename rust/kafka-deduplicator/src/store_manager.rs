use anyhow::{Context, Result};
use dashmap::DashMap;
use futures::stream::{self, StreamExt};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};
use thiserror::Error;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

/// Error type for store lookup operations
#[derive(Debug, Error)]
pub enum StoreError {
    /// Store not found - partition may have been revoked during rebalance
    #[error("No store registered for partition {topic}:{partition}")]
    NotFound { topic: String, partition: i32 },

    /// Other store operation error
    #[error("Store operation failed: {0}")]
    Other(#[from] anyhow::Error),
}

use chrono::Utc;

use crate::checkpoint::metadata::CheckpointMetadata;
use crate::kafka::batch_consumer::OnCommit;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::types::Partition;
use crate::metrics::MetricsHelper;
use crate::metrics_const::{
    ACTIVE_STORE_COUNT, CLEANUP_BYTES_FREED_HISTOGRAM, CLEANUP_DURATION_HISTOGRAM,
    CLEANUP_OPERATIONS_COUNTER, REBALANCE_DIRECTORY_CLEANUP_DURATION_HISTOGRAM,
    STORE_CREATION_DURATION_MS, STORE_CREATION_EVENTS,
};
use crate::rebalance_tracker::RebalanceTracker;
use crate::rocksdb::metrics_consts::ROCKSDB_OLDEST_DATA_AGE_SECONDS_GAUGE;
use crate::store::{DeduplicationStore, DeduplicationStoreConfig};
use crate::utils::format_store_path;

/// Information about folder sizes on disk
#[derive(Debug, Clone)]
struct FolderInfo {
    name: String,
    size_bytes: u64,
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

        // Format folder info as compact list with sizes
        let folders: Vec<String> = self
            .folder_info
            .iter()
            .map(|fi| format!("{}:{:.2}MB", fi.name, fi.size_mb()))
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

    /// Coordinator for rebalance state (single source of truth)
    rebalance_tracker: Arc<RebalanceTracker>,
}

impl StoreManager {
    /// Create a new store manager with the given configuration and rebalance coordinator.
    ///
    /// The coordinator is used to check rebalance state during cleanup operations.
    pub fn new(
        store_config: DeduplicationStoreConfig,
        rebalance_tracker: Arc<RebalanceTracker>,
    ) -> Self {
        let metrics = MetricsHelper::new();

        Self {
            stores: DashMap::new(),
            store_config,
            metrics,
            cleanup_running: AtomicBool::new(false),
            rebalance_tracker,
        }
    }

    /// Get a reference to the rebalance coordinator.
    pub fn rebalance_tracker(&self) -> &Arc<RebalanceTracker> {
        &self.rebalance_tracker
    }

    /// Get an existing store for a partition, if it exists
    pub fn get(&self, topic: &str, partition: i32) -> Option<DeduplicationStore> {
        let partition_key = Partition::new(topic.to_string(), partition);
        self.stores.get(&partition_key).map(|entry| entry.clone())
    }

    /// Get an existing store for a partition during message processing.
    ///
    /// Returns `StoreError::NotFound` if the store doesn't exist. This is expected
    /// during rebalances due to rdkafka message buffering - the partition worker may
    /// still have buffered messages after the store is unregistered.
    ///
    /// The caller should handle `StoreError::NotFound` gracefully by:
    /// - Logging at warn level (expected during rebalance)
    /// - Recording metrics with topic/partition tags
    /// - Dropping the messages
    ///
    /// Use this method in the batch processor instead of `get_or_create` to avoid
    /// accidentally creating stores for revoked partitions.
    pub fn get_store(&self, topic: &str, partition: i32) -> Result<DeduplicationStore, StoreError> {
        let partition_key = Partition::new(topic.to_string(), partition);

        self.stores
            .get(&partition_key)
            .map(|entry| entry.clone())
            .ok_or_else(|| StoreError::NotFound {
                topic: topic.to_string(),
                partition,
            })
    }

    /// Get or create a deduplication store for a specific partition
    ///
    /// This method handles concurrent access safely:
    /// - If the store exists, it returns it immediately
    /// - If the store doesn't exist, it creates it atomically
    /// - If multiple workers try to create the same store, only one succeeds
    ///
    /// Use `get_or_create_for_rebalance` during rebalancing to pre-create stores.
    /// Use this method during message processing - it will warn if a store needs to be created
    /// (indicating pre-creation didn't complete in time).
    pub async fn get_or_create(&self, topic: &str, partition: i32) -> Result<DeduplicationStore> {
        self.get_or_create_internal(topic, partition, false).await
    }

    /// Get or create a deduplication store during rebalancing (pre-creation)
    ///
    /// This should be called during `async_setup_assigned_partitions` to pre-create stores
    /// before messages start flowing. Unlike `get_or_create`, this won't emit a warning
    /// when creating a new store.
    pub async fn get_or_create_for_rebalance(
        &self,
        topic: &str,
        partition: i32,
    ) -> Result<DeduplicationStore> {
        self.get_or_create_internal(topic, partition, true).await
    }

    /// Internal implementation of get_or_create with rebalance context
    async fn get_or_create_internal(
        &self,
        topic: &str,
        partition: i32,
        is_rebalance: bool,
    ) -> Result<DeduplicationStore> {
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
        let creation_start = std::time::Instant::now();
        let result = self
            .stores
            .entry(partition_key.clone())
            .or_try_insert_with(|| {
                // Generate store path inside the closure so only the creating thread generates it
                let store_path = self.build_store_path(topic, partition);
                // Ensure parent directory exists
                // Note: This is inside the closure so only the creating thread does this
                self.ensure_directory_exists(&store_path)?;

                // Warn if store is being created during message processing (not during rebalance)
                // This indicates pre-creation didn't complete in time
                if !is_rebalance {
                    warn!(
                        topic = topic,
                        partition = partition,
                        path = %store_path,
                        "Creating store during message processing - pre-creation did not complete in time"
                    );
                } else {
                    info!(
                        topic = topic,
                        partition = partition,
                        path = store_path,
                        "Pre-creating deduplication store during rebalance"
                    );
                }

                let mut partition_config = self.store_config.clone();
                partition_config.path = PathBuf::from(&store_path);

                DeduplicationStore::new(partition_config, topic.to_string(), partition)
                    .with_context(|| {
                        format!(
                            "Failed to create deduplication store for {topic}:{partition} at path {store_path}",
                        )
                    })
            });

        let creation_duration = creation_start.elapsed();
        match result {
            Ok(entry) => {
                metrics::histogram!(STORE_CREATION_DURATION_MS)
                    .record(creation_duration.as_millis() as f64);
                metrics::counter!(STORE_CREATION_EVENTS, "outcome" => "success").increment(1);
                let store = entry.clone();
                // Drop the entry reference before accessing stores.len() to avoid deadlock
                drop(entry);
                let store_count = self.stores.len();
                metrics::gauge!(ACTIVE_STORE_COUNT).set(store_count as f64);

                // Warn on slow store creation (> 5 seconds indicates potential issues)
                if creation_duration.as_secs() > 5 {
                    warn!(
                        topic = topic,
                        partition = partition,
                        duration_ms = creation_duration.as_millis(),
                        active_stores = store_count,
                        "Slow deduplication store creation"
                    );
                } else {
                    info!(
                        topic = topic,
                        partition = partition,
                        duration_ms = creation_duration.as_millis(),
                        active_stores = store_count,
                        "Successfully created deduplication store"
                    );
                }
                Ok(store)
            }
            Err(e) => {
                // This could happen if:
                // 1. Another worker created the store between our check and creation
                // 2. RocksDB failed to open/create the database

                // Check if another worker succeeded
                if let Some(store) = self.stores.get(&partition_key) {
                    warn!(
                        topic = topic,
                        partition = partition,
                        "Store was created by another worker, using existing store"
                    );
                    Ok(store.clone())
                } else {
                    // Real failure - no one succeeded in creating the store
                    metrics::counter!(STORE_CREATION_EVENTS, "outcome" => "failure").increment(1);

                    error!(
                        topic = topic,
                        partition = partition,
                        duration_ms = creation_duration.as_millis(),
                        error = ?e,
                        "Failed to create deduplication store"
                    );

                    Err(e)
                }
            }
        }
    }

    /// Remove a store from management and clean up its files.
    ///
    /// This is a convenience method that calls `unregister_store()` followed by
    /// `cleanup_store_files()`. Use this for simple cleanup outside rebalance scenarios.
    ///
    /// For rebalance scenarios, prefer the two-step process:
    /// 1. Call `unregister_store()` BEFORE shutting down workers (prevents new store creation)
    /// 2. Call `cleanup_store_files()` AFTER workers are fully stopped (safe file deletion)
    ///
    /// See `test_rebalance_removes_stores_before_workers_shutdown` for rationale.
    pub fn remove(&self, topic: &str, partition: i32) -> Result<()> {
        self.unregister_store(topic, partition);
        self.cleanup_store_files(topic, partition)
    }

    // Internally register a restored set of checkpoint files at the given store path
    // and topic/partition coordinates
    pub fn restore_imported_store(&self, topic: &str, partition: i32, path: &Path) -> Result<()> {
        let store_config = DeduplicationStoreConfig {
            path: path.to_path_buf(),
            max_capacity: self.store_config.max_capacity,
            rocksdb: self.store_config.rocksdb.clone(),
        };
        let restored = DeduplicationStore::new(store_config, topic.to_string(), partition)
            .with_context(|| {
                format!(
                    "Failed to restore imported checkpoint for {topic}:{partition} at path {}",
                    path.display(),
                )
            })?;

        // Don't fail here but do report this it's evidence of a race condition
        if let Some(existing_store) = self
            .stores
            .insert(Partition::new(topic.to_string(), partition), restored)
        {
            metrics::counter!(
                STORE_CREATION_EVENTS,
                "outcome" => "duplicate_on_restore",
            )
            .increment(1);
            error!(
                existing_store_path =% existing_store.get_db_path().display(),
                restored_store_path =% path.display(),
                topic = topic,
                partition = partition,
                "Unexpected duplicate store found when registering imported checkpoint"
            );
        }

        Ok(())
    }

    /// Check if a partition has fresh local data and return its metadata if so.
    ///
    /// Reads `metadata.json` from the partition's store directory and validates that its
    /// `updated_at` timestamp is within `max_staleness` of now. Returns `Some(metadata)` if
    /// the local store is fresh, `None` if stale, missing, or corrupt.
    ///
    /// The caller is responsible for opening RocksDB (via `restore_imported_store`) after a
    /// `Some` return — this method only validates freshness.
    pub async fn try_restore_local_store(
        &self,
        topic: &str,
        partition: i32,
        max_staleness: Duration,
    ) -> Option<CheckpointMetadata> {
        let store_path = format_store_path(&self.store_config.path, topic, partition);

        let metadata = match CheckpointMetadata::load_from_dir(&store_path).await {
            Ok(m) => m,
            Err(_) => return None, // missing or corrupt
        };

        let age = (Utc::now() - metadata.updated_at)
            .to_std()
            .unwrap_or(Duration::MAX);

        if age > max_staleness {
            return None; // stale
        }

        Some(metadata)
    }

    /// Update metadata.json for a partition after a successful Kafka offset commit.
    ///
    /// Loads existing metadata (or creates a new skeleton if missing), updates the consumer
    /// and producer offsets, and writes it back. Failures are non-fatal: if the store
    /// directory doesn't exist yet or the write fails, a warning is logged and processing
    /// continues normally.
    pub async fn update_metadata_for_partition(
        &self,
        topic: &str,
        partition: i32,
        consumer_offset: i64,
        producer_offset: i64,
    ) {
        let store_path = format_store_path(&self.store_config.path, topic, partition);
        if !store_path.exists() {
            return;
        }

        let mut metadata = match CheckpointMetadata::load_from_dir(&store_path).await {
            Ok(m) => m,
            Err(_) => {
                // No existing metadata.json — create a skeleton for local tracking only.
                // sequence=0 and empty files list are fine: this metadata is only used for
                // local recovery (offsets + freshness), never for S3 restoration.
                CheckpointMetadata::new(
                    topic.to_string(),
                    partition,
                    Utc::now(),
                    0,
                    consumer_offset,
                    producer_offset,
                )
            }
        };

        metadata.consumer_offset = consumer_offset;
        metadata.producer_offset = producer_offset;

        if let Err(e) = metadata.write_to_dir(&store_path).await {
            warn!(
                topic = topic,
                partition = partition,
                error = %e,
                "Failed to update metadata.json after commit (non-fatal)"
            );
        }
    }

    /// Unregister a store from the DashMap without deleting files (Step 1 of two-step cleanup).
    ///
    /// Call this BEFORE shutting down partition workers during rebalance. This prevents
    /// workers from creating new stores via `get_or_create()` during their shutdown.
    ///
    /// After workers are fully stopped, call `cleanup_store_files()` to delete the files.
    ///
    /// The two-step process prevents a race condition where:
    /// 1. Worker is processing during shutdown
    /// 2. Worker calls `get_or_create()` which creates a new store
    /// 3. `remove()` deletes the directory
    /// 4. Worker's write fails with "No such file or directory"
    pub fn unregister_store(&self, topic: &str, partition: i32) {
        let partition_key = Partition::new(topic.to_string(), partition);

        if let Some((_, store)) = self.stores.remove(&partition_key) {
            info!(
                topic = topic,
                partition = partition,
                "Unregistering deduplication store"
            );
            // Drop the store explicitly to close RocksDB
            drop(store);
        }
    }

    /// Delete all files for a partition from disk (Step 2 of two-step cleanup).
    ///
    /// Call this AFTER workers are fully shut down to avoid race conditions where
    /// a worker tries to write to a deleted directory.
    ///
    /// Must be called after `unregister_store()` to ensure RocksDB is closed first.
    pub fn cleanup_store_files(&self, topic: &str, partition: i32) -> Result<()> {
        let partition_path = format_store_path(&self.store_config.path, topic, partition);
        let partition_dir_str = partition_path.to_string_lossy().to_string();

        if partition_path.exists() {
            match std::fs::remove_dir_all(&partition_path) {
                Ok(_) => {
                    info!(
                        topic = topic,
                        partition = partition,
                        path = partition_dir_str,
                        "Deleted partition directory"
                    );
                }
                Err(e) => {
                    warn!(
                        topic = topic,
                        partition = partition,
                        path = partition_dir_str,
                        error = %e,
                        "Failed to remove partition directory (usually harmless)"
                    );
                }
            }
        } else {
            debug!(
                topic = topic,
                partition = partition,
                path = partition_dir_str,
                "Partition directory doesn't exist"
            );
        }

        Ok(())
    }

    /// Delete partition directories not in the owned set using bounded parallelism.
    ///
    /// Called at end of rebalance cycle to clean up directories for revoked partitions.
    /// Uses scatter-gather pattern with configurable parallelism for fast cleanup
    /// before resuming consumption.
    ///
    /// This is simpler and more aggressive than the periodic orphan cleaner:
    /// - No staleness check (we know ownership is final at end of cycle)
    /// - Also catches orphans from previous runs
    pub async fn cleanup_unowned_partition_directories(
        &self,
        owned: &[Partition],
        parallelism: usize,
    ) -> Result<()> {
        let start = Instant::now();

        // Build set of owned store paths for O(1) lookup
        let owned_paths: HashSet<PathBuf> = owned
            .iter()
            .map(|p| format_store_path(&self.store_config.path, p.topic(), p.partition_number()))
            .collect();

        // Scan disk: <base>/<topic>/<partition>/ structure
        let base_path = &self.store_config.path;
        let mut unowned_paths = Vec::new();

        let mut topic_dirs = match tokio::fs::read_dir(base_path).await {
            Err(e) => {
                warn!(
                    path = %base_path.display(),
                    error = ?e,
                    "Failed to read store base directory for cleanup"
                );
                return Ok(());
            }
            Ok(rd) => rd,
        };

        while let Ok(Some(topic_entry)) = topic_dirs.next_entry().await {
            let is_dir = topic_entry
                .file_type()
                .await
                .map(|ft| ft.is_dir())
                .unwrap_or(false);
            if !is_dir {
                continue;
            }

            let topic_path = topic_entry.path();
            let mut partition_dirs = match tokio::fs::read_dir(&topic_path).await {
                Ok(rd) => rd,
                Err(_) => continue,
            };

            let mut topic_has_owned = false;
            let mut unowned_partition_paths: Vec<PathBuf> = Vec::new();
            while let Ok(Some(partition_entry)) = partition_dirs.next_entry().await {
                let is_dir = partition_entry
                    .file_type()
                    .await
                    .map(|ft| ft.is_dir())
                    .unwrap_or(false);
                if !is_dir {
                    continue;
                }

                let partition_path = partition_entry.path();
                if owned_paths.contains(&partition_path) {
                    topic_has_owned = true;
                } else {
                    unowned_partition_paths.push(partition_path);
                }
            }

            if !topic_has_owned {
                // No owned partitions remain — delete the whole topic dir in one shot
                unowned_paths.push(topic_path);
            } else {
                // Only delete unowned partitions; keep topic dir for owned children
                unowned_paths.extend(unowned_partition_paths);
            }
        }

        if unowned_paths.is_empty() {
            debug!("No unowned partition directories to clean up");
            return Ok(());
        }

        let count = unowned_paths.len();
        info!(
            count = count,
            parallelism = parallelism,
            "Cleaning up unowned partition directories"
        );

        // Delete in parallel with bounded concurrency
        let results: Vec<std::io::Result<()>> = stream::iter(unowned_paths)
            .map(|path| async move {
                let path_str = path.display().to_string();
                match tokio::fs::remove_dir_all(&path).await {
                    Ok(_) => {
                        debug!(path = %path_str, "Deleted unowned partition directory");
                        Ok(())
                    }
                    Err(e) => {
                        warn!(path = %path_str, error = ?e, "Failed to delete partition directory");
                        Err(e)
                    }
                }
            })
            .buffer_unordered(parallelism)
            .collect()
            .await;

        // Record timing
        let duration = start.elapsed();
        self.metrics
            .histogram(REBALANCE_DIRECTORY_CLEANUP_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());

        let failed = results.iter().filter(|r| r.is_err()).count();
        let succeeded = count - failed;

        if failed > 0 {
            warn!(
                succeeded = succeeded,
                failed = failed,
                duration_ms = duration.as_millis(),
                "Partition directory cleanup completed with failures (orphan cleaner will retry)"
            );
        } else {
            info!(
                deleted = succeeded,
                duration_ms = duration.as_millis(),
                "Partition directory cleanup completed"
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

    /// Get the base path where stores are created
    pub fn base_path(&self) -> &Path {
        &self.store_config.path
    }

    /// Get the store configuration
    pub fn config(&self) -> &DeduplicationStoreConfig {
        &self.store_config
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

        // Skip cleanup during rebalance to avoid deleting entries from stores
        // that are being populated with imported checkpoints
        if self.rebalance_tracker.is_rebalancing() {
            debug!("Skipping capacity cleanup - rebalance in progress");
            return Ok(0);
        }

        let start_time = Instant::now();

        // If max_capacity is 0, no cleanup needed (unlimited)
        if self.store_config.max_capacity == 0 {
            return Ok(0);
        }

        // Collect store clones first to release DashMap guards before slow operations.
        // This prevents blocking other DashMap operations during size calculation and cleanup.
        let stores: Vec<DeduplicationStore> = self
            .stores
            .iter()
            .map(|entry| entry.value().clone())
            .collect();

        // Calculate total size across all stores (no longer holding DashMap guards)
        let mut total_size = 0u64;
        for store in &stores {
            if let Ok(size) = store.get_total_size() {
                total_size += size;
            }
        }

        // Start cleanup at 80% capacity to give compaction headroom
        let cleanup_threshold = (self.store_config.max_capacity as f64 * 0.8) as u64;
        if total_size <= cleanup_threshold {
            return Ok(0); // Under threshold, no cleanup needed
        }

        // Determine capacity level for logging and cleanup aggressiveness
        let capacity_ratio = total_size as f64 / self.store_config.max_capacity as f64;
        let capacity_percent = (capacity_ratio * 100.0) as u32;

        info!(
            "Global store size {} ({}% of max capacity {}) exceeds cleanup threshold, triggering cleanup",
            total_size, capacity_percent, self.store_config.max_capacity
        );

        // We need to clean up - target 70% of max capacity to create buffer
        let target_size = (self.store_config.max_capacity as f64 * 0.7) as u64;
        let bytes_to_free = total_size.saturating_sub(target_size);

        // Calculate cleanup percentage based on how much we need to free
        // If we need to free 20% of total size, clean up 20% of time range from each store
        let raw_cleanup_percentage = bytes_to_free as f64 / total_size as f64;

        // When over 90% capacity, be more aggressive - no cap on cleanup percentage
        // Otherwise cap at 30% to avoid removing too much data at once
        let cleanup_percentage = if capacity_ratio > 0.9 {
            info!(
                "Critical capacity ({}%) - using aggressive cleanup without cap",
                capacity_percent
            );
            raw_cleanup_percentage.min(0.5) // Still cap at 50% to avoid removing everything
        } else {
            raw_cleanup_percentage.min(0.3) // Normal cap at 30%
        };

        info!(
            "Cleaning up {:.1}% of time range from each store (need to free {} bytes)",
            cleanup_percentage * 100.0,
            bytes_to_free
        );

        // Cleanup stores with the calculated percentage (no longer holding DashMap guards)
        let mut total_bytes_freed = 0u64;
        for store in &stores {
            // Check if rebalance started mid-cleanup - abort to avoid deleting
            // entries from stores being populated with imported checkpoints
            if self.rebalance_tracker.is_rebalancing() {
                info!(
                    "Aborting capacity cleanup - rebalance started. Freed {} bytes so far",
                    total_bytes_freed
                );
                return Ok(total_bytes_freed);
            }

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
    /// Cleanup triggers at 80% capacity to give background compaction time to reclaim space
    pub fn needs_cleanup(&self) -> bool {
        // Log folder sizes and assigned partitions
        self.log_folder_sizes_and_partitions();

        if self.store_config.max_capacity == 0 {
            return false;
        }

        // Collect store clones first to release DashMap guards before slow operations
        let stores: Vec<DeduplicationStore> = self
            .stores
            .iter()
            .map(|entry| entry.value().clone())
            .collect();

        let mut total_size = 0u64;
        let mut max_oldest_data_age: Option<u64> = None;
        for store in &stores {
            if let Ok(size) = store.get_total_size() {
                total_size += size;
            }
            // Emit per-partition oldest data age metric and track max
            if let Ok(Some(age)) = store.get_oldest_data_age_seconds() {
                metrics::gauge!(
                    ROCKSDB_OLDEST_DATA_AGE_SECONDS_GAUGE,
                    "topic" => store.get_topic().to_string(),
                    "partition" => store.get_partition().to_string()
                )
                .set(age as f64);
                max_oldest_data_age =
                    Some(max_oldest_data_age.map_or(age, |current| current.max(age)));
            }
        }

        // Start cleanup at 80% capacity to give compaction headroom
        let cleanup_threshold = (self.store_config.max_capacity as f64 * 0.8) as u64;

        info!(
            "Total size of all stores: {} bytes, cleanup threshold: {} bytes, max capacity: {} bytes, oldest data age: {}s",
            total_size, cleanup_threshold, self.store_config.max_capacity, max_oldest_data_age.unwrap_or(0)
        );
        total_size > cleanup_threshold
    }

    /// Start a periodic cleanup task that runs in the background
    /// Returns a handle that can be used to stop the task
    pub fn start_periodic_cleanup(
        self: Arc<Self>,
        cleanup_interval: Duration,
        orphan_min_staleness: Duration,
    ) -> CleanupTaskHandle {
        let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel();
        let manager = self;

        let handle = tokio::spawn(async move {
            let mut interval = tokio::time::interval(cleanup_interval);
            interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

            info!(
                "Started periodic cleanup task with interval of {:?}, orphan staleness {:?}",
                cleanup_interval, orphan_min_staleness
            );

            loop {
                tokio::select! {
                    _ = interval.tick() => {
                        info!("Cleanup task tick - running periodic cleanup check");

                        // First, clean up orphaned directories (unassigned partitions)
                        match manager.cleanup_orphaned_directories(orphan_min_staleness) {
                            Ok(0) => {
                                debug!("No orphaned directories found");
                            }
                            Ok(bytes_freed) => {
                                info!("Cleaned up {} bytes of orphaned directories", bytes_freed);
                            }
                            Err(e) => {
                                warn!("Failed to clean up orphaned directories: {e:#}");
                            }
                        }

                        // Then check if we need capacity-based cleanup
                        if manager.needs_cleanup() {
                            match manager.cleanup_old_entries_if_needed() {
                                Ok(0) => {
                                    debug!("Cleanup skipped (may be already running or no data to clean)");
                                }
                                Ok(bytes_freed) => {
                                    info!("Periodic cleanup freed {} bytes", bytes_freed);
                                }
                                Err(e) => {
                                    error!("Periodic cleanup failed: {e:#}");
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

    /// Build the path for a store based on topic and partition.
    /// Each partition gets a single directory: `<base>/<topic>/<partition>/`
    fn build_store_path(&self, topic: &str, partition: i32) -> String {
        format_store_path(&self.store_config.path, topic, partition)
            .to_string_lossy()
            .to_string()
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
                debug!("Created parent directory: {}", parent.display());
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

        // Get folder sizes from filesystem (<base>/<topic>/<partition>/ structure)
        let mut folder_info = Vec::new();
        let mut total_disk_usage_bytes = 0u64;

        if let Ok(topic_entries) = std::fs::read_dir(&self.store_config.path) {
            for topic_entry in topic_entries.flatten() {
                if !topic_entry.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                    continue;
                }
                let topic_name = topic_entry.file_name().to_string_lossy().to_string();

                if let Ok(partition_entries) = std::fs::read_dir(topic_entry.path()) {
                    for partition_entry in partition_entries.flatten() {
                        if !partition_entry
                            .metadata()
                            .map(|m| m.is_dir())
                            .unwrap_or(false)
                        {
                            continue;
                        }
                        let partition_name =
                            partition_entry.file_name().to_string_lossy().to_string();
                        let folder_size =
                            StoreManager::get_directory_size(&partition_entry.path()).unwrap_or(0);

                        total_disk_usage_bytes += folder_size;
                        folder_info.push(FolderInfo {
                            name: format!("{topic_name}/{partition_name}"),
                            size_bytes: folder_size,
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

    /// Get the modification time of a directory.
    fn get_dir_mtime(dir: &Path) -> Option<SystemTime> {
        std::fs::metadata(dir).ok().and_then(|m| m.modified().ok())
    }

    /// Clean up unowned partition directories that are stale.
    ///
    /// With single-directory-per-partition layout (`<base>/<topic>/<partition>/`),
    /// this finds partition directories that don't belong to any active store
    /// and whose directory mtime exceeds the staleness threshold.
    ///
    /// Safety checks:
    /// 1. Skip if stores map is empty (startup race)
    /// 2. Skip if rebalancing is in progress
    /// 3. Only delete directories older than orphan_min_staleness
    pub fn cleanup_orphaned_directories(&self, orphan_min_staleness: Duration) -> Result<u64> {
        if self.stores.is_empty() {
            debug!("Skipping orphan cleanup - no stores registered");
            return Ok(0);
        }

        if self.rebalance_tracker.is_rebalancing() {
            debug!("Skipping orphan cleanup - rebalance in progress");
            return Ok(0);
        }

        // Build set of active store paths
        let active_paths: HashSet<PathBuf> = self
            .stores
            .iter()
            .map(|entry| entry.value().get_db_path().clone())
            .collect();

        let mut total_freed = 0u64;

        // Scan <base>/<topic>/<partition>/ structure
        let Ok(topic_entries) = std::fs::read_dir(&self.store_config.path) else {
            return Ok(0);
        };

        for topic_entry in topic_entries.flatten() {
            if !topic_entry.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                continue;
            }

            if self.rebalance_tracker.is_rebalancing() {
                info!(
                    "Aborting orphan cleanup - rebalance started. Freed {} bytes so far",
                    total_freed
                );
                return Ok(total_freed);
            }

            let topic_path = topic_entry.path();
            let Ok(partition_entries) = std::fs::read_dir(&topic_path) else {
                continue;
            };

            for partition_entry in partition_entries.flatten() {
                if !partition_entry
                    .metadata()
                    .map(|m| m.is_dir())
                    .unwrap_or(false)
                {
                    continue;
                }

                let partition_path = partition_entry.path();

                // Skip active stores
                if active_paths.contains(&partition_path) {
                    continue;
                }

                // Check staleness via directory mtime
                let is_stale = Self::get_dir_mtime(&partition_path)
                    .map(|mtime| mtime.elapsed().unwrap_or(Duration::ZERO) >= orphan_min_staleness)
                    .unwrap_or(true);

                if !is_stale {
                    debug!(
                        path = %partition_path.display(),
                        "Skipping orphan candidate - directory too recent"
                    );
                    continue;
                }

                let dir_size = Self::get_directory_size(&partition_path).unwrap_or(0);

                match std::fs::remove_dir_all(&partition_path) {
                    Ok(_) => {
                        info!(
                            path = %partition_path.display(),
                            size_mb = dir_size as f64 / (1024.0 * 1024.0),
                            "Removed orphaned partition directory"
                        );
                        metrics::counter!(
                            CLEANUP_OPERATIONS_COUNTER,
                            "partition_status" => "unassigned"
                        )
                        .increment(1);
                        total_freed += dir_size;
                    }
                    Err(e) => {
                        warn!(
                            "Failed to remove orphaned partition directory {}: {}",
                            partition_path.display(),
                            e
                        );
                    }
                }
            }

            // Clean up empty topic directories
            if std::fs::read_dir(&topic_path)
                .map(|mut rd| rd.next().is_none())
                .unwrap_or(false)
            {
                let _ = std::fs::remove_dir(&topic_path);
            }
        }

        if total_freed > 0 {
            info!(
                "Cleaned up {:.2} MB of orphaned partition directories",
                total_freed as f64 / (1024.0 * 1024.0)
            );
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
            Ok(Err(e)) => warn!("Cleanup task failed: {e:#}"),
            Err(_) => warn!("Cleanup task shutdown timed out"),
        }
    }
}

/// Bridges `OnCommit` to `StoreManager::update_metadata_for_partition`.
///
/// Constructed by the pipeline builder so `BatchConsumer` stays decoupled from
/// store internals. Each committed partition triggers a metadata update;
/// failures are non-fatal and logged inside `update_metadata_for_partition`.
pub struct MetadataCommitCallback {
    store_manager: Arc<StoreManager>,
    offset_tracker: Arc<OffsetTracker>,
}

impl MetadataCommitCallback {
    pub fn new(store_manager: Arc<StoreManager>, offset_tracker: Arc<OffsetTracker>) -> Self {
        Self {
            store_manager,
            offset_tracker,
        }
    }
}

#[async_trait::async_trait]
impl OnCommit for MetadataCommitCallback {
    async fn on_commit(&self, offsets: &HashMap<Partition, i64>) {
        for (partition, consumer_offset) in offsets {
            let producer_offset = self
                .offset_tracker
                .get_producer_offset(partition)
                .unwrap_or(0);
            self.store_manager
                .update_metadata_for_partition(
                    partition.topic(),
                    partition.partition_number(),
                    *consumer_offset,
                    producer_offset,
                )
                .await;
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::rocksdb::store::RocksDbConfig;
    use crate::store::{TimestampKey, TimestampMetadata};
    use crate::test_utils::create_test_tracker;

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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

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
            rocksdb: RocksDbConfig::default(),
        };
        let zero_manager = Arc::new(StoreManager::new(zero_config, create_test_tracker()));
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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Start periodic cleanup with short interval for testing
        let cleanup_handle = manager.clone().start_periodic_cleanup(
            Duration::from_millis(100), // Very short interval for testing
            Duration::from_secs(0),     // No staleness for testing
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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Start cleanup task
        let cleanup_handle = manager.clone().start_periodic_cleanup(
            Duration::from_secs(60), // Long interval
            Duration::from_secs(0),  // No staleness for testing
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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

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
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

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

    #[tokio::test]
    async fn test_get_or_create_for_rebalance() {
        // Test that get_or_create_for_rebalance works the same as get_or_create
        // but is intended for pre-creation during rebalancing
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // Pre-create during rebalance
        let store1 = manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        // Subsequent call (during message processing) should return the same store
        let store2 = manager.get_or_create("test-topic", 0).await.unwrap();

        // Verify they share state
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);

        store1.put_timestamp_record(&key, &metadata).unwrap();
        assert!(store2.get_timestamp_record(&key).unwrap().is_some());
    }

    #[tokio::test]
    async fn test_store_precreation_before_message_processing() {
        // Simulates the ideal flow: store is pre-created during rebalance,
        // then used during message processing without creating a new one
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // Step 1: Pre-create during rebalance (async_setup_assigned_partitions)
        let _store = manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // Step 2: Message processing calls get_or_create
        // This should return the existing store (no new creation)
        let store = manager.get_or_create("test-topic", 0).await.unwrap();

        // Still only 1 store
        assert_eq!(manager.get_active_store_count(), 1);

        // Verify it's the same store by checking it works
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata).unwrap();
        assert!(store.get_timestamp_record(&key).unwrap().is_some());
    }

    #[tokio::test]
    async fn test_rapid_revoke_assign_store_recreation() {
        // Simulates rapid revoke -> assign where:
        // 1. Store exists
        // 2. Revoke removes it from map
        // 3. Assign pre-creates a new one
        // 4. Messages can use the new store
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // Initial assignment - pre-create store
        let store1 = manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // Add some data
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store1.put_timestamp_record(&key, &metadata).unwrap();

        // Revoke - unregister store (but don't delete files yet)
        manager.unregister_store("test-topic", 0);
        assert_eq!(manager.get_active_store_count(), 0);

        // Drop store1 to release the RocksDB lock before re-opening the same path.
        // With flat partition paths, store1 and store2 share the same directory, so
        // the lock must be released before the re-assign can open a new instance.
        drop(store1);

        // Rapid re-assign - pre-create new store for the same partition path
        let store2 = manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // The new store reuses the same partition directory and retains previously written data
        let event2 = RawEvent {
            event: "test_event_2".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user_2".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };
        let key2 = TimestampKey::from(&event2);
        let metadata2 = TimestampMetadata::new(&event2);
        store2.put_timestamp_record(&key2, &metadata2).unwrap();
        assert!(store2.get_timestamp_record(&key2).unwrap().is_some());

        // Message processing should use the new store
        let store3 = manager.get_or_create("test-topic", 0).await.unwrap();
        assert!(store3.get_timestamp_record(&key2).unwrap().is_some());
    }

    #[tokio::test]
    async fn test_message_processing_creates_store_if_precreation_missed() {
        // Simulates the case where messages arrive before pre-creation completes
        // The processor's get_or_create should still work (and emit a warning)
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // No pre-creation - messages arrive first
        // This would emit a warning in production
        let store = manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // Store should work normally
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);
        store.put_timestamp_record(&key, &metadata).unwrap();
        assert!(store.get_timestamp_record(&key).unwrap().is_some());

        // Late pre-creation should just return the existing store
        let store2 = manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();
        assert_eq!(manager.get_active_store_count(), 1);
        assert!(store2.get_timestamp_record(&key).unwrap().is_some());
    }

    #[tokio::test]
    async fn test_concurrent_rebalance_and_message_processing() {
        // Simulates concurrent pre-creation and message processing
        // Only one store should be created
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Spawn concurrent tasks: some for rebalance, some for message processing
        let mut handles = vec![];

        for i in 0..5 {
            let manager_clone = manager.clone();
            let handle = if i % 2 == 0 {
                // Rebalance pre-creation
                tokio::spawn(async move {
                    manager_clone
                        .get_or_create_for_rebalance("test-topic", 0)
                        .await
                })
            } else {
                // Message processing
                tokio::spawn(async move { manager_clone.get_or_create("test-topic", 0).await })
            };
            handles.push(handle);
        }

        // All should succeed
        let mut stores = vec![];
        for handle in handles {
            let store = handle.await.unwrap().unwrap();
            stores.push(store);
        }

        // Only one store should exist
        assert_eq!(manager.get_active_store_count(), 1);

        // All stores should be the same instance
        let event = RawEvent {
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("test_user".to_string())),
            token: Some("test_token".to_string()),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);

        stores[0].put_timestamp_record(&key, &metadata).unwrap();
        for store in &stores {
            assert!(store.get_timestamp_record(&key).unwrap().is_some());
        }
    }

    #[tokio::test]
    async fn test_cleanup_orphaned_directories_skips_during_rebalance() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store for partition 0
        manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // Create an "orphaned" directory manually (not in stores map)
        // Must have timestamp subdir structure: topic_partition/timestamp/files
        let orphan_dir = temp_dir.path().join("other-topic_1");
        let timestamp_subdir = orphan_dir.join("1234567890");
        std::fs::create_dir_all(&timestamp_subdir).unwrap();
        std::fs::write(timestamp_subdir.join("dummy.txt"), b"test data").unwrap();
        assert!(timestamp_subdir.exists());

        // When NOT rebalancing, cleanup should remove the orphan timestamp dir
        assert!(!manager.rebalance_tracker().is_rebalancing());
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert!(freed > 0);
        assert!(
            !timestamp_subdir.exists(),
            "Orphan timestamp dir should be removed when not rebalancing"
        );

        // Recreate the orphan directory structure
        std::fs::create_dir_all(&timestamp_subdir).unwrap();
        std::fs::write(timestamp_subdir.join("dummy.txt"), b"test data").unwrap();
        assert!(timestamp_subdir.exists());

        // Start rebalancing via coordinator
        manager.rebalance_tracker().start_rebalancing();
        assert!(manager.rebalance_tracker().is_rebalancing());

        // During rebalance, cleanup should skip and not remove the orphan
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert_eq!(freed, 0);
        assert!(
            timestamp_subdir.exists(),
            "Orphan should NOT be removed during rebalance"
        );

        // Finish rebalancing via coordinator
        manager.rebalance_tracker().finish_rebalancing();
        assert!(!manager.rebalance_tracker().is_rebalancing());

        // Now cleanup should remove the orphan again
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert!(freed > 0);
        assert!(
            !timestamp_subdir.exists(),
            "Orphan timestamp dir should be removed after rebalance ends"
        );
    }

    #[tokio::test]
    async fn test_capacity_cleanup_skips_during_rebalance() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 100, // Very small to trigger cleanup
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store and add data
        let store = manager.get_or_create("test-topic", 0).await.unwrap();
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
            let key = TimestampKey::from(&event);
            let metadata = TimestampMetadata::new(&event);
            store.put_timestamp_record(&key, &metadata).unwrap();
        }

        // Start rebalancing via coordinator
        manager.rebalance_tracker().start_rebalancing();
        assert!(manager.rebalance_tracker().is_rebalancing());

        // During rebalance, capacity cleanup should skip
        let freed = manager.cleanup_old_entries_if_needed().unwrap();
        assert_eq!(freed, 0, "Should skip cleanup during rebalance");

        // Finish rebalancing via coordinator
        manager.rebalance_tracker().finish_rebalancing();
        assert!(!manager.rebalance_tracker().is_rebalancing());

        // Now cleanup should run (may or may not free bytes depending on actual size)
        let result = manager.cleanup_old_entries_if_needed();
        assert!(result.is_ok(), "Cleanup should run after rebalance ends");
    }

    #[tokio::test]
    async fn test_orphan_cleanup_recent_wal_prevents_deletion() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store for partition 0 (so stores map is not empty)
        manager.get_or_create("test-topic", 0).await.unwrap();

        // Create an "orphaned" directory with a recent WAL file
        let orphan_dir = temp_dir.path().join("other-topic_1");
        let timestamp_subdir = orphan_dir.join("1234567890");
        std::fs::create_dir_all(&timestamp_subdir).unwrap();
        std::fs::write(timestamp_subdir.join("000001.log"), b"wal data").unwrap();
        std::fs::write(timestamp_subdir.join("dummy.sst"), b"test data").unwrap();
        assert!(timestamp_subdir.exists());

        // Cleanup should NOT remove the timestamp dir because WAL file is too recent (staleness=15min)
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(900))
            .unwrap();
        assert_eq!(freed, 0, "Should not delete directory with recent WAL");
        assert!(
            timestamp_subdir.exists(),
            "Timestamp dir with recent WAL should NOT be removed"
        );
    }

    #[tokio::test]
    async fn test_orphan_cleanup_old_wal_allows_deletion() {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store for partition 0 (so stores map is not empty)
        manager.get_or_create("test-topic", 0).await.unwrap();

        // Create an "orphaned" directory with a WAL file (no LOCK)
        let orphan_dir = temp_dir.path().join("other-topic_1");
        let timestamp_subdir = orphan_dir.join("1234567890");
        std::fs::create_dir_all(&timestamp_subdir).unwrap();
        std::fs::write(timestamp_subdir.join("000001.log"), b"wal data").unwrap();
        std::fs::write(timestamp_subdir.join("dummy.sst"), b"test data").unwrap();
        assert!(timestamp_subdir.exists());

        // With zero staleness, cleanup should remove the timestamp dir
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert!(freed > 0, "Should delete directory with stale WAL");
        assert!(
            !timestamp_subdir.exists(),
            "Timestamp dir with stale WAL should be removed"
        );
    }

    #[tokio::test]
    async fn test_orphan_safety_checks_combined() {
        // Verify all safety checks work together
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store for partition 0
        manager.get_or_create("test-topic", 0).await.unwrap();

        // Test 1: Directory in stores map should NOT be deleted
        // (the existing test-topic_0 directory)
        let active_dir = temp_dir.path().join("test-topic").join("0");
        assert!(active_dir.exists(), "Active store directory should exist");
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert_eq!(freed, 0, "No orphans should be found initially");
        assert!(
            active_dir.exists(),
            "Active store directory should NOT be deleted"
        );

        // Test 2: True orphan (no LOCK, no recent WAL, not in stores) should be deleted
        let orphan_dir = temp_dir.path().join("orphan-topic_99");
        let timestamp_subdir = orphan_dir.join("9999999999");
        std::fs::create_dir_all(&timestamp_subdir).unwrap();
        std::fs::write(timestamp_subdir.join("dummy.sst"), b"test data").unwrap();

        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();
        assert!(freed > 0, "True orphan should be deleted");
        assert!(
            !timestamp_subdir.exists(),
            "Orphan timestamp directory should be removed"
        );
    }

    #[tokio::test]
    async fn test_get_store_returns_not_found_when_not_exists() {
        // Test that get_store() returns StoreError::NotFound when no store exists
        // This is the expected behavior during message processing for revoked partitions
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // get_store() should return StoreError::NotFound when store doesn't exist
        let result = manager.get_store("test-topic", 0);
        match result {
            Err(StoreError::NotFound { topic, partition }) => {
                assert_eq!(topic, "test-topic");
                assert_eq!(partition, 0);
            }
            Ok(_) => panic!("Expected StoreError::NotFound, got Ok"),
            Err(e) => panic!("Expected StoreError::NotFound, got {:?}", e),
        }
    }

    #[tokio::test]
    async fn test_get_store_returns_store_when_exists() {
        // Test that get_store() returns the store when it exists
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // Pre-create store (as would happen during rebalance)
        manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        // get_store() should now return the store
        let result = manager.get_store("test-topic", 0);
        assert!(
            result.is_ok(),
            "get_store() should return Ok when store exists"
        );
    }

    #[tokio::test]
    async fn test_get_store_after_unregister_returns_not_found() {
        // Test that get_store() returns StoreError::NotFound after store is unregistered
        // This simulates the revocation scenario where buffered messages arrive after revoke
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = StoreManager::new(config, create_test_tracker());

        // Create store
        manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        // get_store() should work
        assert!(manager.get_store("test-topic", 0).is_ok());

        // Unregister store (as would happen during revocation)
        manager.unregister_store("test-topic", 0);

        // get_store() should now return StoreError::NotFound
        let result = manager.get_store("test-topic", 0);
        match result {
            Err(StoreError::NotFound { topic, partition }) => {
                assert_eq!(topic, "test-topic");
                assert_eq!(partition, 0);
            }
            Ok(_) => panic!("Expected StoreError::NotFound after unregister, got Ok"),
            Err(e) => panic!(
                "Expected StoreError::NotFound after unregister, got {:?}",
                e
            ),
        }
    }

    #[tokio::test]
    async fn test_orphan_cleanup_never_deletes_active_store_path() {
        // Defense-in-depth test: even if collect_orphan_candidates somehow includes
        // the active store path, is_safe_to_delete_timestamp_dir should prevent deletion.
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create a store for partition 0
        manager.get_or_create("test-topic", 0).await.unwrap();
        assert_eq!(manager.get_active_store_count(), 1);

        // Get the active store's path
        let active_store = manager.get("test-topic", 0).unwrap();
        let active_path = active_store.get_db_path().clone();

        // Verify active store exists
        assert!(active_path.exists(), "Active store path should exist");

        // Run orphan cleanup multiple times - should never touch active store
        for _ in 0..3 {
            let freed = manager
                .cleanup_orphaned_directories(Duration::from_secs(0))
                .unwrap();
            assert_eq!(
                freed, 0,
                "Should not free anything - only active store exists"
            );
            assert!(
                active_path.exists(),
                "Active store path should NEVER be deleted"
            );
        }

        assert_eq!(
            manager.get_active_store_count(),
            1,
            "Store should still be registered"
        );
    }

    #[tokio::test]
    async fn test_orphan_cleanup_mixed_assigned_and_unassigned_partitions() {
        // Test that orphan cleanup correctly handles a mix of:
        // - Assigned partitions (keep active partition dir intact)
        // - Unassigned partitions (delete entire partition dir)
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create stores for partitions 0 and 1 (assigned)
        manager.get_or_create("test-topic", 0).await.unwrap();
        manager.get_or_create("test-topic", 1).await.unwrap();
        assert_eq!(manager.get_active_store_count(), 2);

        let active_store_0 = manager.get("test-topic", 0).unwrap();
        let active_path_0 = active_store_0.get_db_path().clone();
        let active_store_1 = manager.get("test-topic", 1).unwrap();
        let active_path_1 = active_store_1.get_db_path().clone();

        // Create an unassigned partition (partition 99) with some data files
        let unassigned_dir = temp_dir.path().join("test-topic").join("99");
        std::fs::create_dir_all(&unassigned_dir).unwrap();
        std::fs::write(unassigned_dir.join("dummy1.sst"), b"orphan1").unwrap();
        std::fs::write(unassigned_dir.join("dummy2.sst"), b"orphan2").unwrap();

        // Verify setup
        assert!(unassigned_dir.exists());

        // Run orphan cleanup
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();

        assert!(
            freed > 0,
            "Should have freed bytes from the unassigned partition"
        );

        // Verify: active stores for assigned partitions are untouched
        assert!(
            active_path_0.exists(),
            "Active store for partition 0 should exist"
        );
        assert!(
            active_path_1.exists(),
            "Active store for partition 1 should exist"
        );

        // Verify: the unassigned partition directory is fully cleaned
        assert!(
            !unassigned_dir.exists(),
            "Unassigned partition dir should be deleted"
        );

        // Stores still registered
        assert_eq!(manager.get_active_store_count(), 2);
    }

    #[tokio::test]
    async fn test_revoke_then_orphan_cleanup_flow() {
        // Test the full flow: assign → create store → revoke → orphan cleanup cleans files
        // This verifies that revoked partition files ARE eventually cleaned by the orphan cleaner.
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1024 * 1024 * 1024,
            rocksdb: RocksDbConfig::default(),
        };

        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));

        // Create stores for partitions 0 and 1
        // We need at least one store to remain so the cleanup doesn't skip due to empty stores
        manager.get_or_create("test-topic", 0).await.unwrap();
        manager.get_or_create("test-topic", 1).await.unwrap();
        assert_eq!(manager.get_active_store_count(), 2);

        let store_0 = manager.get("test-topic", 0).unwrap();
        let store_path_0 = store_0.get_db_path().clone();
        let partition_dir_0 = temp_dir.path().join("test-topic").join("0");

        // Verify store 0 exists on disk
        assert!(store_path_0.exists(), "Store 0 path should exist");
        assert!(partition_dir_0.exists(), "Partition 0 dir should exist");

        // Drop the store reference before unregistering
        drop(store_0);

        // Simulate revoke of partition 0: unregister store (but don't delete files)
        manager.unregister_store("test-topic", 0);
        assert_eq!(
            manager.get_active_store_count(),
            1,
            "Only partition 1 store should remain"
        );

        // Files for partition 0 should still exist after unregister
        assert!(
            partition_dir_0.exists(),
            "Partition 0 dir should still exist after unregister"
        );
        assert!(
            store_path_0.exists(),
            "Store 0 path should still exist after unregister"
        );

        // Now run orphan cleanup - should clean partition 0 files since it's no longer assigned
        // (Partition 1 is still assigned so cleanup won't skip due to empty stores)
        let freed = manager
            .cleanup_orphaned_directories(Duration::from_secs(0))
            .unwrap();

        assert!(freed > 0, "Should have freed bytes from orphaned files");
        assert!(
            !store_path_0.exists(),
            "Store 0 path should be cleaned by orphan cleaner"
        );

        // Partition 1 store should still exist
        let store_1 = manager.get("test-topic", 1).unwrap();
        assert!(
            store_1.get_db_path().exists(),
            "Store 1 should still exist (still assigned)"
        );
    }

    mod try_restore_local_store_tests {
        use super::*;
        use crate::checkpoint::config::DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS;
        use crate::checkpoint::metadata::CheckpointMetadata;
        use crate::test_utils::create_test_store_manager;
        use crate::utils::format_store_path;
        use chrono::Utc;

        #[tokio::test]
        async fn test_returns_metadata_when_fresh() {
            let temp_dir = TempDir::new().unwrap();
            let manager = create_test_store_manager(temp_dir.path().to_path_buf());
            let store_path = format_store_path(temp_dir.path(), "test-topic", 0);
            tokio::fs::create_dir_all(&store_path).await.unwrap();

            let mut metadata =
                CheckpointMetadata::new("test-topic".to_string(), 0, Utc::now(), 1, 100, 50);
            metadata.write_to_dir(&store_path).await.unwrap();

            let result = manager
                .try_restore_local_store(
                    "test-topic",
                    0,
                    Duration::from_secs(DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS),
                )
                .await;

            assert!(result.is_some(), "Should return metadata for fresh store");
            let loaded = result.unwrap();
            assert_eq!(loaded.consumer_offset, 100);
            assert_eq!(loaded.producer_offset, 50);
        }

        #[tokio::test]
        async fn test_returns_none_when_missing() {
            let temp_dir = TempDir::new().unwrap();
            let manager = create_test_store_manager(temp_dir.path().to_path_buf());

            // No metadata.json written — directory doesn't even exist
            let result = manager
                .try_restore_local_store(
                    "test-topic",
                    0,
                    Duration::from_secs(DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS),
                )
                .await;

            assert!(
                result.is_none(),
                "Should return None when metadata is missing"
            );
        }

        #[tokio::test]
        async fn test_returns_none_when_stale() {
            let temp_dir = TempDir::new().unwrap();
            let manager = create_test_store_manager(temp_dir.path().to_path_buf());
            let store_path = format_store_path(temp_dir.path(), "test-topic", 0);
            tokio::fs::create_dir_all(&store_path).await.unwrap();

            // Write metadata with an old updated_at by setting attempt_timestamp far in the past
            // then manually writing JSON with an old updated_at
            let old_timestamp = Utc::now() - chrono::Duration::hours(3);
            let json = serde_json::json!({
                "id": CheckpointMetadata::generate_id(old_timestamp),
                "topic": "test-topic",
                "partition": 0,
                "attempt_timestamp": old_timestamp,
                "sequence": 1,
                "consumer_offset": 50,
                "producer_offset": 25,
                "updated_at": old_timestamp,
                "files": []
            });
            let path = store_path.join("metadata.json");
            tokio::fs::write(&path, serde_json::to_string_pretty(&json).unwrap())
                .await
                .unwrap();

            // 2h max staleness — 3h old timestamp should be stale
            let result = manager
                .try_restore_local_store(
                    "test-topic",
                    0,
                    Duration::from_secs(DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS),
                )
                .await;

            assert!(result.is_none(), "Should return None for stale metadata");
        }

        #[tokio::test]
        async fn test_returns_none_when_corrupt() {
            let temp_dir = TempDir::new().unwrap();
            let manager = create_test_store_manager(temp_dir.path().to_path_buf());
            let store_path = format_store_path(temp_dir.path(), "test-topic", 0);
            tokio::fs::create_dir_all(&store_path).await.unwrap();

            // Write invalid JSON
            let path = store_path.join("metadata.json");
            tokio::fs::write(&path, b"not valid json at all!!!")
                .await
                .unwrap();

            let result = manager
                .try_restore_local_store(
                    "test-topic",
                    0,
                    Duration::from_secs(DEFAULT_LOCAL_CHECKPOINT_MAX_STALENESS_SECS),
                )
                .await;

            assert!(result.is_none(), "Should return None for corrupt metadata");
        }
    }
}
