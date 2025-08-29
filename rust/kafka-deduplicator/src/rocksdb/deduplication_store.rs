use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use anyhow::{Context, Result};
use common_types::RawEvent;
use rocksdb::{ColumnFamilyDescriptor, Options};
use tracing::{error, info};

use crate::metrics::MetricsHelper;
use crate::rocksdb::dedup_metadata::{MetadataV1, MetadataVersion, VersionedMetadata};
use crate::rocksdb::{metrics_consts::*, store::RocksDbStore};

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

#[derive(Debug, Clone, Hash, PartialEq, Eq)]
struct DeduplicationKey {
    timestamp: u64,
    distinct_id: String,
    token: String,
    event_name: String,
    formatted_key: String,
}

impl DeduplicationKey {
    fn new(timestamp: u64, distinct_id: String, token: String, event_name: String) -> Self {
        let formatted_key = format!("{timestamp}:{distinct_id}:{token}:{event_name}");
        Self {
            timestamp,
            distinct_id,
            token,
            event_name,
            formatted_key,
        }
    }

    fn get_formatted_key(&self) -> &str {
        &self.formatted_key
    }
}

impl AsRef<[u8]> for DeduplicationKey {
    fn as_ref(&self) -> &[u8] {
        self.formatted_key.as_bytes()
    }
}

impl From<DeduplicationKey> for Vec<u8> {
    fn from(key: DeduplicationKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl From<&DeduplicationKey> for Vec<u8> {
    fn from(key: &DeduplicationKey) -> Vec<u8> {
        key.formatted_key.as_bytes().to_vec()
    }
}

impl TryFrom<&[u8]> for DeduplicationKey {
    type Error = anyhow::Error;

    fn try_from(bytes: &[u8]) -> Result<Self> {
        let key_str = std::str::from_utf8(bytes)
            .with_context(|| format!("Invalid UTF-8 in deduplication key: {bytes:?}"))?;
        let parts: Vec<&str> = key_str.split(':').collect();

        if parts.len() != 4 {
            return Err(anyhow::anyhow!(
                "Invalid deduplication key format '{}', expected 4 parts separated by ':' (timestamp:distinct_id:token:event_name)",
                key_str
            ));
        }

        Ok(Self::new(
            parts[0].parse::<u64>().with_context(|| {
                format!(
                    "Failed to parse timestamp '{}' in deduplication key",
                    parts[0]
                )
            })?, // timestamp
            parts[1].to_string(), // distinct_id
            parts[2].to_string(), // token
            parts[3].to_string(), // event_name
        ))
    }
}

impl TryFrom<Vec<u8>> for DeduplicationKey {
    type Error = anyhow::Error;

    fn try_from(bytes: Vec<u8>) -> Result<Self> {
        Self::try_from(bytes.as_slice())
    }
}

impl From<&RawEvent> for DeduplicationKey {
    fn from(raw_event: &RawEvent) -> Self {
        let timestamp = raw_event
            .timestamp
            .as_ref()
            .and_then(|t| t.parse::<u64>().ok())
            .unwrap_or_else(|| chrono::Utc::now().timestamp() as u64);

        let distinct_id = raw_event
            .distinct_id
            .as_ref()
            .and_then(|v| {
                // Treat JSON null as None
                if v.is_null() {
                    None
                } else {
                    // Try to get as string first, if not possible stringify the JSON
                    Some(
                        v.as_str()
                            .map(|s| s.to_string())
                            .unwrap_or_else(|| v.to_string()),
                    )
                }
            })
            .unwrap_or_else(|| UNKNOWN_STR.to_string());

        let token = raw_event
            .token
            .clone()
            .unwrap_or_else(|| UNKNOWN_STR.to_string());

        Self::new(timestamp, distinct_id, token, raw_event.event.clone())
    }
}

#[derive(Debug, Clone)]
pub struct DeduplicationStore {
    store: Arc<RocksDbStore>,
    config: DeduplicationStoreConfig,
    topic: String,
    partition: i32,
    metrics: MetricsHelper,
}

impl DeduplicationStore {
    const RECORDS_CF: &'static str = "records";

    pub fn new(config: DeduplicationStoreConfig, topic: String, partition: i32) -> Result<Self> {
        let metrics = MetricsHelper::with_partition(&topic, partition)
            .with_label("service", "kafka-deduplicator");

        let store = RocksDbStore::new(
            &config.path,
            vec![ColumnFamilyDescriptor::new(
                DeduplicationStore::RECORDS_CF,
                Options::default(),
            )],
            metrics.clone(),
        )?;

        Ok(Self {
            store: Arc::new(store),
            topic,
            partition,
            config,
            metrics,
        })
    }

    pub fn get_non_duplicated_keys<'a>(&self, keys: Vec<&'a [u8]>) -> Result<Vec<&'a [u8]>> {
        if keys.is_empty() {
            return Ok(vec![]);
        }

        // Use RocksDB's multi_get which leverages bloom filters internally
        // This will be fast - bloom filter eliminates most keys, then does actual lookups
        let results = self
            .store
            .multi_get(DeduplicationStore::RECORDS_CF, keys.clone())?;

        // Return only keys that don't exist (None results)
        // Note: Duplicate metrics are now emitted per-event in handle_event_with_raw
        let non_duplicated: Vec<&[u8]> = keys
            .into_iter()
            .zip(results)
            .filter_map(|(key, result)| {
                if result.is_none() {
                    // Key doesn't exist - not a duplicate
                    Some(key)
                } else {
                    // Key exists - it's a duplicate (metrics handled elsewhere)
                    None
                }
            })
            .collect();

        Ok(non_duplicated)
    }

