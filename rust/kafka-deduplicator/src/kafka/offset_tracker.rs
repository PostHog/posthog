//! Offset Tracker - Tracks the latest processed offset per partition
//!
//! This component provides thread-safe offset tracking to ensure we only commit
//! offsets for batches that have been successfully processed. This is in contrast
//! to the previous approach of committing offsets immediately after receiving them.
//!
//! It also provides sequential batch IDs per partition to ensure ordering.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use dashmap::DashMap;
use thiserror::Error;
use tracing::{debug, info, warn};

use crate::kafka::metrics_consts::OFFSET_TRACKER_OUT_OF_ORDER_BATCH;
use crate::kafka::types::Partition;

/// Errors that can occur when retrieving committable offsets
#[derive(Error, Debug)]
pub enum OffsetTrackerError {
    /// A rebalance is currently in progress - commits should be skipped
    #[error("Rebalance in progress - offset commits should be skipped")]
    RebalanceInProgress,
}

/// State tracked per partition
struct PartitionState {
    /// The next offset to consume (highest processed + 1)
    processed_offset: i64,
    /// The last batch ID that was processed (for ordering verification)
    last_processed_batch_id: u64,
}

/// Thread-safe tracker for processed offsets per partition
///
/// This is used to track the highest offset that has been successfully processed
/// for each partition. The consumer periodically queries this tracker to get
/// offsets that are safe to commit.
///
/// It also assigns sequential batch IDs to ensure ordering within partitions.
pub struct OffsetTracker {
    /// Map of partition to state (offset + last batch ID)
    partition_state: DashMap<Partition, PartitionState>,
    /// Global counter for assigning batch IDs (unique across all partitions)
    next_batch_id: AtomicU64,
    /// Flag indicating whether a rebalance is in progress
    /// When true, offset commits should be skipped to avoid committing during rebalancing
    rebalancing: AtomicBool,
}

impl Default for OffsetTracker {
    fn default() -> Self {
        Self::new()
    }
}

impl OffsetTracker {
    pub fn new() -> Self {
        Self {
            partition_state: DashMap::new(),
            next_batch_id: AtomicU64::new(1), // Start at 1 so 0 can mean "no batch"
            rebalancing: AtomicBool::new(false),
        }
    }

    /// Set the rebalancing flag to prevent offset commits during rebalancing
    ///
    /// This should be called at the start of a rebalance (before any partition changes)
    /// and cleared after the rebalance is complete.
    pub fn set_rebalancing(&self, rebalancing: bool) {
        let was_rebalancing = self.rebalancing.swap(rebalancing, Ordering::SeqCst);
        if was_rebalancing != rebalancing {
            info!(
                rebalancing = rebalancing,
                "Offset tracker rebalancing state changed"
            );
        }
    }

    /// Check if a rebalance is currently in progress
    pub fn is_rebalancing(&self) -> bool {
        self.rebalancing.load(Ordering::SeqCst)
    }

    /// Assign a new batch ID for a partition.
    ///
    /// Batch IDs are globally unique and monotonically increasing. They're used
    /// to verify ordering when marking batches as processed.
    pub fn assign_batch_id(&self) -> u64 {
        self.next_batch_id.fetch_add(1, Ordering::SeqCst)
    }

