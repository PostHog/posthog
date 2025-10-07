use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result};
use rocksdb::{ColumnFamilyDescriptor, Options};
use tracing::info;

use crate::rocksdb::store::RocksDbStore;

use super::keys::{TimestampKey, UuidIndexKey, UuidKey};
use super::metadata::{TimestampMetadata, UuidMetadata};

#[derive(Debug, Clone)]
pub struct DeduplicationStoreConfig {
    // Path to the store in disk
    pub path: PathBuf,
    // Maximum capacity in bytes
    pub max_capacity: u64,
}

#[derive(Debug, Clone)]
pub struct DeduplicationStore {
    store: Arc<RocksDbStore>,
    topic: String,
    partition: i32,
}

#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DeduplicationResultReason {
    OnlyUuidDifferent,
    OnlyTimestampDifferent,
    SameEvent,
}

#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DeduplicationType {
    Timestamp,
    UUID,
}

#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DeduplicationResult {
    ConfirmedDuplicate(DeduplicationType, DeduplicationResultReason), // The reason why it's a confirmed duplicate
    PotentialDuplicate(DeduplicationType),
    New,
    Skipped,
}

impl DeduplicationResult {
    pub fn is_duplicate(&self) -> bool {
        matches!(self, DeduplicationResult::ConfirmedDuplicate(_, _))
    }
}

impl DeduplicationStore {
    // Column families for different tracking patterns
    const TIMESTAMP_CF: &'static str = "timestamp_records";
    const UUID_CF: &'static str = "uuid_records";
    const UUID_TIMESTAMP_INDEX_CF: &'static str = "uuid_timestamp_index"; // For cleanup

