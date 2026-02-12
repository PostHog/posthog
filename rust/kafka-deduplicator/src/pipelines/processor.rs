//! Shared processor utilities for deduplication pipelines.
//!
//! This module provides common functionality used across different pipeline
//! processors to reduce code duplication.

use std::time::Instant;

use anyhow::Result;
use tracing::warn;

use crate::metrics::MetricsHelper;
use crate::metrics_const::{
    DEDUPLICATION_RESULT_COUNTER, MESSAGES_DROPPED_NO_STORE, ROCKSDB_MULTI_GET_DURATION_MS,
    ROCKSDB_PUT_BATCH_DURATION_MS,
};
use crate::pipelines::EventSimilarity;
use crate::store::deduplication_store::{DeduplicationStore, TimestampBatchEntry};
use crate::store_manager::{StoreError, StoreManager};

/// Reason why an event was identified as a duplicate or potential duplicate.
#[derive(strum_macros::Display, Debug, Copy, Clone, PartialEq)]
pub enum DuplicateReason {
    /// Exact same event (all fields match including UUID)
    SameEvent,
    /// Same dedup key with same UUID (retry of original)
    SameUuid,
    /// Same dedup key, only UUID differs (confirmed duplicate)
    OnlyUuidDifferent,
    /// Same dedup key but content differs beyond just UUID (potential duplicate)
    ContentDiffers,
}

/// Metadata about a duplicate event detection.
#[derive(Debug)]
pub struct DuplicateInfo<E> {
    /// Why this is considered a duplicate
    pub reason: DuplicateReason,
    /// Similarity between the new event and the original
    pub similarity: EventSimilarity,
    /// The original event that was stored
    pub original_event: E,
    /// Number of unique UUIDs seen for this dedup key (after update)
    pub unique_uuids_count: usize,
}

/// Deduplication result shared across all pipelines.
///
/// This type captures the outcome of deduplication checks:
/// - `New`: First occurrence of this event
/// - `ConfirmedDuplicate`: Definitely a duplicate (same UUID or identical event)
/// - `PotentialDuplicate`: Same dedup key but different content
/// - `Skipped`: Processing was skipped due to an error
#[derive(Debug)]
pub enum DeduplicationResult<E> {
    /// First time seeing this event
    New,
    /// Confirmed duplicate with full info
    ConfirmedDuplicate(DuplicateInfo<E>),
    /// Same dedup key but different content (not confirmed as duplicate)
    PotentialDuplicate(DuplicateInfo<E>),
    /// Processing was skipped (error)
    Skipped,
}

impl<E> DeduplicationResult<E> {
    /// Returns true only for confirmed duplicates.
    /// Potential duplicates are NOT treated as duplicates for filtering purposes.
    pub fn is_duplicate(&self) -> bool {
        matches!(self, DeduplicationResult::ConfirmedDuplicate(_))
    }

    /// Get the similarity info if this is a duplicate.
    pub fn get_similarity(&self) -> Option<&EventSimilarity> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(info) => Some(&info.similarity),
            DeduplicationResult::PotentialDuplicate(info) => Some(&info.similarity),
            _ => None,
        }
    }

    /// Get the original event if this is a duplicate.
    pub fn get_original_event(&self) -> Option<&E> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(info) => Some(&info.original_event),
            DeduplicationResult::PotentialDuplicate(info) => Some(&info.original_event),
            _ => None,
        }
    }

    /// Get the duplicate reason if this is a confirmed duplicate.
    pub fn get_reason(&self) -> Option<DuplicateReason> {
        match self {
            DeduplicationResult::ConfirmedDuplicate(info) => Some(info.reason),
            _ => None,
        }
    }
}

/// Labels for deduplication result metrics.
pub struct DeduplicationResultLabels {
    pub result_type: &'static str,
    pub reason: Option<&'static str>,
}

/// Get metric labels for a deduplication result.
pub fn get_result_labels<E>(result: &DeduplicationResult<E>) -> DeduplicationResultLabels {
    match result {
        DeduplicationResult::New => DeduplicationResultLabels {
            result_type: "new",
            reason: None,
        },
        DeduplicationResult::ConfirmedDuplicate(info) => DeduplicationResultLabels {
            result_type: "confirmed_duplicate",
            reason: Some(match info.reason {
                DuplicateReason::SameEvent => "same_event",
                DuplicateReason::SameUuid => "same_uuid",
                DuplicateReason::OnlyUuidDifferent => "only_uuid_different",
                DuplicateReason::ContentDiffers => "content_differs",
            }),
        },
        DeduplicationResult::PotentialDuplicate(info) => DeduplicationResultLabels {
            result_type: "potential_duplicate",
            reason: Some(match info.reason {
                DuplicateReason::SameEvent => "same_event",
                DuplicateReason::SameUuid => "same_uuid",
                DuplicateReason::OnlyUuidDifferent => "only_uuid_different",
                DuplicateReason::ContentDiffers => "content_differs",
            }),
        },
        DeduplicationResult::Skipped => DeduplicationResultLabels {
            result_type: "skipped",
            reason: None,
        },
    }
}