    /// Mark a batch as processed.
    ///
    /// The offset should be `last_offset + 1` (the next offset to consume).
    /// The batch_id must be greater than the last processed batch_id for this
    /// partition to ensure ordering. If a batch is processed out of order,
    /// a warning is logged and a metric is emitted, but the offset is still
    /// updated if it advances.
    pub fn mark_processed(&self, partition: &Partition, batch_id: u64, next_offset: i64) {
        self.partition_state
            .entry(partition.clone())
            .and_modify(|state| {
                // Verify ordering
                if batch_id <= state.last_processed_batch_id {
                    warn!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        batch_id = batch_id,
                        last_batch_id = state.last_processed_batch_id,
                        "Batch processed out of order"
                    );
                    // Emit metric for out-of-order batch processing
                    metrics::counter!(
                        OFFSET_TRACKER_OUT_OF_ORDER_BATCH,
                        "topic" => partition.topic().to_string(),
                        "partition" => partition.partition_number().to_string()
                    )
                    .increment(1);
                }

                // Only advance offset, never go backwards
                if next_offset > state.processed_offset {
                    debug!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        batch_id = batch_id,
                        previous_offset = state.processed_offset,
                        new_offset = next_offset,
                        "Advancing processed offset"
                    );
                    state.processed_offset = next_offset;
                }

                // Always update last batch ID to track ordering
                if batch_id > state.last_processed_batch_id {
                    state.last_processed_batch_id = batch_id;
                }
            })
            .or_insert_with(|| {
                debug!(
                    topic = partition.topic(),
                    partition = partition.partition_number(),
                    batch_id = batch_id,
                    offset = next_offset,
                    "Initializing partition state"
                );
                PartitionState {
                    processed_offset: next_offset,
                    last_processed_batch_id: batch_id,
                }
            });
    }

    /// Get all offsets ready for commit (thread-safe snapshot)
    ///
    /// Returns a map of partition to next offset to consume. These offsets
    /// can be safely committed to Kafka as they represent successfully
    /// processed batches.
    ///
    /// # Errors
    ///
    /// Returns `OffsetTrackerError::RebalanceInProgress` if a rebalance is currently
    /// in progress. Callers should skip committing offsets in this case.
    pub fn get_committable_offsets(&self) -> Result<HashMap<Partition, i64>, OffsetTrackerError> {
        // Check rebalancing flag first - if true, return error to prevent commits
        if self.rebalancing.load(Ordering::SeqCst) {
            return Err(OffsetTrackerError::RebalanceInProgress);
        }

        Ok(self
            .partition_state
            .iter()
            .map(|entry| (entry.key().clone(), entry.value().processed_offset))
            .collect())
    }

    /// Get the current offset for a specific partition
    pub fn get_partition_offset(&self, partition: &Partition) -> Option<i64> {
        self.partition_state
            .get(partition)
            .map(|r| r.value().processed_offset)
    }

    /// Clear offset tracking for a partition (during revocation)
    ///
    /// Called when a partition is revoked to clean up state. The offset
    /// should have been committed before calling this.
    pub fn clear_partition(&self, partition: &Partition) {
        if self.partition_state.remove(partition).is_some() {
            debug!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                "Cleared offset tracking for revoked partition"
            );
        }
    }

    /// Clear all partitions (during shutdown)
    pub fn clear_all(&self) {
        self.partition_state.clear();
    }

    /// Get the number of partitions being tracked
    pub fn partition_count(&self) -> usize {
        self.partition_state.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_partition(num: i32) -> Partition {
        Partition::new("test-topic".to_string(), num)
    }

    #[test]
    fn test_assign_batch_id_is_sequential() {
        let tracker = OffsetTracker::new();

        let id1 = tracker.assign_batch_id();
        let id2 = tracker.assign_batch_id();
        let id3 = tracker.assign_batch_id();

        assert_eq!(id1, 1);
        assert_eq!(id2, 2);
        assert_eq!(id3, 3);
    }

    #[test]
    fn test_mark_processed_initializes_offset() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id, 100);

        assert_eq!(tracker.get_partition_offset(&partition), Some(100));
    }

    #[test]
    fn test_mark_processed_advances_offset() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);

        let batch_id1 = tracker.assign_batch_id();
        let batch_id2 = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id1, 100);
        tracker.mark_processed(&partition, batch_id2, 150);

        assert_eq!(tracker.get_partition_offset(&partition), Some(150));
    }

    #[test]
    fn test_mark_processed_never_goes_backwards() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);

        let batch_id1 = tracker.assign_batch_id();
        let batch_id2 = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id1, 100);
        tracker.mark_processed(&partition, batch_id2, 50); // Try to go backwards

        // Should still be at 100
        assert_eq!(tracker.get_partition_offset(&partition), Some(100));
    }

    #[test]
    fn test_multiple_partitions() {
        let tracker = OffsetTracker::new();
        let p0 = test_partition(0);
        let p1 = test_partition(1);
        let p2 = test_partition(2);

        let batch_id1 = tracker.assign_batch_id();
        let batch_id2 = tracker.assign_batch_id();
        let batch_id3 = tracker.assign_batch_id();

        tracker.mark_processed(&p0, batch_id1, 100);
        tracker.mark_processed(&p1, batch_id2, 200);
        tracker.mark_processed(&p2, batch_id3, 300);

        let offsets = tracker.get_committable_offsets().unwrap();

        assert_eq!(offsets.len(), 3);
        assert_eq!(offsets.get(&p0), Some(&100));
        assert_eq!(offsets.get(&p1), Some(&200));
        assert_eq!(offsets.get(&p2), Some(&300));
    }

    #[test]
    fn test_clear_partition() {
        let tracker = OffsetTracker::new();
        let p0 = test_partition(0);
        let p1 = test_partition(1);

        let batch_id1 = tracker.assign_batch_id();
        let batch_id2 = tracker.assign_batch_id();

        tracker.mark_processed(&p0, batch_id1, 100);
        tracker.mark_processed(&p1, batch_id2, 200);

        tracker.clear_partition(&p0);

        assert_eq!(tracker.get_partition_offset(&p0), None);
        assert_eq!(tracker.get_partition_offset(&p1), Some(200));
        assert_eq!(tracker.partition_count(), 1);
    }

    #[test]
    fn test_clear_all() {
        let tracker = OffsetTracker::new();

        let batch_id1 = tracker.assign_batch_id();
        let batch_id2 = tracker.assign_batch_id();
        let batch_id3 = tracker.assign_batch_id();

        tracker.mark_processed(&test_partition(0), batch_id1, 100);
        tracker.mark_processed(&test_partition(1), batch_id2, 200);
        tracker.mark_processed(&test_partition(2), batch_id3, 300);

        assert_eq!(tracker.partition_count(), 3);

        tracker.clear_all();

        assert_eq!(tracker.partition_count(), 0);
    }

    #[test]
    fn test_concurrent_updates_same_partition() {
        use std::sync::Arc;
        use std::thread;

        let tracker = Arc::new(OffsetTracker::new());
        let partition = test_partition(0);

        // Pre-assign batch IDs so they're sequential
        let batch_ids: Vec<u64> = (0..10).map(|_| tracker.assign_batch_id()).collect();

        let mut handles = vec![];

        // Spawn multiple threads that update the same partition
        for (i, batch_id) in batch_ids.into_iter().enumerate() {
            let tracker_clone = tracker.clone();
            let partition_clone = partition.clone();
            let offset = ((i + 1) * 100) as i64; // 100, 200, 300, ...

            handles.push(thread::spawn(move || {
                tracker_clone.mark_processed(&partition_clone, batch_id, offset);
            }));
        }

        for handle in handles {
            handle.join().unwrap();
        }

        // The highest offset should win (1000)
        assert_eq!(tracker.get_partition_offset(&partition), Some(1000));
    }

    #[test]
    fn test_concurrent_different_partitions() {
        use std::sync::Arc;
        use std::thread;

        let tracker = Arc::new(OffsetTracker::new());

        // Pre-assign batch IDs
        let batch_ids: Vec<u64> = (0..10).map(|_| tracker.assign_batch_id()).collect();

        let mut handles = vec![];

        // Spawn multiple threads, each updating a different partition
        for (i, batch_id) in batch_ids.into_iter().enumerate() {
            let tracker_clone = tracker.clone();
            let partition = test_partition(i as i32);
            let offset = (i as i64 + 1) * 100;

            handles.push(thread::spawn(move || {
                tracker_clone.mark_processed(&partition, batch_id, offset);
            }));
        }

        for handle in handles {
            handle.join().unwrap();
        }

        let offsets = tracker.get_committable_offsets().unwrap();
        assert_eq!(offsets.len(), 10);

        for i in 0..10 {
            let partition = test_partition(i);
            let expected = (i as i64 + 1) * 100;
            assert_eq!(offsets.get(&partition), Some(&expected));
        }
    }

    #[test]
    fn test_out_of_order_batch_processing() {
        // This tests the scenario where batches complete out of order
        // (e.g., batch 2 finishes before batch 1)
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);

        let batch_id1 = tracker.assign_batch_id(); // 1
        let batch_id2 = tracker.assign_batch_id(); // 2

        // Batch 2 completes first with higher offset
        tracker.mark_processed(&partition, batch_id2, 200);
        assert_eq!(tracker.get_partition_offset(&partition), Some(200));

        // Batch 1 completes later with lower offset - should not regress
        tracker.mark_processed(&partition, batch_id1, 100);
        assert_eq!(tracker.get_partition_offset(&partition), Some(200));
    }

    #[test]
    fn test_rebalancing_flag() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        // Initially not rebalancing
        assert!(!tracker.is_rebalancing());

        // Mark some offsets
        tracker.mark_processed(&partition, batch_id, 100);

        // Should be able to get offsets
        let offsets = tracker.get_committable_offsets();
        assert!(offsets.is_ok());
        assert_eq!(offsets.unwrap().get(&partition), Some(&100));

        // Start rebalancing
        tracker.set_rebalancing(true);
        assert!(tracker.is_rebalancing());

        // Should get RebalanceInProgress error
        let result = tracker.get_committable_offsets();
        assert!(matches!(
            result,
            Err(OffsetTrackerError::RebalanceInProgress)
        ));

        // End rebalancing
        tracker.set_rebalancing(false);
        assert!(!tracker.is_rebalancing());

        // Should be able to get offsets again
        let offsets = tracker.get_committable_offsets();
        assert!(offsets.is_ok());
        assert_eq!(offsets.unwrap().get(&partition), Some(&100));
    }
}
