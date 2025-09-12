use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result};
use common_types::RawEvent;
use rocksdb::{ColumnFamilyDescriptor, Options};
use tracing::info;

use crate::metrics::MetricsHelper;
use crate::metrics_const::*;
use crate::rocksdb::store::RocksDbStore;

use super::keys::{TimestampKey, UuidIndexKey, UuidKey};
use super::metadata::{TimestampMetadata, UuidMetadata};

const UNKNOWN_STR: &str = "unknown";

/// Extract library name and version from RawEvent properties
fn extract_library_info(event: &RawEvent) -> (String, String) {
    let lib_name = event
        .properties
        .get("$lib")
        .and_then(|v| v.as_str())
        .unwrap_or(UNKNOWN_STR)
        .to_string();

    let lib_version = event
        .properties
        .get("$lib_version")
        .and_then(|v| v.as_str())
        .unwrap_or(UNKNOWN_STR)
        .to_string();

    (lib_name, lib_version)
}

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
    metrics: MetricsHelper,
}

impl DeduplicationStore {
    // Column families for different tracking patterns
    const TIMESTAMP_CF: &'static str = "timestamp_records";
    const UUID_CF: &'static str = "uuid_records";
    const UUID_TIMESTAMP_INDEX_CF: &'static str = "uuid_timestamp_index"; // For cleanup