/// Emit deduplication result metrics.
///
/// This is the shared implementation used by all pipeline processors.
pub fn emit_deduplication_result_metrics(
    topic: &str,
    partition: i32,
    pipeline: &str,
    labels: DeduplicationResultLabels,
) {
    let mut counter = MetricsHelper::with_partition(topic, partition)
        .with_label("service", "kafka-deduplicator")
        .with_label("pipeline", pipeline)
        .counter(DEDUPLICATION_RESULT_COUNTER)
        .with_label("result_type", labels.result_type);

    if let Some(reason) = labels.reason {
        counter = counter.with_label("reason", reason);
    }

    counter.increment(1);
}

/// Result of attempting to get a store for a partition.
pub enum StoreResult {
    /// Store was found and is ready to use
    Found(DeduplicationStore),
    /// Store was not found (partition likely revoked) - messages should be dropped
    NotFound,
}

/// Get a store for a partition, handling the "not found" case gracefully.
///
/// When a partition is revoked during rebalance, messages may still arrive due to
/// rdkafka buffering. This function handles that case by logging a warning and
/// emitting a metric, returning `StoreResult::NotFound` to indicate messages
/// should be dropped.
pub fn get_store_or_drop(
    store_manager: &StoreManager,
    topic: &str,
    partition: i32,
    message_count: usize,
) -> Result<StoreResult> {
    match store_manager.get_store(topic, partition) {
        Ok(store) => Ok(StoreResult::Found(store)),
        Err(StoreError::NotFound {
            topic: t,
            partition: p,
        }) => {
            warn!(
                topic = %t,
                partition = p,
                message_count = message_count,
                "No store for partition - dropping messages (expected during rebalance)"
            );
            metrics::counter!(
                MESSAGES_DROPPED_NO_STORE,
                "topic" => t.clone(),
                "partition" => p.to_string(),
            )
            .increment(message_count as u64);
            Ok(StoreResult::NotFound)
        }
        Err(StoreError::Other(e)) => Err(e),
    }
}

/// Batch read from RocksDB with metrics.
///
/// Reads multiple keys from the timestamp column family and records the duration.
pub fn batch_read_timestamp_records(
    store: &DeduplicationStore,
    keys: Vec<&[u8]>,
) -> Result<Vec<Option<Vec<u8>>>> {
    let start = Instant::now();
    let results = store.multi_get_timestamp_records(keys)?;
    let duration = start.elapsed();
    metrics::histogram!(ROCKSDB_MULTI_GET_DURATION_MS, "cf" => "timestamp")
        .record(duration.as_millis() as f64);
    Ok(results)
}

/// Batch write to RocksDB with metrics.
///
/// Writes multiple key-value pairs to the timestamp column family and records the duration.
pub fn batch_write_timestamp_records(
    store: &DeduplicationStore,
    writes: &[(Vec<u8>, Vec<u8>)],
) -> Result<()> {
    if writes.is_empty() {
        return Ok(());
    }

    let entries: Vec<TimestampBatchEntry> = writes
        .iter()
        .map(|(key, value)| TimestampBatchEntry {
            key: key.as_slice(),
            value: value.as_slice(),
        })
        .collect();

    let start = Instant::now();
    store.put_timestamp_records_batch(entries)?;
    let duration = start.elapsed();
    metrics::histogram!(ROCKSDB_PUT_BATCH_DURATION_MS, "cf" => "timestamp")
        .record(duration.as_millis() as f64);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::DeduplicationStoreConfig;
    use crate::test_utils::create_test_tracker;
    use std::sync::Arc;
    use tempfile::TempDir;

    fn create_test_store_manager() -> (Arc<StoreManager>, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let manager = Arc::new(StoreManager::new(config, create_test_tracker()));
        (manager, temp_dir)
    }

    #[tokio::test]
    async fn test_get_store_or_drop_found() {
        let (manager, _temp_dir) = create_test_store_manager();

        // Create store first
        manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let result = get_store_or_drop(&manager, "test-topic", 0, 10).unwrap();
        assert!(matches!(result, StoreResult::Found(_)));
    }

    #[tokio::test]
    async fn test_get_store_or_drop_not_found() {
        let (manager, _temp_dir) = create_test_store_manager();

        // Don't create store - simulates revoked partition
        let result = get_store_or_drop(&manager, "test-topic", 0, 10).unwrap();
        assert!(matches!(result, StoreResult::NotFound));
    }

    #[tokio::test]
    async fn test_batch_read_write_roundtrip() {
        let (manager, _temp_dir) = create_test_store_manager();

        manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let store = manager.get_store("test-topic", 0).unwrap();

        // Write some records
        let writes = vec![
            (b"key1".to_vec(), b"value1".to_vec()),
            (b"key2".to_vec(), b"value2".to_vec()),
        ];
        batch_write_timestamp_records(&store, &writes).unwrap();

        // Read them back
        let keys: Vec<&[u8]> = vec![b"key1", b"key2", b"key3"];
        let results = batch_read_timestamp_records(&store, keys).unwrap();

        assert_eq!(results.len(), 3);
        assert_eq!(results[0], Some(b"value1".to_vec()));
        assert_eq!(results[1], Some(b"value2".to_vec()));
        assert_eq!(results[2], None); // key3 doesn't exist
    }

    #[test]
    fn test_batch_write_empty() {
        // Should not panic on empty writes
        let temp_dir = TempDir::new().unwrap();
        let config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };
        let store = DeduplicationStore::new(config, "test-topic".to_string(), 0).unwrap();

        let result = batch_write_timestamp_records(&store, &[]);
        assert!(result.is_ok());
    }
}