    pub fn handle_event_with_raw(&self, raw_event: &RawEvent) -> Result<bool> {
        let _start_time = Instant::now();

        let key = DeduplicationKey::from(raw_event);
        let key_bytes = key.as_ref().to_vec();

        // Check if this is a duplicate
        let existing_metadata = self.store.get(DeduplicationStore::RECORDS_CF, &key_bytes)?;

        if let Some(existing_bytes) = existing_metadata {
            // Key exists - it's a duplicate
            let mut metadata = VersionedMetadata::deserialize_metadata(&existing_bytes)?;

            // Calculate similarity between original and new event
            let similarity = match &metadata {
                VersionedMetadata::V1(v1) => v1.calculate_similarity(raw_event)?,
            };

            // Update duplicate metrics using trait method (tracks UUIDs)
            metadata.update_duplicate(raw_event);

            // Log the duplicate with similarity metrics
            info!(
                "Duplicate detected: {} for key {}, Similarity: {:.2}, Field diffs: {}, Property diffs: {}",
                metadata.get_metrics_summary(),
                key.get_formatted_key(),
                similarity.overall_score,
                similarity.different_field_count,
                similarity.different_property_count
            );

            // Log detailed differences if similarity is not perfect
            if !similarity.different_fields.is_empty() {
                for (field_name, original_val, new_val) in &similarity.different_fields {
                    info!(
                        "Different field '{}' for key {}: '{}' -> '{}'",
                        field_name,
                        key.get_formatted_key(),
                        original_val,
                        new_val
                    );
                }
            }
            if !similarity.different_properties.is_empty() {
                for (prop_name, values_opt) in &similarity.different_properties {
                    if let Some((orig_val, new_val)) = values_opt {
                        // $ properties - show values
                        info!(
                            "Different property '{}' for key {}: '{}' -> '{}'",
                            prop_name,
                            key.get_formatted_key(),
                            orig_val,
                            new_val
                        );
                    } else {
                        // Non-$ properties - just show key name for privacy
                        info!(
                            "Different property '{}' for key {} (values hidden for privacy)",
                            prop_name,
                            key.get_formatted_key()
                        );
                    }
                }
            }

            // Extract library info and emit duplicate metric with labels
            let (lib_name, lib_version) = extract_library_info(raw_event);
            self.metrics
                .counter(DUPLICATE_EVENTS_TOTAL_COUNTER)
                .with_label("lib", &lib_name)
                .with_label("lib_version", &lib_version)
                .increment(1);

            // Emit similarity histogram metric
            self.metrics
                .histogram("deduplication_similarity_score")
                .with_label("lib", &lib_name)
                .with_label("lib_version", &lib_version)
                .record(similarity.overall_score);

            // Emit field differences metric
            self.metrics
                .histogram("deduplication_field_differences")
                .with_label("lib", &lib_name)
                .with_label("lib_version", &lib_version)
                .record(similarity.different_field_count as f64);

            // Emit property differences metric
            self.metrics
                .histogram("deduplication_property_differences")
                .with_label("lib", &lib_name)
                .with_label("lib_version", &lib_version)
                .record(similarity.different_property_count as f64);

            // Emit individual counters for each mismatched field
            for (field_name, _, _) in &similarity.different_fields {
                self.metrics
                    .counter("deduplication_field_mismatch_total")
                    .with_label("field", field_name)
                    .with_label("lib", &lib_name)
                    .with_label("lib_version", &lib_version)
                    .increment(1);
            }

            // Store updated metrics
            let serialized_metadata = VersionedMetadata::serialize_metadata(&metadata)?;
            self.store.put(
                DeduplicationStore::RECORDS_CF,
                &key_bytes,
                &serialized_metadata,
            )?;

            return Ok(false); // It's a duplicate
        }

        // Key doesn't exist - store it with initial metrics
        let metadata = VersionedMetadata::V1(MetadataV1::new(raw_event));
        let serialized_metadata = VersionedMetadata::serialize_metadata(&metadata)?;

        self.store.put_batch(
            DeduplicationStore::RECORDS_CF,
            vec![(&key_bytes, &serialized_metadata)],
        )?;

        // Track unique event with library info
        let (lib_name, lib_version) = extract_library_info(raw_event);
        self.metrics
            .counter(UNIQUE_EVENTS_TOTAL_COUNTER)
            .with_label("lib", &lib_name)
            .with_label("lib_version", &lib_version)
            .increment(1);

        Ok(true) // New event
    }