    pub fn new(config: DeduplicationStoreConfig, topic: String, partition: i32) -> Result<Self> {
        let metrics = MetricsHelper::with_partition(&topic, partition)
            .with_label("service", "kafka-deduplicator");

        // Create all three column families
        let store = RocksDbStore::new(
            &config.path,
            vec![
                ColumnFamilyDescriptor::new(Self::TIMESTAMP_CF, Options::default()),
                ColumnFamilyDescriptor::new(Self::UUID_CF, Options::default()),
                ColumnFamilyDescriptor::new(Self::UUID_TIMESTAMP_INDEX_CF, Options::default()),
            ],
            metrics.clone(),
        )?;

        Ok(Self {
            store: Arc::new(store),
            topic,
            partition,
            metrics,
        })
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

    /// Handle an event, tracking both timestamp and UUID patterns
    pub fn handle_event_with_raw(&self, raw_event: &RawEvent) -> Result<bool> {
        let _start_time = Instant::now();

        // Track timestamp-based deduplication
        let is_new_timestamp = self.handle_timestamp_dedup(raw_event)?;

        // Track UUID-based deduplication (only if UUID exists)
        if raw_event.uuid.is_some() {
            let _is_new_uuid = self.handle_uuid_dedup(raw_event)?;
        }

        Ok(is_new_timestamp)
    }

    /// Handle timestamp-based deduplication
    fn handle_timestamp_dedup(&self, raw_event: &RawEvent) -> Result<bool> {
        let key = TimestampKey::from(raw_event);
        let key_bytes: Vec<u8> = (&key).into();

        // Check if this is a duplicate
        let existing_metadata = self.store.get(Self::TIMESTAMP_CF, &key_bytes)?;

        if let Some(existing_bytes) = existing_metadata {
            // Key exists - it's a duplicate
            let mut metadata: TimestampMetadata =
                bincode::serde::decode_from_slice(&existing_bytes, bincode::config::standard())
                    .map(|(m, _)| m)
                    .context("Failed to deserialize timestamp metadata")?;

            // Calculate similarity
            let similarity = metadata.calculate_similarity(raw_event)?;

            // Update metadata
            metadata.update_duplicate(raw_event);

            // Log the duplicate
            info!(
                "Timestamp duplicate: {} for key {:?}, Similarity: {:.2}",
                metadata.get_metrics_summary(),
                key,
                similarity.overall_score
            );

            // Emit metrics
            let (lib_name, _lib_version) = extract_library_info(raw_event);
            self.metrics
                .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                .with_label("lib", &lib_name)
                .with_label("dedup_type", "timestamp")
                .increment(1);

            self.metrics
                .histogram(TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(metadata.seen_uuids.len() as f64);

            self.metrics
                .histogram(TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.overall_score);

            self.metrics
                .histogram(TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.different_field_count as f64);

            self.metrics
                .histogram(TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.different_property_count as f64);

            self.metrics
                .histogram(TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.properties_similarity);

            // Emit counters for specific fields that differ
            for (field_name, _, _) in &similarity.different_fields {
                self.metrics
                    .counter(TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER)
                    .with_label("lib", &lib_name)
                    .with_label("field", field_name)
                    .increment(1);
            }

            // Store updated metadata
            let serialized = bincode::serde::encode_to_vec(&metadata, bincode::config::standard())
                .context("Failed to serialize timestamp metadata")?;
            self.store
                .put(Self::TIMESTAMP_CF, &key_bytes, &serialized)?;

            return Ok(false); // It's a duplicate
        }

        // Key doesn't exist - store it with initial metadata
        let metadata = TimestampMetadata::new(raw_event);
        let serialized = bincode::serde::encode_to_vec(&metadata, bincode::config::standard())
            .context("Failed to serialize timestamp metadata")?;

        self.store
            .put_batch(Self::TIMESTAMP_CF, vec![(&key_bytes, &serialized)])?;

        // Track unique event
        let (lib_name, _lib_version) = extract_library_info(raw_event);
        self.metrics
            .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
            .with_label("lib", &lib_name)
            .with_label("dedup_type", "timestamp")
            .increment(1);

        Ok(true) // New event
    }

    /// Handle UUID-based deduplication
    fn handle_uuid_dedup(&self, raw_event: &RawEvent) -> Result<bool> {
        let key = UuidKey::from(raw_event);
        let key_bytes: Vec<u8> = (&key).into();

        // Extract timestamp for indexing
        let timestamp = raw_event
            .timestamp
            .as_ref()
            .and_then(|t| crate::utils::timestamp::parse_timestamp(t))
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis() as u64);

        // Check if this UUID combination exists
        let existing_metadata = self.store.get(Self::UUID_CF, &key_bytes)?;

        if let Some(existing_bytes) = existing_metadata {
            // UUID combination exists - it's a duplicate
            let mut metadata: UuidMetadata =
                bincode::serde::decode_from_slice(&existing_bytes, bincode::config::standard())
                    .map(|(m, _)| m)
                    .context("Failed to deserialize UUID metadata")?;

            // Calculate similarity
            let similarity = metadata.calculate_similarity(raw_event)?;

            // Update metadata
            metadata.update_duplicate(raw_event);

            // Log the duplicate
            info!(
                "UUID duplicate: {} for key {:?}",
                metadata.get_metrics_summary(),
                key
            );

            // Emit metrics
            let (lib_name, _) = extract_library_info(raw_event);

            self.metrics
                .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                .with_label("lib", &lib_name)
                .with_label("dedup_type", "uuid")
                .increment(1);

            self.metrics
                .histogram(UUID_DEDUP_TIMESTAMP_VARIANCE_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(metadata.get_timestamp_variance() as f64);

            self.metrics
                .histogram(UUID_DEDUP_UNIQUE_TIMESTAMPS_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(metadata.seen_timestamps.len() as f64);

            self.metrics
                .histogram(UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.overall_score);

            self.metrics
                .histogram(UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.different_field_count as f64);

            self.metrics
                .histogram(UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.different_property_count as f64);

            self.metrics
                .histogram(UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM)
                .with_label("lib", &lib_name)
                .record(similarity.properties_similarity);

            // Emit counters for specific fields that differ
            for (field_name, _, _) in &similarity.different_fields {
                self.metrics
                    .counter(UUID_DEDUP_FIELD_DIFFERENCES_COUNTER)
                    .with_label("lib", &lib_name)
                    .with_label("field", field_name)
                    .increment(1);
            }

            // Store updated metadata
            let serialized = bincode::serde::encode_to_vec(&metadata, bincode::config::standard())
                .context("Failed to serialize UUID metadata")?;
            self.store.put(Self::UUID_CF, &key_bytes, &serialized)?;

            return Ok(false); // It's a duplicate
        }

        // New UUID combination - store it
        let metadata = UuidMetadata::new(raw_event);
        let serialized = bincode::serde::encode_to_vec(&metadata, bincode::config::standard())
            .context("Failed to serialize UUID metadata")?;

        // Store in UUID CF
        self.store
            .put_batch(Self::UUID_CF, vec![(&key_bytes, &serialized)])?;

        // Also store in timestamp index for cleanup
        let index_key = UuidIndexKey::new(timestamp, key_bytes.clone());
        let index_key_bytes: Vec<u8> = index_key.into();
        // Value is just the UUID key bytes for reference
        self.store.put_batch(
            Self::UUID_TIMESTAMP_INDEX_CF,
            vec![(&index_key_bytes, &key_bytes)],
        )?;

        // Track new UUID combination
        let (lib_name, _lib_version) = extract_library_info(raw_event);
        self.metrics
            .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
            .with_label("lib", &lib_name)
            .with_label("dedup_type", "uuid")
            .increment(1);

        Ok(true) // New UUID combination
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
    use crate::store::keys::{UuidIndexKey, UuidKey};
    use tempfile::TempDir;

    fn create_test_store(max_capacity: Option<u64>) -> (DeduplicationStore, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let max_capacity = max_capacity.unwrap_or(1_000_000);
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity,
        };
        let store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();
        (store, temp_dir)
    }

    fn create_test_raw_event_with_timestamp(
        distinct_id: &str,
        token: &str,
        event_name: &str,
        timestamp: Option<String>,
    ) -> RawEvent {
        RawEvent {
            uuid: Some(uuid::Uuid::new_v4()),
            event: event_name.to_string(),
            distinct_id: Some(serde_json::Value::String(distinct_id.to_string())),
            token: Some(token.to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: timestamp.or_else(|| Some(chrono::Utc::now().to_rfc3339())),
            ..Default::default()
        }
    }

    #[test]
    fn test_handle_event_new() {
        let (store, _temp_dir) = create_test_store(None);
        let event = create_test_raw_event_with_timestamp(
            "user1",
            "token1",
            "event1",
            Some("2021-01-01T00:00:00Z".to_string()),
        );

        let result = store.handle_event_with_raw(&event).unwrap();
        assert!(result); // Should be new
    }

    #[test]
    fn test_handle_event_duplicate() {
        let (store, _temp_dir) = create_test_store(None);
        let timestamp = Some("2021-01-01T00:00:00Z".to_string());
        let event1 =
            create_test_raw_event_with_timestamp("user1", "token1", "event1", timestamp.clone());
        let event2 =
            create_test_raw_event_with_timestamp("user1", "token1", "event1", timestamp.clone());

        assert!(store.handle_event_with_raw(&event1).unwrap()); // First is new
        assert!(!store.handle_event_with_raw(&event2).unwrap()); // Second is duplicate
    }

    #[test]
    fn test_dual_tracking() {
        let (store, _temp_dir) = create_test_store(None);
        let uuid1 = uuid::Uuid::new_v4();
        let uuid2 = uuid::Uuid::new_v4();

        // Create events with same timestamp but different UUIDs
        let event1 = RawEvent {
            uuid: Some(uuid1),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid2),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        assert!(store.handle_event_with_raw(&event1).unwrap()); // First is new
        assert!(!store.handle_event_with_raw(&event2).unwrap()); // Second is duplicate by timestamp

        // Now test with same UUID but different timestamp
        let event3 = RawEvent {
            uuid: Some(uuid1),
            event: "page_view".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:10Z".to_string()), // Different timestamp
            ..Default::default()
        };

        assert!(store.handle_event_with_raw(&event3).unwrap()); // New by timestamp, but duplicate by UUID
    }

    #[test]
    fn test_uuid_timestamp_index_creation() {
        let (store, _temp_dir) = create_test_store(None);
        let uuid = uuid::Uuid::new_v4();
        let timestamp = "2021-01-01T00:00:00Z";

        let event = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some(timestamp.to_string()),
            ..Default::default()
        };

        // Process the event
        assert!(store.handle_event_with_raw(&event).unwrap());

        // Verify that the timestamp index was created
        let timestamp_ms = crate::utils::timestamp::parse_timestamp(timestamp).unwrap();

        // Create the UuidKey to match the format used in the code
        let uuid_key = UuidKey::from(&event);
        let uuid_key_bytes: Vec<u8> = (&uuid_key).into();

        // Create the index key using the UuidIndexKey struct
        let index_key_struct = UuidIndexKey::new(timestamp_ms, uuid_key_bytes.clone());
        let index_key: Vec<u8> = index_key_struct.into();

        // Check that the index entry exists
        let index_value = store
            .store
            .get(DeduplicationStore::UUID_TIMESTAMP_INDEX_CF, &index_key)
            .unwrap();
        assert!(index_value.is_some());

        // Verify the index value points to the UUID key bytes
        let stored_uuid_key = index_value.unwrap();
        assert_eq!(stored_uuid_key, uuid_key_bytes);
    }

    #[test]
    fn test_uuid_tracking_with_multiple_timestamps() {
        let (store, _temp_dir) = create_test_store(None);
        let uuid = uuid::Uuid::new_v4();

        // Same UUID, different timestamps
        let event1 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:10Z".to_string()),
            ..Default::default()
        };

        let event3 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:05Z".to_string()),
            ..Default::default()
        };

        // First event is new
        assert!(store.handle_event_with_raw(&event1).unwrap());

        // Second and third are duplicates by UUID (but different timestamps)
        assert!(store.handle_event_with_raw(&event2).unwrap()); // New timestamp
        assert!(store.handle_event_with_raw(&event3).unwrap()); // New timestamp

        // Verify UUID metadata tracks all timestamps
        let uuid_key = UuidKey::from(&event1);
        let uuid_key_bytes: Vec<u8> = (&uuid_key).into();
        let metadata_bytes = store
            .store
            .get(DeduplicationStore::UUID_CF, &uuid_key_bytes)
            .unwrap()
            .unwrap();
        let metadata: UuidMetadata =
            bincode::serde::decode_from_slice(&metadata_bytes, bincode::config::standard())
                .map(|(m, _)| m)
                .unwrap();

        // Should have 3 unique timestamps
        assert_eq!(metadata.seen_timestamps.len(), 3);
        assert_eq!(metadata.duplicate_count, 2); // Two duplicates after the first
        assert_eq!(metadata.get_timestamp_variance(), 10000); // 10 seconds in ms
    }

    #[test]
    fn test_cleanup_with_uuid_records() {
        let (store, _temp_dir) = create_test_store(Some(1000)); // Small capacity to force cleanup

        // Use timestamps relative to now for predictable cleanup behavior
        let now = chrono::Utc::now();
        let old_timestamp = (now - chrono::Duration::days(10)).to_rfc3339();
        let new_timestamp = (now - chrono::Duration::days(5)).to_rfc3339();

        // Add many old events to ensure database has measurable size
        let old_uuids: Vec<uuid::Uuid> = (0..1000).map(|_| uuid::Uuid::new_v4()).collect();
        for (i, uuid) in old_uuids.iter().enumerate() {
            let event = RawEvent {
                uuid: Some(*uuid),
                event: format!("old_event_{i}"),
                distinct_id: Some(serde_json::Value::String(format!("old_user_{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::from([
                    ("key1".to_string(), serde_json::json!("value1")),
                    ("key2".to_string(), serde_json::json!("value2")),
                ]),
                timestamp: Some(old_timestamp.clone()),
                ..Default::default()
            };
            store.handle_event_with_raw(&event).unwrap();
        }

        // Add new events (should be kept)
        let new_uuids: Vec<uuid::Uuid> = (0..100).map(|_| uuid::Uuid::new_v4()).collect();
        for (i, uuid) in new_uuids.iter().enumerate() {
            let event = RawEvent {
                uuid: Some(*uuid),
                event: format!("new_event_{i}"),
                distinct_id: Some(serde_json::Value::String(format!("new_user_{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::from([
                    ("key1".to_string(), serde_json::json!("value1")),
                    ("key2".to_string(), serde_json::json!("value2")),
                ]),
                timestamp: Some(new_timestamp.clone()),
                ..Default::default()
            };
            store.handle_event_with_raw(&event).unwrap();
        }

        // Compact and flush to ensure data is written to SST files
        store
            .store
            .compact_cf(DeduplicationStore::TIMESTAMP_CF)
            .unwrap();
        store.store.compact_cf(DeduplicationStore::UUID_CF).unwrap();
        store
            .store
            .compact_cf(DeduplicationStore::UUID_TIMESTAMP_INDEX_CF)
            .unwrap();
        store.flush().unwrap();

        // Force cleanup with 40% to clean up events older than 6 days
        // With 10 days of data, 40% means we clean up to 6 days ago
        // Since new events are 5 days old, they should be kept
        store.cleanup_old_entries_with_percentage(0.40).unwrap();

        // Verify some old UUID records can be added again (were cleaned)
        for i in 0..5 {
            let test_uuid = uuid::Uuid::new_v4();
            let old_event = RawEvent {
                uuid: Some(test_uuid),
                event: format!("old_event_{i}"),
                distinct_id: Some(serde_json::Value::String(format!("old_user_{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::new(),
                timestamp: Some(old_timestamp.clone()),
                ..Default::default()
            };

            // These should be new again after cleanup (timestamp records were deleted)
            assert!(store.handle_event_with_raw(&old_event).unwrap());
        }

        // Verify new records are still detected as duplicates
        for (i, &uuid) in new_uuids.iter().take(5).enumerate() {
            let test_event = RawEvent {
                uuid: Some(uuid),
                event: format!("new_event_{i}"),
                distinct_id: Some(serde_json::Value::String(format!("new_user_{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::new(),
                timestamp: Some(new_timestamp.clone()),
                ..Default::default()
            };

            // These should still be duplicates (not cleaned up)
            assert!(!store.handle_event_with_raw(&test_event).unwrap());
        }
    }

    #[test]
    fn test_batch_deletion_boundaries() {
        let (store, _temp_dir) = create_test_store(Some(1000)); // Small capacity to force cleanup

        // Use timestamps relative to now for predictable cleanup behavior
        let now = chrono::Utc::now();
        let base_timestamp = now - chrono::Duration::days(10);
        let base_ms = base_timestamp.timestamp_millis() as u64;

        // Create 2500 events (more than BATCH_SIZE of 1000) with sequential timestamps
        for i in 0..2500 {
            let timestamp_ms = base_ms + i;
            let timestamp = chrono::DateTime::from_timestamp_millis(timestamp_ms as i64)
                .unwrap()
                .to_rfc3339();

            let event = RawEvent {
                uuid: Some(uuid::Uuid::new_v4()),
                event: "batch_test".to_string(),
                distinct_id: Some(serde_json::Value::String(format!("user{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::from([(
                    "data".to_string(),
                    serde_json::json!(format!("value_{}", i)),
                )]),
                timestamp: Some(timestamp),
                ..Default::default()
            };
            store.handle_event_with_raw(&event).unwrap();
        }

        // Add some newer events that shouldn't be cleaned
        let new_base_timestamp = now - chrono::Duration::days(5); // 5 days ago
        let new_base_ms = new_base_timestamp.timestamp_millis() as u64;
        for i in 0..100 {
            let timestamp_ms = new_base_ms + i;
            let timestamp = chrono::DateTime::from_timestamp_millis(timestamp_ms as i64)
                .unwrap()
                .to_rfc3339();

            let event = RawEvent {
                uuid: Some(uuid::Uuid::new_v4()),
                event: "new_batch_test".to_string(),
                distinct_id: Some(serde_json::Value::String(format!("new_user{i}"))),
                token: Some("token1".to_string()),
                properties: std::collections::HashMap::new(),
                timestamp: Some(timestamp),
                ..Default::default()
            };
            store.handle_event_with_raw(&event).unwrap();
        }

        // Compact and flush to ensure proper size reporting
        store
            .store
            .compact_cf(DeduplicationStore::TIMESTAMP_CF)
            .unwrap();
        store.store.compact_cf(DeduplicationStore::UUID_CF).unwrap();
        store
            .store
            .compact_cf(DeduplicationStore::UUID_TIMESTAMP_INDEX_CF)
            .unwrap();
        store.flush().unwrap();

        // Count initial UUID records
        let uuid_cf = store
            .store
            .get_cf_handle(DeduplicationStore::UUID_CF)
            .unwrap();
        let mut count_before = 0;
        let mut iter = store
            .store
            .db
            .iterator_cf(&uuid_cf, rocksdb::IteratorMode::Start);
        while iter.next().is_some() {
            count_before += 1;
        }
        assert_eq!(count_before, 2600); // 2500 old + 100 new

        // Trigger cleanup with 40% to clean up events older than 6 days
        // With 10 days of data, 40% means we clean up to 6 days ago
        // This should remove the 10-day-old events but keep the 5-day-old events
        store.cleanup_old_entries_with_percentage(0.40).unwrap();

        // Count remaining UUID records
        let mut count_after = 0;
        let mut iter_after = store
            .store
            .db
            .iterator_cf(&uuid_cf, rocksdb::IteratorMode::Start);
        while iter_after.next().is_some() {
            count_after += 1;
        }

        // Should have cleaned up old records
        // With percentage-based cleanup, we expect approximately the new 100 to remain
        assert!(count_after < count_before);
        assert!(count_after <= 200); // Should have at most the new 100 + some boundary cases
    }

    #[test]
    fn test_no_uuid_event_handling() {
        let (store, _temp_dir) = create_test_store(None);

        // Event without UUID
        let event = RawEvent {
            uuid: None, // No UUID
            event: "no_uuid_event".to_string(),
            distinct_id: Some(serde_json::Value::String("user1".to_string())),
            token: Some("token1".to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some("2021-01-01T00:00:00Z".to_string()),
            ..Default::default()
        };

        // Should be tracked only in timestamp CF, not UUID CF
        assert!(store.handle_event_with_raw(&event).unwrap());

        // Duplicate by timestamp
        assert!(!store.handle_event_with_raw(&event).unwrap());

        // Verify no UUID tracking occurred
        let uuid_cf = store
            .store
            .get_cf_handle(DeduplicationStore::UUID_CF)
            .unwrap();
        let mut iter = store
            .store
            .db
            .iterator_cf(&uuid_cf, rocksdb::IteratorMode::Start);
        assert!(iter.next().is_none()); // UUID CF should be empty

        // Verify timestamp tracking worked
        let timestamp_key = TimestampKey::from(&event);
        let timestamp_key_bytes: Vec<u8> = (&timestamp_key).into();
        let timestamp_metadata = store
            .store
            .get(DeduplicationStore::TIMESTAMP_CF, &timestamp_key_bytes)
            .unwrap();
        assert!(timestamp_metadata.is_some());
    }
}
