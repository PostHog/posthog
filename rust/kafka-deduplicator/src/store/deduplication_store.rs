use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result};
use rocksdb::{ColumnFamilyDescriptor, Options, SliceTransform};
use tracing::info;

use crate::metrics::MetricsHelper;
use crate::rocksdb::store::{block_based_table_factory, RocksDbStore};

use super::keys::TimestampKey;
use crate::pipelines::ingestion_events::TimestampMetadata;

#[derive(Debug, Clone)]
pub struct DeduplicationStoreConfig {
    // Path to the store in disk
    pub path: PathBuf,
    // Maximum capacity in bytes
    pub max_capacity: u64,
}

/// Entry for batch writing timestamp records
pub struct TimestampBatchEntry<'a> {
    pub key: &'a [u8],
    pub value: &'a [u8],
}

#[derive(Debug, Clone)]
pub struct DeduplicationStore {
    store: Arc<RocksDbStore>,
    topic: String,
    partition: i32,
}

impl DeduplicationStore {
    // Column family for timestamp-based deduplication
    const TIMESTAMP_CF: &'static str = "timestamp_records";

    pub fn new(config: DeduplicationStoreConfig, topic: String, partition: i32) -> Result<Self> {
        // Create metrics helper for the RocksDB store
        let metrics = MetricsHelper::with_partition(&topic, partition)
            .with_label("service", "kafka-deduplicator");

        let cf_descriptors = Self::get_cf_descriptors();
        let store = RocksDbStore::new(&config.path, cf_descriptors, metrics)?;

        Ok(Self {
            store: Arc::new(store),
            topic,
            partition,
        })
    }

    fn get_cf_descriptors() -> Vec<ColumnFamilyDescriptor> {
        let block_opts = block_based_table_factory();

        // ----- CF: TimestampKey (prefix = 8-byte BE timestamp)
        let mut ts_cf_opts = Options::default();
        ts_cf_opts.set_block_based_table_factory(&block_opts);
        ts_cf_opts.set_prefix_extractor(SliceTransform::create_fixed_prefix(8)); // <- per-CF
        ts_cf_opts.set_write_buffer_size(8 * 1024 * 1024);
        ts_cf_opts.set_max_write_buffer_number(3);
        // IMPORTANT: CF options don't inherit from DB options, must set compression explicitly
        // LZ4 is ~2x faster than Snappy for both compression and decompression
        ts_cf_opts.set_compression_type(rocksdb::DBCompressionType::Lz4);

        vec![ColumnFamilyDescriptor::new(Self::TIMESTAMP_CF, ts_cf_opts)]
    }

    // Storage operations for each column family

    /// Get a timestamp record from the store
    pub fn get_timestamp_record(&self, key: &TimestampKey) -> Result<Option<TimestampMetadata>> {
        let key_bytes: Vec<u8> = key.into();
        match self.store.get(Self::TIMESTAMP_CF, &key_bytes)? {
            Some(bytes) => {
                let metadata =
                    bincode::serde::decode_from_slice(&bytes, bincode::config::standard())
                        .map(|(m, _)| m)
                        .context("Failed to deserialize timestamp metadata")?;
                Ok(Some(metadata))
            }
            None => Ok(None),
        }
    }

    /// Put a timestamp record in the store
    pub fn put_timestamp_record(
        &self,
        key: &TimestampKey,
        metadata: &TimestampMetadata,
    ) -> Result<()> {
        let key_bytes: Vec<u8> = key.into();
        let value = bincode::serde::encode_to_vec(metadata, bincode::config::standard())
            .context("Failed to serialize timestamp metadata")?;
        self.store.put(Self::TIMESTAMP_CF, &key_bytes, &value)
    }