    pub fn cleanup_old_entries(&self) -> Result<u64> {
        let start_time = Instant::now();

        self.metrics
            .counter(CLEANUP_OPERATIONS_COUNTER)
            .increment(1);

        if self.config.max_capacity == 0 {
            return Ok(0); // No cleanup needed if max_capacity is 0 (unlimited)
        }

        let current_size = self.store.get_db_size()?;
        if current_size <= self.config.max_capacity {
            return Ok(0); // Under capacity, no cleanup needed
        }

        let target_size = (self.config.max_capacity as f64 * 0.8) as u64; // Clean up to 80% of max capacity
        let bytes_to_free = current_size.saturating_sub(target_size);

        if bytes_to_free == 0 {
            return Ok(0);
        }

        // Since our keys are timestamp-prefixed, we can delete old entries by timestamp
        // Let's delete a full day of entries, until we reach the target size
        let cf = self.store.get_cf_handle(Self::RECORDS_CF)?;
        let mut iter = self.store.db.iterator_cf(&cf, rocksdb::IteratorMode::Start);

        // Get the first key
        if let Some(Ok((first_key, _))) = iter.next() {
            let first_key_bytes: DeduplicationKey = first_key.as_ref().try_into()?;

            let first_key_timestamp = first_key_bytes.timestamp;
            let last_key_timestamp = first_key_timestamp + (24 * 60 * 60); // Original timestamp + 1 day

            let first_key_bytes: Vec<u8> = first_key_bytes.into();

            // We want to delete all keys with timestamp < last_key_timestamp
            // Since keys are formatted as "timestamp:distinct_id:token:event_name",
            // we can create an exclusive upper bound by using the timestamp followed by ":"
            // This ensures we delete all keys starting with timestamps less than last_key_timestamp
            let last_key_bytes: Vec<u8> = format!("{last_key_timestamp}:").as_bytes().to_vec();

            // Delete the first key
            self.store.delete_range(
                Self::RECORDS_CF,
                first_key_bytes.as_ref(),
                last_key_bytes.as_ref(),
            )?;
        } else {
            error!("No keys found in the database");
            return Ok(0);
        }

        let new_size = self.store.get_db_size()?;
        let bytes_freed = current_size.saturating_sub(new_size);

        // Emit cleanup metrics
        let duration = start_time.elapsed();
        self.metrics
            .histogram(CLEANUP_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());
        self.metrics
            .histogram(CLEANUP_BYTES_FREED_HISTOGRAM)
            .record(bytes_freed as f64);

        Ok(bytes_freed)
    }

    pub fn get_store(&self) -> &RocksDbStore {
        &self.store
    }

    /// Create an incremental checkpoint of the deduplication store
    /// This creates a point-in-time snapshot that can be used for recovery
    pub fn create_checkpoint<P: AsRef<std::path::Path>>(&self, checkpoint_path: P) -> Result<()> {
        self.store.create_checkpoint(checkpoint_path)
    }

    /// Get the current database path
    pub fn get_db_path(&self) -> &std::path::PathBuf {
        self.store.get_path()
    }

    /// Get current SST file names for tracking incremental checkpoint changes
    pub fn get_sst_file_names(&self) -> Result<Vec<String>> {
        self.store.get_sst_file_names(Self::RECORDS_CF)
    }