    pub fn new(config: DeduplicationStoreConfig, topic: String, partition: i32) -> Result<Self> {
        // Create metrics helper for the RocksDB store
        let metrics = crate::metrics::MetricsHelper::with_partition(&topic, partition)
            .with_label("service", "kafka-deduplicator");

        // Create all three column families
        let store = RocksDbStore::new(
            &config.path,
            vec![
                ColumnFamilyDescriptor::new(Self::TIMESTAMP_CF, Options::default()),
                ColumnFamilyDescriptor::new(Self::UUID_CF, Options::default()),
                ColumnFamilyDescriptor::new(Self::UUID_TIMESTAMP_INDEX_CF, Options::default()),
            ],
            metrics,
        )?;

        Ok(Self {
            store: Arc::new(store),
            topic,
            partition,
        })
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

    /// Get a UUID record from the store
    pub fn get_uuid_record(&self, key: &UuidKey) -> Result<Option<UuidMetadata>> {
        let key_bytes: Vec<u8> = key.into();
        match self.store.get(Self::UUID_CF, &key_bytes)? {
            Some(bytes) => {
                let metadata =
                    bincode::serde::decode_from_slice(&bytes, bincode::config::standard())
                        .map(|(m, _)| m)
                        .context("Failed to deserialize UUID metadata")?;
                Ok(Some(metadata))
            }
            None => Ok(None),
        }
    }

    /// Put a UUID record in the store and automatically create the timestamp index
    pub fn put_uuid_record(
        &self,
        key: &UuidKey,
        metadata: &UuidMetadata,
        timestamp: u64,
    ) -> Result<()> {
        let key_bytes: Vec<u8> = key.into();
        let value = bincode::serde::encode_to_vec(metadata, bincode::config::standard())
            .context("Failed to serialize UUID metadata")?;

        // Store the UUID record
        self.store.put(Self::UUID_CF, &key_bytes, &value)?;

        // Automatically create the timestamp index for cleanup
        let index_key = UuidIndexKey::new(timestamp, key_bytes.clone());
        let index_key_bytes: Vec<u8> = index_key.into();
        self.store
            .put(Self::UUID_TIMESTAMP_INDEX_CF, &index_key_bytes, &key_bytes)?;

        Ok(())
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

        // Collect UUID keys to delete first (minimize iterator lifetime)
        let index_cf = self.store.get_cf_handle(Self::UUID_TIMESTAMP_INDEX_CF)?;
        let mut uuid_keys_to_delete = Vec::new();
        let mut kept_count = 0;

        {
            // Scope the iterator to release lock quickly
            let mut index_iter = self
                .store
                .db
                .iterator_cf(&index_cf, rocksdb::IteratorMode::Start);

            while let Some(Ok((index_key, uuid_key_bytes))) = index_iter.next() {
                // Check if this key is within our cleanup range
                if let Some(timestamp) = UuidIndexKey::parse_timestamp(&index_key) {
                    if timestamp >= cleanup_timestamp {
                        kept_count += 1;
                        break; // We've reached keys that shouldn't be deleted
                    }
                    // Collect UUID key for batch deletion
                    uuid_keys_to_delete.push(uuid_key_bytes.to_vec());
                }
            }
        } // Iterator dropped here, releasing read lock

        // Now delete UUID keys in batches
        let deleted_count = uuid_keys_to_delete.len();
        if !uuid_keys_to_delete.is_empty() {
            const BATCH_SIZE: usize = 1000;
            for chunk in uuid_keys_to_delete.chunks(BATCH_SIZE) {
                let mut batch = rocksdb::WriteBatch::default();
                for key in chunk {
                    batch.delete_cf(&self.store.get_cf_handle(Self::UUID_CF)?, key);
                }
                self.store.db.write(batch)?;
            }
        }

        info!(
            "Store {}:{} - UUID cleanup: deleted {} records, keeping {} records",
            self.topic, self.partition, deleted_count, kept_count
        );

        // Now delete the index entries themselves using range delete (this is efficient as it's timestamp-prefixed)
        let index_start = UuidIndexKey::range_start();
        let index_end = UuidIndexKey::range_end(cleanup_timestamp);
        self.store.delete_range(
            Self::UUID_TIMESTAMP_INDEX_CF,
            index_start.as_ref(),
            index_end.as_ref(),
        )?;

        // Calculate bytes freed
        let final_size = self.get_total_size()?;
        let bytes_freed = initial_size.saturating_sub(final_size);

        // Log cleanup results for this store
        if bytes_freed > 0 {
            info!(
                "Store {}:{} cleanup freed {} bytes in {:?}",
                self.topic,
                self.partition,
                bytes_freed,
                start_time.elapsed()
            );
        }

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
        // Get SST files from both column families
        let mut sst_files = self.store.get_sst_file_names(Self::TIMESTAMP_CF)?;
        let uuid_sst_files = self.store.get_sst_file_names(Self::UUID_CF)?;
        sst_files.extend(uuid_sst_files);
        sst_files.sort();
        sst_files.dedup();
        Ok(sst_files)
    }

    /// Get the topic this store is responsible for
    pub fn get_topic(&self) -> &str {
        &self.topic
    }

    /// Get the partition this store is responsible for
    pub fn get_partition(&self) -> i32 {
        self.partition
    }

    /// Get the total size of all column families in this store
    pub fn get_total_size(&self) -> Result<u64> {
        let timestamp_size = self.store.get_db_size(Self::TIMESTAMP_CF)?;
        let uuid_size = self.store.get_db_size(Self::UUID_CF)?;
        let index_size = self.store.get_db_size(Self::UUID_TIMESTAMP_INDEX_CF)?;
        Ok(timestamp_size + uuid_size + index_size)
    }

    /// Flush the store to disk
    pub fn flush(&self) -> Result<()> {
        self.store.flush_cf(Self::TIMESTAMP_CF)?;
        self.store.flush_cf(Self::UUID_CF)?;
        Ok(())
    }

    /// Update metrics for this store (including database size)
    pub fn update_metrics(&self) -> Result<()> {
        self.store.update_db_metrics(Self::TIMESTAMP_CF)?;
        self.store.update_db_metrics(Self::UUID_CF)?;
        self.store
            .update_db_metrics(Self::UUID_TIMESTAMP_INDEX_CF)?;
        Ok(())
    }

    /// Create a checkpoint and return the SST files at the time of checkpoint
    pub fn create_checkpoint_with_metadata<P: AsRef<std::path::Path>>(
        &self,
        checkpoint_path: P,
    ) -> Result<Vec<String>> {
        // Flush before checkpoint to ensure all data is in SST files
        self.flush()?;

        // Get SST files before checkpoint
        let sst_files = self.get_sst_file_names()?;

        // Create the checkpoint
        self.store.create_checkpoint(checkpoint_path)?;

        Ok(sst_files)
    }
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
    fn test_uuid_record_storage() {
        let (store, _temp_dir) = create_test_store();

        // Create a test key and metadata
        let event = create_test_raw_event();
        let key = UuidKey::from(&event);
        let metadata = UuidMetadata::new(&event);
        let timestamp = 1234567890;

        // Should not exist initially
        assert!(store.get_uuid_record(&key).unwrap().is_none());

        // Store the metadata
        store.put_uuid_record(&key, &metadata, timestamp).unwrap();

        // Should exist now
        let retrieved = store.get_uuid_record(&key).unwrap();
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
        assert_eq!(retrieved_metadata.seen_timestamps.len(), 1);
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