    /// Get non-duplicated keys based on timestamp pattern (for batch processing)
    pub fn get_non_duplicated_keys<'a>(&self, keys: Vec<&'a [u8]>) -> Result<Vec<&'a [u8]>> {
        if keys.is_empty() {
            return Ok(vec![]);
        }

        // Use RocksDB's multi_get which leverages bloom filters internally
        let results = self.store.multi_get(Self::TIMESTAMP_CF, keys.clone())?;

        // Return only keys that don't exist (None results)
        let non_duplicated: Vec<&[u8]> = keys
            .into_iter()
            .zip(results)
            .filter_map(|(key, result)| {
                if result.is_none() {
                    Some(key) // Key doesn't exist - not a duplicate
                } else {
                    None // Key exists - it's a duplicate
                }
            })
            .collect();

        Ok(non_duplicated)
    }

    /// Batch get timestamp records
    pub fn multi_get_timestamp_records(&self, keys: Vec<&[u8]>) -> Result<Vec<Option<Vec<u8>>>> {
        self.store.multi_get(Self::TIMESTAMP_CF, keys)
    }

    /// Batch put timestamp records
    pub fn put_timestamp_records_batch(&self, entries: Vec<TimestampBatchEntry>) -> Result<()> {
        let raw_entries: Vec<(&[u8], &[u8])> = entries.iter().map(|e| (e.key, e.value)).collect();
        self.store.put_batch(Self::TIMESTAMP_CF, raw_entries)
    }

    pub fn cleanup_old_entries(&self) -> Result<u64> {
        // Default to 10% cleanup if no percentage specified
        self.cleanup_old_entries_with_percentage(0.10)
    }

    pub fn cleanup_old_entries_with_percentage(&self, cleanup_percentage: f64) -> Result<u64> {
        let start_time = Instant::now();

        // Get initial size for metrics
        let initial_size = self.get_total_size()?;

        // Clean up old entries from timestamp CF (they're timestamp-prefixed so easy to clean)
        let cf = self.store.get_cf_handle(Self::TIMESTAMP_CF)?;

        // Get first key
        let mut first_iter = self.store.db.iterator_cf(&cf, rocksdb::IteratorMode::Start);
        let (first_key_bytes, first_timestamp) = if let Some(Ok((first_key, _))) = first_iter.next()
        {
            let first_key_parsed: TimestampKey = first_key.as_ref().try_into()?;
            (first_key.to_vec(), first_key_parsed.timestamp)
        } else {
            // No data to clean up
            return Ok(0);
        };
        drop(first_iter);

        // Get last key to understand the time range
        let mut last_iter = self.store.db.iterator_cf(&cf, rocksdb::IteratorMode::End);
        let last_timestamp = if let Some(Ok((last_key, _))) = last_iter.next() {
            let last_key_parsed: TimestampKey = last_key.as_ref().try_into()?;
            last_key_parsed.timestamp
        } else {
            // Should not happen if we have a first key, but handle gracefully
            first_timestamp
        };
        drop(last_iter);

        // Calculate the time range of data we have
        let time_range = last_timestamp.saturating_sub(first_timestamp);

        if time_range == 0 {
            info!(
                "Store {}:{} - All data has same timestamp {}, skipping cleanup",
                self.topic, self.partition, first_timestamp
            );
            return Ok(0);
        }

        // Calculate how much of the time range to clean up (percentage)
        let cleanup_duration = (time_range as f64 * cleanup_percentage) as u64;

        // Calculate the cutoff timestamp
        let cleanup_timestamp = first_timestamp + cleanup_duration;

        info!(
            "Store {}:{} - Cleaning up {}% of time range. First: {}, Last: {}, Cutoff: {}",
            self.topic,
            self.partition,
            (cleanup_percentage * 100.0) as u32,
            first_timestamp,
            last_timestamp,
            cleanup_timestamp
        );

        // Make sure we have something to delete
        if cleanup_timestamp <= first_timestamp {
            info!(
                "Store {}:{} - No data old enough to clean up",
                self.topic, self.partition
            );
            return Ok(0);
        }

        // Create an end key with the cleanup timestamp and empty strings for other fields
        // This ensures all keys with timestamps less than cleanup_timestamp are deleted
        let end_key = TimestampKey::new(
            cleanup_timestamp,
            String::new(),
            String::new(),
            String::new(),
        );
        let last_key_bytes: Vec<u8> = (&end_key).into();

        self.store.delete_range(
            Self::TIMESTAMP_CF,
            first_key_bytes.as_ref(),
            last_key_bytes.as_ref(),
        )?;

        // Spawn compaction on a background thread to avoid blocking cleanup.
        // RocksDB's compact_range is synchronous and can block for extended periods.
        // delete_range creates tombstones but doesn't immediately free disk space -
        // compaction merges/removes tombstoned data to reclaim space.
        let store = self.store.clone();
        let topic = self.topic.clone();
        let partition = self.partition;
        std::thread::spawn(move || {
            info!(
                "Store {}:{} - Starting background compaction after cleanup",
                topic, partition
            );
            let compaction_start = Instant::now();

            store.compact_range(
                Self::TIMESTAMP_CF,
                Some(first_key_bytes.as_ref()),
                Some(last_key_bytes.as_ref()),
            );

            info!(
                "Store {}:{} - Background compaction completed in {:?}",
                topic,
                partition,
                compaction_start.elapsed()
            );
        });

        // Calculate bytes freed (will likely be 0 since compaction is now async)
        let final_size = self.get_total_size()?;
        let bytes_freed = initial_size.saturating_sub(final_size);

        info!(
            "Store {}:{} cleanup completed in {:?} (compaction spawned in background)",
            self.topic,
            self.partition,
            start_time.elapsed()
        );

        Ok(bytes_freed)
    }

    pub fn get_store(&self) -> &RocksDbStore {
        &self.store
    }

    /// Create an incremental checkpoint of the deduplication store
    pub fn create_checkpoint<P: AsRef<std::path::Path>>(&self, checkpoint_path: P) -> Result<()> {
        self.store.create_checkpoint(checkpoint_path)
    }

    /// Get the current database path
    pub fn get_db_path(&self) -> &std::path::PathBuf {
        self.store.get_path()
    }

    /// Get current SST file names for tracking incremental checkpoint changes
    pub fn get_sst_file_names(&self) -> Result<Vec<String>> {
        self.store.get_sst_file_names(Self::TIMESTAMP_CF)
    }

    /// Get the topic this store is responsible for
    pub fn get_topic(&self) -> &str {
        &self.topic
    }

    /// Get the partition this store is responsible for
    pub fn get_partition(&self) -> i32 {
        self.partition
    }

    /// Get the total size of the store
    pub fn get_total_size(&self) -> Result<u64> {
        self.store.get_db_size(Self::TIMESTAMP_CF)
    }

    /// Get the age of the oldest data in seconds (current time - oldest timestamp)
    /// Returns None if the store is empty
    pub fn get_oldest_data_age_seconds(&self) -> Result<Option<u64>> {
        let cf = self.store.get_cf_handle(Self::TIMESTAMP_CF)?;

        // Get first (oldest) key
        let mut first_iter = self.store.db.iterator_cf(&cf, rocksdb::IteratorMode::Start);
        let oldest_timestamp = if let Some(Ok((first_key, _))) = first_iter.next() {
            let first_key_parsed: TimestampKey = first_key.as_ref().try_into()?;
            first_key_parsed.timestamp
        } else {
            return Ok(None); // Empty store
        };
        drop(first_iter);

        // Calculate age using wall clock
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        Ok(Some(now.saturating_sub(oldest_timestamp)))
    }

    /// Flush the store to disk
    pub fn flush(&self) -> Result<()> {
        self.store.flush_all_cf()
    }

    /// Update metrics for this store (including database size)
    pub fn update_metrics(&self) -> Result<()> {
        self.store.update_db_metrics(Self::TIMESTAMP_CF)
    }

    /// Create a checkpoint and return metadata about the checkpoint
    /// This ensures consistency by:
    /// 1. Flushing WAL to disk
    /// 2. Flushing all column families
    /// 3. Capturing sequence number for consistency verification
    /// 4. Creating the checkpoint with hard links
    pub fn create_checkpoint_with_metadata<P: AsRef<std::path::Path>>(
        &self,
        checkpoint_path: P,
    ) -> Result<LocalCheckpointInfo> {
        // Step 1: Flush WAL to ensure durability
        self.store.flush_wal(true)?;

        // Step 2: Flush all column families to ensure data is in SST files
        self.flush()?;

        // Step 3: Get sequence number for consistency tracking
        let sequence = self.store.latest_sequence_number();

        // Step 4: Get SST files after flush
        let sst_files = self.get_sst_file_names()?;

        // Step 5: Create the checkpoint (RocksDB internally handles file deletion safety)
        self.store.create_checkpoint(checkpoint_path)?;

        Ok(LocalCheckpointInfo {
            sst_files,
            sequence,
        })
    }
}