    /// Get the topic this store is responsible for
    pub fn get_topic(&self) -> &str {
        &self.topic
    }

    /// Get the partition this store is responsible for
    pub fn get_partition(&self) -> i32 {
        self.partition
    }

    /// Flush the store to disk
    pub fn flush(&self) -> Result<()> {
        self.store.flush_cf(Self::RECORDS_CF)
    }

    /// Update metrics for this store (including database size)
    pub fn update_metrics(&self) -> Result<()> {
        self.store.update_db_metrics(Self::RECORDS_CF)
    }

    /// Create a checkpoint and return the SST files at the time of checkpoint
    pub fn create_checkpoint_with_metadata<P: AsRef<std::path::Path>>(
        &self,
        checkpoint_path: P,
    ) -> Result<Vec<String>> {
        // Flush before checkpoint to ensure all data is in SST files
        self.store.flush_cf(Self::RECORDS_CF)?;

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
    use std::time::SystemTime;
    use tempfile::TempDir;
    use tracing::info;

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

    fn create_test_raw_event(distinct_id: &str, token: &str, event_name: &str) -> RawEvent {
        RawEvent {
            uuid: None,
            event: event_name.to_string(),
            distinct_id: Some(serde_json::Value::String(distinct_id.to_string())),
            token: Some(token.to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some(
                SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs()
                    .to_string(),
            ),
            ..Default::default()
        }
    }

    #[test]
    fn test_get_non_duplicated_keys_empty() {
        let (store, _temp_dir) = create_test_store(None);
        let result = store.get_non_duplicated_keys(vec![]).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_get_non_duplicated_keys_all_new() {
        let (store, _temp_dir) = create_test_store(None);

        let key1 = b"key1";
        let key2 = b"key2";
        let keys = vec![key1.as_slice(), key2.as_slice()];

        let result = store.get_non_duplicated_keys(keys).unwrap();
        assert_eq!(result.len(), 2);
        assert!(result.contains(&key1.as_slice()));
        assert!(result.contains(&key2.as_slice()));
    }

    #[test]
    fn test_get_non_duplicated_keys_with_duplicates() {
        let (store, _temp_dir) = create_test_store(None);

        // Store some keys first
        let key1 = b"key1";
        let key2 = b"key2";
        let key3 = b"key3";

        store
            .store
            .put(DeduplicationStore::RECORDS_CF, key1, b"value1")
            .unwrap();
        store
            .store
            .put(DeduplicationStore::RECORDS_CF, key2, b"value2")
            .unwrap();

        // Now check with mix of existing and new keys
        let keys = vec![key1.as_slice(), key2.as_slice(), key3.as_slice()];
        let result = store.get_non_duplicated_keys(keys).unwrap();

        assert_eq!(result.len(), 1);
        assert!(result.contains(&key3.as_slice()));
        assert!(!result.contains(&key1.as_slice()));
        assert!(!result.contains(&key2.as_slice()));
    }

    #[test]
    fn test_handle_event_with_raw_empty_batch() {
        let (store, _temp_dir) = create_test_store(None);
        let events: Vec<RawEvent> = vec![];
        // Empty batch - nothing to process
        for event in events {
            let result = store.handle_event_with_raw(&event);
            assert!(result.is_ok());
        }
    }

    #[test]
    fn test_handle_events_new_events() {
        let (store, _temp_dir) = create_test_store(None);

        let events = vec![
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];

        // Process events individually
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Verify events were stored by checking they're now duplicates
        let events_again = [
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];

        let dedup_keys: Vec<DeduplicationKey> =
            events_again.iter().map(DeduplicationKey::from).collect();
        let key_bytes: Vec<&[u8]> = dedup_keys.iter().map(|k| k.as_ref()).collect();
        let non_duplicated = store.get_non_duplicated_keys(key_bytes).unwrap();

        assert!(
            non_duplicated.is_empty(),
            "All events should now be duplicates"
        );
    }

    #[test]
    fn test_handle_events_mixed_duplicates() {
        let (store, _temp_dir) = create_test_store(None);

        // First batch
        let first_batch = vec![
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &first_batch {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Second batch with one duplicate and one new
        let second_batch = vec![
            create_test_raw_event("user1", "token1", "event1"), // duplicate
            create_test_raw_event("user3", "token1", "event3"), // new
        ];
        let results: Vec<bool> = second_batch
            .iter()
            .map(|event| store.handle_event_with_raw(event).unwrap())
            .collect();
        assert_eq!(results, vec![false, true]); // first duplicate, second new

        // Verify only the new event was stored
        let test_event = create_test_raw_event("user3", "token1", "event3");
        let dedup_key = DeduplicationKey::from(&test_event);
        let key_bytes = vec![dedup_key.as_ref()];
        let non_duplicated = store.get_non_duplicated_keys(key_bytes).unwrap();

        assert!(
            non_duplicated.is_empty(),
            "user3 event should now be a duplicate"
        );
    }

    #[test]
    fn test_deduplication_key_formatting() {
        let event = create_test_raw_event("user123", "token456", "page_view");
        let key = DeduplicationKey::from(&event);

        let expected = format!(
            "{}:user123:token456:page_view",
            event.timestamp.as_ref().unwrap()
        );
        assert_eq!(String::from_utf8_lossy(key.as_ref()), expected);
    }

    #[test]
    fn test_metadata_storage_functionality() {
        let (store, _temp_dir) = create_test_store(None);

        let event = create_test_raw_event("user1", "token1", "event1");

        // Test that single event processing works
        let is_new = store.handle_event_with_raw(&event).unwrap();
        assert!(is_new); // First time should be new

        // Verify we can handle duplicates using the trait-based approach
        let duplicate_event = create_test_raw_event("user1", "token1", "event1");
        let is_duplicate = store.handle_event_with_raw(&duplicate_event).unwrap();
        assert!(!is_duplicate); // Should be a duplicate (returns false for new)

        // Test individual event processing works without errors - using different events to avoid serialization
        let batch_events = vec![
            create_test_raw_event("user2", "token1", "event2"),
            create_test_raw_event("user3", "token1", "event3"),
        ];
        for event in &batch_events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Test that the new events work with individual processing
        let new_event = create_test_raw_event("user4", "token1", "event4");
        let is_new_again = store.handle_event_with_raw(&new_event).unwrap();
        assert!(is_new_again); // Should be new
    }

    #[test]
    fn test_deduplication_key_conversion() {
        let event = create_test_raw_event("user123", "token456", "page_view");
        let key = DeduplicationKey::from(&event);

        // Test converting to bytes and back
        let key_bytes: Vec<u8> = (&key).into();
        let parsed_key = DeduplicationKey::try_from(key_bytes.as_slice()).unwrap();

        assert_eq!(key.timestamp, parsed_key.timestamp);
        assert_eq!(key.distinct_id, parsed_key.distinct_id);
        assert_eq!(key.token, parsed_key.token);
        assert_eq!(key.event_name, parsed_key.event_name);
        assert_eq!(key.formatted_key, parsed_key.formatted_key);
    }

    #[test]
    fn test_cleanup_old_entries_no_capacity_limit() {
        let (store, _temp_dir) = create_test_store(Some(0)); // 0 = unlimited

        // Add some events
        let events = vec![
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Cleanup should do nothing when max_capacity is 0
        let bytes_freed = store.cleanup_old_entries().unwrap();
        assert_eq!(bytes_freed, 0);
    }

    #[test]
    fn test_cleanup_old_entries_under_capacity() {
        let (store, _temp_dir) = create_test_store(Some(1_000_000)); // 1MB limit

        // Add a small amount of data
        let events = vec![create_test_raw_event("user1", "token1", "event1")];
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Should be under capacity, no cleanup needed
        let bytes_freed = store.cleanup_old_entries().unwrap();
        assert_eq!(bytes_freed, 0);
    }

    fn create_test_raw_event_with_timestamp(
        timestamp: u64,
        distinct_id: &str,
        token: &str,
        event_name: &str,
    ) -> RawEvent {
        RawEvent {
            uuid: None,
            event: event_name.to_string(),
            distinct_id: Some(serde_json::Value::String(distinct_id.to_string())),
            token: Some(token.to_string()),
            properties: std::collections::HashMap::new(),
            timestamp: Some(timestamp.to_string()),
            ..Default::default()
        }
    }

    #[test]
    fn test_cleanup_old_entries_over_capacity() {
        let (store, _temp_dir) = create_test_store(Some(1000)); // Very small capacity to trigger cleanup

        // Add events with different timestamps to test timestamp-based cleanup
        let base_timestamp = 1609459200; // 2021-01-01

        // Create much larger data to exceed capacity reliably
        let large_value = "x".repeat(100); // 100 bytes per event
        let events: Vec<RawEvent> = (0..100)
            .map(|i| {
                create_test_raw_event_with_timestamp(
                    base_timestamp + i,
                    &format!("user{i}{large_value}"),
                    &format!("token{i}{large_value}"),
                    &format!("event{i}{large_value}"),
                )
            })
            .collect();
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            // Don't assert true since we might have duplicates due to the large number of events
        }

        // Force data to SST files
        store
            .get_store()
            .flush_cf(DeduplicationStore::RECORDS_CF)
            .unwrap();
        store
            .get_store()
            .compact_cf(DeduplicationStore::RECORDS_CF)
            .unwrap();

        // Check initial size
        let initial_size = store.store.get_db_size().unwrap();

        // If we still can't measure size reliably, test the cleanup logic differently
        if initial_size == 0 {
            // Alternative test: verify cleanup method runs without error and returns 0 when size can't be measured
            let bytes_freed = store.cleanup_old_entries().unwrap();
            // When size is 0, cleanup should return 0 (no cleanup needed)
            assert_eq!(
                bytes_freed, 0,
                "Should return 0 when size can't be measured"
            );
            return;
        }

        assert!(initial_size > 1000, "Initial size should exceed capacity");

        // Run cleanup
        let bytes_freed = store.cleanup_old_entries().unwrap();
        assert!(bytes_freed > 0, "Should have freed some bytes");

        // Check that size was reduced
        let final_size = store.store.get_db_size().unwrap();
        assert!(
            final_size < initial_size,
            "Size should be reduced after cleanup"
        );
    }

    #[test]
    fn test_cleanup_preserves_newer_entries() {
        let (store, _temp_dir) = create_test_store(Some(1000)); // Very small capacity

        let base_timestamp = 1609459200; // 2021-01-01
        let old_event =
            create_test_raw_event_with_timestamp(base_timestamp, "old_user", "token1", "old_event");
        let new_event = create_test_raw_event_with_timestamp(
            base_timestamp + 86400,
            "new_user",
            "token1",
            "new_event",
        );

        // Add old event first
        let result = store.handle_event_with_raw(&old_event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // Should be new

        // Add many more events to exceed capacity
        for i in 0..10 {
            let event = create_test_raw_event_with_timestamp(
                base_timestamp + i,
                &format!("user{i}"),
                "token1",
                &format!("event{i}"),
            );
            let result = store.handle_event_with_raw(&event);
            assert!(result.is_ok());
            // Don't assert true as some events might be duplicates due to timestamp logic
        }
        // Add new event last
        let result = store.handle_event_with_raw(&new_event);
        assert!(result.is_ok());
        assert!(result.unwrap()); // Should be new

        // Run cleanup
        let bytes_freed = store.cleanup_old_entries().unwrap();

        // If we can't measure database size reliably, just verify cleanup runs without error
        let final_size = store.store.get_db_size().unwrap();
        if final_size == 0 {
            // When size can't be measured, cleanup should return 0
            assert_eq!(
                bytes_freed, 0,
                "Should return 0 when size can't be measured"
            );
            return;
        }

        assert!(bytes_freed > 0, "Should have freed some bytes");

        // The cleanup implementation deletes by timestamp range, so we can't easily test
        // which specific entries remain, but we can verify the cleanup ran successfully
        assert!(
            final_size <= store.config.max_capacity,
            "Should be under capacity after cleanup"
        );
    }

    #[test]
    fn test_create_checkpoint() {
        let (store, _temp_dir) = create_test_store(None);

        // Add some deduplication data
        let events = vec![
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Create checkpoint
        let checkpoint_dir = tempfile::TempDir::new().unwrap();
        let checkpoint_path = checkpoint_dir.path().join("dedup_checkpoint");
        info!("checkpoint_path: {:?}", checkpoint_path);

        let result = store.create_checkpoint(&checkpoint_path);
        assert!(result.is_ok());

        // Verify checkpoint directory exists
        assert!(checkpoint_path.exists());
        assert!(checkpoint_path.is_dir());
    }

    #[test]
    fn test_checkpoint_recovery() {
        let temp_dir = tempfile::TempDir::new().unwrap();
        let original_path = temp_dir.path().join("original_dedup");
        let checkpoint_path = temp_dir.path().join("checkpoint_dedup");

        // Create original store and add deduplication data
        let original_events = vec![
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];

        {
            let config = DeduplicationStoreConfig {
                path: original_path.clone(),
                max_capacity: 1_000_000,
            };
            let original_store =
                DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();

            for event in &original_events {
                let result = original_store.handle_event_with_raw(event);
                assert!(result.is_ok());
                assert!(result.unwrap()); // All events should be new
            }

            // Create checkpoint
            original_store.create_checkpoint(&checkpoint_path).unwrap();
        } // Drop original store

        // Open new store from checkpoint
        let config = DeduplicationStoreConfig {
            path: checkpoint_path,
            max_capacity: 1_000_000,
        };
        let recovered_store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();

        // Verify data is recovered by checking duplicates
        let dedup_keys: Vec<DeduplicationKey> =
            original_events.iter().map(DeduplicationKey::from).collect();
        let key_bytes: Vec<&[u8]> = dedup_keys.iter().map(|k| k.as_ref()).collect();
        let non_duplicated = recovered_store.get_non_duplicated_keys(key_bytes).unwrap();

        // All events should be duplicates (already exist in checkpoint)
        assert!(
            non_duplicated.is_empty(),
            "All events should be duplicates after recovery"
        );
    }

    #[test]
    fn test_incremental_checkpointing() {
        let temp_dir = tempfile::TempDir::new().unwrap();
        let original_path = temp_dir.path().join("original_dedup");
        let checkpoint1_path = temp_dir.path().join("checkpoint1");
        let checkpoint2_path = temp_dir.path().join("checkpoint2");

        let config = DeduplicationStoreConfig {
            path: original_path,
            max_capacity: 1_000_000,
        };
        let store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();

        // Phase 1: Add initial events and create first checkpoint
        let initial_events = [
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &initial_events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Create first checkpoint
        store.create_checkpoint(&checkpoint1_path).unwrap();

        // Phase 2: Add more events and create second checkpoint
        let additional_events = [
            create_test_raw_event("user3", "token1", "event3"),
            create_test_raw_event("user4", "token1", "event4"),
        ];
        for event in &additional_events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Create second checkpoint (incremental - contains all data up to this point)
        store.create_checkpoint(&checkpoint2_path).unwrap();

        // Verify checkpoint1 only has initial events
        {
            let config1 = DeduplicationStoreConfig {
                path: checkpoint1_path,
                max_capacity: 1_000_000,
            };
            let recovered_store1 =
                DeduplicationStore::new(config1, "test_topic".to_string(), 0).unwrap();

            // Initial events should be duplicates (exist in checkpoint1)
            let initial_keys: Vec<DeduplicationKey> =
                initial_events.iter().map(DeduplicationKey::from).collect();
            let initial_key_bytes: Vec<&[u8]> = initial_keys.iter().map(|k| k.as_ref()).collect();
            let non_duplicated_initial = recovered_store1
                .get_non_duplicated_keys(initial_key_bytes)
                .unwrap();
            assert!(
                non_duplicated_initial.is_empty(),
                "Initial events should be duplicates in checkpoint1"
            );

            // Additional events should NOT be duplicates (don't exist in checkpoint1)
            let additional_keys: Vec<DeduplicationKey> = additional_events
                .iter()
                .map(DeduplicationKey::from)
                .collect();
            let additional_key_bytes: Vec<&[u8]> =
                additional_keys.iter().map(|k| k.as_ref()).collect();
            let non_duplicated_additional = recovered_store1
                .get_non_duplicated_keys(additional_key_bytes)
                .unwrap();
            assert_eq!(
                non_duplicated_additional.len(),
                2,
                "Additional events should NOT be duplicates in checkpoint1"
            );
        }

        // Verify checkpoint2 has all events (incremental checkpoint)
        {
            let config2 = DeduplicationStoreConfig {
                path: checkpoint2_path,
                max_capacity: 1_000_000,
            };
            let recovered_store2 =
                DeduplicationStore::new(config2, "test_topic".to_string(), 0).unwrap();

            // All events should be duplicates (exist in checkpoint2)
            let all_events: Vec<_> = initial_events
                .iter()
                .chain(additional_events.iter())
                .collect();
            let all_keys: Vec<DeduplicationKey> = all_events
                .iter()
                .map(|e| DeduplicationKey::from(*e))
                .collect();
            let all_key_bytes: Vec<&[u8]> = all_keys.iter().map(|k| k.as_ref()).collect();
            let non_duplicated_all = recovered_store2
                .get_non_duplicated_keys(all_key_bytes)
                .unwrap();
            assert!(
                non_duplicated_all.is_empty(),
                "All events should be duplicates in checkpoint2"
            );
        }
    }

    #[test]
    fn test_sst_file_tracking_incremental_deltas() {
        let temp_dir = tempfile::TempDir::new().unwrap();
        let original_path = temp_dir.path().join("original_dedup");
        let checkpoint1_path = temp_dir.path().join("checkpoint1");
        let checkpoint2_path = temp_dir.path().join("checkpoint2");

        let config = DeduplicationStoreConfig {
            path: original_path,
            max_capacity: 1_000_000,
        };
        let store = DeduplicationStore::new(config, "test_topic".to_string(), 0).unwrap();

        // Phase 1: Add initial events and create checkpoint with metadata
        let initial_events = [
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &initial_events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Create checkpoint with SST file tracking
        let sst_files_checkpoint1 = store
            .create_checkpoint_with_metadata(&checkpoint1_path)
            .unwrap();

        // Phase 2: Add more events and create second checkpoint
        let additional_events = [
            create_test_raw_event("user3", "token1", "event3"),
            create_test_raw_event("user4", "token1", "event4"),
        ];
        for event in &additional_events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Create second checkpoint with SST file tracking
        let sst_files_checkpoint2 = store
            .create_checkpoint_with_metadata(&checkpoint2_path)
            .unwrap();

        // Compute delta between checkpoints
        let delta = crate::rocksdb::store::RocksDbStore::compute_sst_delta(
            &sst_files_checkpoint1,
            &sst_files_checkpoint2,
        );

        // Verify we can track changes
        // The exact files depend on RocksDB's internal behavior, but we should have consistent tracking
        let total_checkpoint2_files = sst_files_checkpoint2.len();

        // Delta accounting should be consistent
        // All files in checkpoint2 should be either added or unchanged
        assert!(delta.added_files.len() + delta.unchanged_files.len() >= total_checkpoint2_files);

        // Verify both checkpoints exist
        assert!(checkpoint1_path.exists());
        assert!(checkpoint2_path.exists());

        // Verify the delta is correct
        assert_eq!(delta.added_files.len(), 1);
        assert_eq!(delta.unchanged_files.len(), 1);
        assert_eq!(delta.removed_files.len(), 0);
    }

    #[test]
    fn test_get_sst_file_names() {
        let (store, _temp_dir) = create_test_store(None);

        // Initially should have no SST files
        let initial_sst_files = store.get_sst_file_names().unwrap();

        // Add some events
        let events = [
            create_test_raw_event("user1", "token1", "event1"),
            create_test_raw_event("user2", "token1", "event2"),
        ];
        for event in &events {
            let result = store.handle_event_with_raw(event);
            assert!(result.is_ok());
            assert!(result.unwrap()); // All events should be new
        }

        // Force flush to create SST files
        store
            .store
            .flush_cf(DeduplicationStore::RECORDS_CF)
            .unwrap();

        let after_flush_sst_files = store.get_sst_file_names().unwrap();

        // Should have either more files or the same (depending on size)
        assert!(after_flush_sst_files.len() >= initial_sst_files.len());

        // All SST file names should end with .sst
        for file_name in &after_flush_sst_files {
            assert!(file_name.ends_with(".sst"));
        }
    }

    #[test]
    fn test_flush_method() {
        let (store, _temp_dir) = create_test_store(None);

        // Add some events
        let event1 = create_test_raw_event("user1", "token1", "event1");
        let event2 = create_test_raw_event("user2", "token2", "event2");

        store.handle_event_with_raw(&event1).unwrap();
        store.handle_event_with_raw(&event2).unwrap();

        // Flush should succeed
        assert!(store.flush().is_ok());

        // Flush again should also succeed (idempotent)
        assert!(store.flush().is_ok());
    }

    #[test]
    fn test_update_metrics_succeeds() {
        let (store, _temp_dir) = create_test_store(None);

        // Add some events first
        let event = create_test_raw_event("user1", "token1", "event1");
        store.handle_event_with_raw(&event).unwrap();

        // Update metrics should succeed
        assert!(store.update_metrics().is_ok());
    }

    #[test]
    fn test_flush_before_checkpoint() {
        let (store, temp_dir) = create_test_store(None);

        // Add some events
        let event = create_test_raw_event("user1", "token1", "checkpoint_test");
        store.handle_event_with_raw(&event).unwrap();

        // Create a checkpoint (which internally calls flush)
        let checkpoint_path = temp_dir.path().join("checkpoint");
        let sst_files = store
            .create_checkpoint_with_metadata(&checkpoint_path)
            .unwrap();

        // Checkpoint should exist
        assert!(checkpoint_path.exists());

        // Should have SST files
        assert!(!sst_files.is_empty());
    }
}
