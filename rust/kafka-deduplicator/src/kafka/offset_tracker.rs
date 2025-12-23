//! Offset Tracker - Tracks offsets per partition for processing and checkpointing
//!
//! This component provides thread-safe offset tracking for:
//! - **Processed offsets**: Updated after batch processing succeeds, used for periodic commits
//! - **Committed offsets**: Updated after consumer.commit() succeeds, used for checkpointing
//! - **Producer offsets**: Tracks the highest offset written to the output topic, used for checkpointing
//!
//! The distinction between processed and committed is critical for disaster recovery:
//! if we crash between processing and committing, Kafka replays from the last committed offset.
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
    /// The last successfully committed consumer offset (updated after consumer.commit())
    /// Used for checkpointing - represents the offset Kafka would replay from on restart
    committed_offset: i64,
    /// The highest producer offset written to the output topic for this partition
    /// Used for checkpointing to track output progress
    producer_offset: i64,
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
                    committed_offset: 0,
                    producer_offset: 0,
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

    /// Mark offsets as successfully committed to Kafka
    ///
    /// Called after `consumer.commit()` succeeds. These offsets are used for
    /// checkpointing as they represent the true recovery point - if we crash,
    /// Kafka will replay from the last committed offset.
    ///
    /// # Arguments
    /// * `offsets` - Map of partition to committed offset (next offset to consume)
    pub fn mark_committed(&self, offsets: &HashMap<Partition, i64>) {
        for (partition, offset) in offsets {
            self.partition_state
                .entry(partition.clone())
                .and_modify(|state| {
                    if *offset > state.committed_offset {
                        debug!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            previous_committed = state.committed_offset,
                            new_committed = offset,
                            "Advancing committed offset"
                        );
                        state.committed_offset = *offset;
                    }
                });
        }
    }

    /// Get the committed offset for a specific partition
    ///
    /// Returns the last successfully committed consumer offset, which represents
    /// where Kafka would resume consumption after a restart.
    pub fn get_committed_offset(&self, partition: &Partition) -> Option<i64> {
        self.partition_state
            .get(partition)
            .map(|r| r.value().committed_offset)
    }

    /// Mark a producer offset for a partition
    ///
    /// Called after successfully producing messages to the output topic.
    /// Tracks the highest offset written so checkpointing knows output progress.
    ///
    /// # Arguments
    /// * `partition` - The input partition this producer write corresponds to
    /// * `offset` - The producer offset returned from rdkafka
    pub fn mark_produced(&self, partition: &Partition, offset: i64) {
        self.partition_state
            .entry(partition.clone())
            .and_modify(|state| {
                if offset > state.producer_offset {
                    debug!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        previous_producer = state.producer_offset,
                        new_producer = offset,
                        "Advancing producer offset"
                    );
                    state.producer_offset = offset;
                }
            });
    }

    /// Get the producer offset for a specific partition
    ///
    /// Returns the highest offset written to the output topic for messages
    /// originating from this input partition.
    pub fn get_producer_offset(&self, partition: &Partition) -> Option<i64> {
        self.partition_state
            .get(partition)
            .map(|r| r.value().producer_offset)
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

    #[test]
    fn test_mark_committed_updates_committed_offset() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        // First, mark as processed to create the partition state
        tracker.mark_processed(&partition, batch_id, 100);

        // Committed offset starts at 0
        assert_eq!(tracker.get_committed_offset(&partition), Some(0));

        // Mark as committed
        let mut offsets = HashMap::new();
        offsets.insert(partition.clone(), 100);
        tracker.mark_committed(&offsets);

        // Committed offset should now be 100
        assert_eq!(tracker.get_committed_offset(&partition), Some(100));
    }

    #[test]
    fn test_committed_offset_never_goes_backwards() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id, 200);

        let mut offsets = HashMap::new();
        offsets.insert(partition.clone(), 150);
        tracker.mark_committed(&offsets);
        assert_eq!(tracker.get_committed_offset(&partition), Some(150));

        // Try to go backwards - should be ignored
        offsets.insert(partition.clone(), 100);
        tracker.mark_committed(&offsets);
        assert_eq!(tracker.get_committed_offset(&partition), Some(150));

        // Advance forward - should work
        offsets.insert(partition.clone(), 200);
        tracker.mark_committed(&offsets);
        assert_eq!(tracker.get_committed_offset(&partition), Some(200));
    }

    #[test]
    fn test_mark_produced_updates_producer_offset() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        // First, mark as processed to create the partition state
        tracker.mark_processed(&partition, batch_id, 100);

        // Producer offset starts at 0
        assert_eq!(tracker.get_producer_offset(&partition), Some(0));

        // Mark producer offset
        tracker.mark_produced(&partition, 50);
        assert_eq!(tracker.get_producer_offset(&partition), Some(50));

        // Advance producer offset
        tracker.mark_produced(&partition, 75);
        assert_eq!(tracker.get_producer_offset(&partition), Some(75));
    }

    #[test]
    fn test_producer_offset_never_goes_backwards() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id, 100);

        tracker.mark_produced(&partition, 50);
        assert_eq!(tracker.get_producer_offset(&partition), Some(50));

        // Try to go backwards - should be ignored
        tracker.mark_produced(&partition, 25);
        assert_eq!(tracker.get_producer_offset(&partition), Some(50));
    }

    #[test]
    fn test_committed_and_producer_offsets_independent() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id, 100);

        // Set committed and producer offsets to different values
        let mut offsets = HashMap::new();
        offsets.insert(partition.clone(), 80);
        tracker.mark_committed(&offsets);
        tracker.mark_produced(&partition, 50);

        // Verify they're tracked independently
        assert_eq!(tracker.get_partition_offset(&partition), Some(100));
        assert_eq!(tracker.get_committed_offset(&partition), Some(80));
        assert_eq!(tracker.get_producer_offset(&partition), Some(50));
    }

    #[test]
    fn test_clear_partition_clears_all_offsets() {
        let tracker = OffsetTracker::new();
        let partition = test_partition(0);
        let batch_id = tracker.assign_batch_id();

        tracker.mark_processed(&partition, batch_id, 100);

        let mut offsets = HashMap::new();
        offsets.insert(partition.clone(), 80);
        tracker.mark_committed(&offsets);
        tracker.mark_produced(&partition, 50);

        // Clear the partition
        tracker.clear_partition(&partition);

        // All offsets should be None
        assert_eq!(tracker.get_partition_offset(&partition), None);
        assert_eq!(tracker.get_committed_offset(&partition), None);
        assert_eq!(tracker.get_producer_offset(&partition), None);
    }
}