/// Information about a local RocksDB checkpoint
#[derive(Debug, Clone)]
pub struct LocalCheckpointInfo {
    /// SST files included in the checkpoint
    pub sst_files: Vec<String>,
    /// RocksDB sequence number at checkpoint time
    pub sequence: u64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_types::RawEvent;
    use tempfile::TempDir;

    fn create_test_store() -> (DeduplicationStore, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1_000_000,
        };
        let store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();
        (store, temp_dir)
    }

    fn create_test_raw_event() -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_timestamp_record_storage() {
        let (store, _temp_dir) = create_test_store();

        // Create a test key and metadata
        let event = create_test_raw_event();
        let key = TimestampKey::from(&event);
        let metadata = TimestampMetadata::new(&event);

        // Should not exist initially
        assert!(store.get_timestamp_record(&key).unwrap().is_none());

        // Store the metadata
        store.put_timestamp_record(&key, &metadata).unwrap();

        // Should exist now
        let retrieved = store.get_timestamp_record(&key).unwrap();
        assert!(retrieved.is_some());

        // Verify the metadata was stored correctly
        let retrieved_metadata = retrieved.unwrap();
        assert_eq!(retrieved_metadata.duplicate_count, 0);
        // Verify the original event was stored correctly by converting back
        let stored_event = retrieved_metadata.get_original_event().unwrap();
        assert_eq!(stored_event.event, event.event);
        assert_eq!(stored_event.uuid, event.uuid);
        assert_eq!(stored_event.distinct_id, event.distinct_id);
        assert_eq!(stored_event.token, event.token);
        assert_eq!(retrieved_metadata.seen_uuids.len(), 1);
        if let Some(uuid) = event.uuid {
            assert!(retrieved_metadata.seen_uuids.contains(&uuid.to_string()));
        }
    }

    #[test]
    fn test_batch_deduplication() {
        let (store, _temp_dir) = create_test_store();

        // Create test keys as raw bytes (since get_non_duplicated_keys still uses raw bytes)
        let keys: Vec<&[u8]> = vec![b"key1", b"key2", b"key3"];

        // All should be non-duplicated initially
        let non_dup = store.get_non_duplicated_keys(keys.clone()).unwrap();
        assert_eq!(non_dup.len(), 3);

        // Add one key to timestamp CF directly (using raw store access for this test)
        store
            .store
            .put(DeduplicationStore::TIMESTAMP_CF, b"key2", b"value2")
            .unwrap();

        // Now only 2 should be non-duplicated
        let non_dup = store.get_non_duplicated_keys(keys).unwrap();
        assert_eq!(non_dup.len(), 2);
        assert!(!non_dup.contains(&b"key2".as_ref()));
    }

    #[test]
    fn test_store_creation_and_basic_operations() {
        let (store, _temp_dir) = create_test_store();

        // Test that store was created successfully
        assert_eq!(store.get_topic(), "test_topic");
        assert_eq!(store.get_partition(), 0);

        // Test flush doesn't error
        store.flush().unwrap();

        // Test getting total size (should not error)
        let _size = store.get_total_size().unwrap();
    }
}
