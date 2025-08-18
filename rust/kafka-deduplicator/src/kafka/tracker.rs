use rdkafka::message::OwnedMessage;
use rdkafka::Message;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};
use tracing::{debug, info, warn};

use crate::kafka::message::MessageResult;

/// Type alias for fenced partitions mapping
type FencedPartitionsMap = Arc<RwLock<HashMap<(String, i32), Arc<AtomicBool>>>>;

/// Completion signal for a message
#[derive(Debug, Clone)]
pub struct MessageCompletion {
    pub offset: i64,
    pub result: MessageResult,
    pub memory_size: usize,
}

/// Per-partition tracker using channels
struct PartitionTracker {
    /// Channel to send completion signals
    completion_tx: mpsc::UnboundedSender<MessageCompletion>,
    /// Channel to receive completion signals
    completion_rx: mpsc::UnboundedReceiver<MessageCompletion>,
    /// Highest committed offset for this partition
    last_committed_offset: i64,
    /// Current in-flight count for this partition
    in_flight_count: usize,
    /// Memory usage for this partition
    memory_usage: usize,
    /// Pending completions that arrived out of order
    pending_completions: HashMap<i64, MessageResult>,
}

impl PartitionTracker {
    fn new() -> Self {
        let (completion_tx, completion_rx) = mpsc::unbounded_channel();

        Self {
            completion_tx,
            completion_rx,
            last_committed_offset: -1,
            in_flight_count: 0,
            memory_usage: 0,
            pending_completions: HashMap::new(),
        }
    }
}

/// Message handle that contains completion info
#[derive(Debug)]
pub struct MessageHandle {
    pub message_id: u64,
    pub offset: i64,
    pub memory_size: usize,
    pub(crate) completion_tx: mpsc::UnboundedSender<MessageCompletion>,
}

impl MessageHandle {
    pub(crate) fn new(
        message_id: u64,
        offset: i64,
        memory_size: usize,
        completion_tx: mpsc::UnboundedSender<MessageCompletion>,
    ) -> Self {
        Self {
            message_id,
            offset,
            memory_size,
            completion_tx,
        }
    }

    /// Send completion signal
    pub async fn complete(&self, result: MessageResult) {
        let completion = MessageCompletion {
            offset: self.offset,
            result,
            memory_size: self.memory_size,
        };

        if self.completion_tx.send(completion).is_err() {
            warn!(
                "Failed to send completion signal for message {}",
                self.message_id
            );
        }
    }
}

/// Tracks in-flight messages using channels per partition
pub struct InFlightTracker {
    /// Per-partition trackers
    partitions: Arc<RwLock<HashMap<(String, i32), PartitionTracker>>>,

    /// Set of revoked partitions that should not accept new messages
    revoked_partitions: Arc<RwLock<HashSet<(String, i32)>>>,

    /// Fast lookup for fenced partitions using atomic booleans
    fenced_partitions: FencedPartitionsMap,

    /// Counter for generating unique message IDs
    next_message_id: AtomicU64,

    /// Global statistics
    completed_count: AtomicU64,
    failed_count: AtomicU64,
}

impl Default for InFlightTracker {
    fn default() -> Self {
        Self::new()
    }
}

impl InFlightTracker {
    pub fn new() -> Self {
        Self {
            partitions: Arc::new(RwLock::new(HashMap::new())),
            revoked_partitions: Arc::new(RwLock::new(HashSet::new())),
            fenced_partitions: Arc::new(RwLock::new(HashMap::new())),
            next_message_id: AtomicU64::new(1),
            completed_count: AtomicU64::new(0),
            failed_count: AtomicU64::new(0),
        }
    }

    /// Add a new message to tracking and return its ID and handle
    pub async fn track_message(
        &self,
        message: &OwnedMessage,
        memory_size: usize,
    ) -> (u64, MessageHandle) {
        let message_id = self.next_message_id.fetch_add(1, Ordering::SeqCst);
        let topic = message.topic().to_string();
        let partition = message.partition();
        let offset = message.offset();

        let completion_tx = {
            let mut partitions = self.partitions.write().await;
            let partition_key = (topic.clone(), partition);

            let tracker = partitions
                .entry(partition_key)
                .or_insert_with(PartitionTracker::new);
            tracker.in_flight_count += 1;
            tracker.memory_usage += memory_size;

            tracker.completion_tx.clone()
        };

        debug!(
            "Tracking message: id={}, topic={}, partition={}, offset={}, memory={}",
            message_id, topic, partition, offset, memory_size
        );

        let handle = MessageHandle::new(message_id, offset, memory_size, completion_tx);

        (message_id, handle)
    }

    /// Process completion signals for all partitions
    pub async fn process_completions(&self) {
        let mut partitions = self.partitions.write().await;

        for ((topic, partition), tracker) in partitions.iter_mut() {
            // Drain all pending completions for this partition
            while let Ok(completion) = tracker.completion_rx.try_recv() {
                tracker.in_flight_count = tracker.in_flight_count.saturating_sub(1);
                tracker.memory_usage = tracker.memory_usage.saturating_sub(completion.memory_size);

                // Update global counters based on result
                match &completion.result {
                    MessageResult::Success => {
                        self.completed_count.fetch_add(1, Ordering::SeqCst);
                    }
                    MessageResult::Failed(_) => {
                        self.failed_count.fetch_add(1, Ordering::SeqCst);
                    }
                }

                // Check if this offset can be committed (sequential from last committed)
                if completion.offset == tracker.last_committed_offset + 1 {
                    tracker.last_committed_offset = completion.offset;

                    // Check if any pending completions can now be committed
                    loop {
                        let next_offset = tracker.last_committed_offset + 1;
                        if let Some(_result) = tracker.pending_completions.remove(&next_offset) {
                            tracker.last_committed_offset = next_offset;
                        } else {
                            break;
                        }
                    }

                    debug!(
                        "Updated safe commit offset: topic={}, partition={}, offset={}",
                        topic, partition, tracker.last_committed_offset
                    );
                } else if completion.offset > tracker.last_committed_offset + 1 {
                    // Out of order completion - store for later
                    tracker
                        .pending_completions
                        .insert(completion.offset, completion.result);
                    debug!(
                        "Stored out-of-order completion: topic={}, partition={}, offset={}",
                        topic, partition, completion.offset
                    );
                }
                // If offset <= last_committed_offset, it's a duplicate or old message - ignore
            }
        }
    }

    /// Get current number of in-flight messages across all partitions
    pub async fn in_flight_count(&self) -> usize {
        let partitions = self.partitions.read().await;
        partitions.values().map(|t| t.in_flight_count).sum()
    }

    /// Get current memory usage across all partitions
    pub async fn memory_usage(&self) -> usize {
        let partitions = self.partitions.read().await;
        partitions.values().map(|t| t.memory_usage).sum()
    }

    /// Get safe commit offsets for all partitions
    pub async fn get_safe_commit_offsets(&self) -> HashMap<(String, i32), i64> {
        // Process any pending completions first
        self.process_completions().await;

        let partitions = self.partitions.read().await;
        partitions
            .iter()
            .filter(|(_, tracker)| tracker.last_committed_offset >= 0)
            .map(|((topic, partition), tracker)| {
                ((topic.clone(), *partition), tracker.last_committed_offset)
            })
            .collect()
    }

    /// Wait for all in-flight messages to complete and return final offsets
    pub async fn wait_for_completion(&self) -> Vec<(String, i32, i64)> {
        info!("Waiting for all in-flight messages to complete...");

        loop {
            // Process any pending completions
            self.process_completions().await;

            // Check if any messages are still in-flight
            let total_in_flight = self.in_flight_count().await;
            if total_in_flight == 0 {
                break;
            }

            info!("Still waiting for {} in-flight messages", total_in_flight);
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }

        // Return final offsets for all partitions
        let safe_offsets = self.get_safe_commit_offsets().await;
        safe_offsets
            .into_iter()
            .map(|((topic, partition), offset)| (topic, partition, offset))
            .collect()
    }

    /// Get statistics about message processing
    pub async fn get_stats(&self) -> TrackerStats {
        let in_flight = self.in_flight_count().await;
        let memory_usage = self.memory_usage().await;
        let completed = self.completed_count.load(Ordering::SeqCst);
        let failed = self.failed_count.load(Ordering::SeqCst);

        TrackerStats {
            in_flight,
            completed,
            failed,
            memory_usage,
        }
    }

    /// Check if a partition is active (not fenced or revoked) - fast non-blocking check
    pub async fn is_partition_active(&self, topic: &str, partition: i32) -> bool {
        // First check if it's fenced
        let fenced = self.fenced_partitions.read().await;
        if let Some(is_fenced) = fenced.get(&(topic.to_string(), partition)) {
            if is_fenced.load(Ordering::Acquire) {
                return false;
            }
        }

        // Then check if it's revoked
        let revoked = self.revoked_partitions.read().await;
        !revoked.contains(&(topic.to_string(), partition))
    }

    /// Fence partitions immediately (non-blocking) to stop accepting new messages
    pub async fn fence_partitions(&self, partitions: &[(String, i32)]) {
        let mut fenced = self.fenced_partitions.write().await;
        for (topic, partition) in partitions {
            info!("Fencing partition {}:{}", topic, partition);
            let is_fenced = fenced
                .entry((topic.clone(), *partition))
                .or_insert_with(|| Arc::new(AtomicBool::new(false)));
            is_fenced.store(true, Ordering::Release);
        }
    }

    /// Finalize revocation after cleanup is complete
    pub async fn finalize_revocation(&self, partitions: &[(String, i32)]) {
        let mut revoked = self.revoked_partitions.write().await;
        let mut fenced = self.fenced_partitions.write().await;

        for (topic, partition) in partitions {
            info!(
                "Finalizing revocation for partition {}:{}",
                topic, partition
            );
            revoked.insert((topic.clone(), *partition));
            // Remove from fenced map as it's now fully revoked
            fenced.remove(&(topic.clone(), *partition));
        }
    }

    /// Mark partitions as active (remove from revoked set and unfence)
    pub async fn mark_partitions_active(&self, partitions: &[(String, i32)]) {
        let mut revoked = self.revoked_partitions.write().await;
        let mut fenced = self.fenced_partitions.write().await;

        for (topic, partition) in partitions {
            info!("Marking partition {}:{} as active", topic, partition);
            revoked.remove(&(topic.clone(), *partition));
            // Remove any fencing
            fenced.remove(&(topic.clone(), *partition));
        }
    }

    /// Wait for all in-flight messages in specific partitions to complete
    pub async fn wait_for_partition_completion(
        &self,
        partitions: &[(String, i32)],
    ) -> Vec<(String, i32, i64)> {
        info!(
            "Waiting for {} partitions to complete processing",
            partitions.len()
        );

        loop {
            // Process any pending completions
            self.process_completions().await;

            // Check if specified partitions have any in-flight messages
            let partitions_guard = self.partitions.read().await;
            let mut total_in_flight = 0;

            for (topic, partition) in partitions {
                let partition_key = (topic.clone(), *partition);
                if let Some(tracker) = partitions_guard.get(&partition_key) {
                    total_in_flight += tracker.in_flight_count;
                }
            }

            if total_in_flight == 0 {
                break;
            }

            info!(
                "Still waiting for {} in-flight messages in {} partitions",
                total_in_flight,
                partitions.len()
            );
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }

        // Return final offsets for specified partitions
        let safe_offsets = self.get_safe_commit_offsets().await;
        partitions
            .iter()
            .filter_map(|(topic, partition)| {
                let partition_key = (topic.clone(), *partition);
                safe_offsets
                    .get(&partition_key)
                    .map(|offset| (topic.clone(), *partition, *offset))
            })
            .collect()
    }

    /// Reset statistics (useful for testing)
    pub async fn reset_stats(&self) {
        self.completed_count.store(0, Ordering::SeqCst);
        self.failed_count.store(0, Ordering::SeqCst);

        let mut partitions = self.partitions.write().await;
        partitions.clear();
    }
}

#[derive(Debug, Clone)]
pub struct TrackerStats {
    pub in_flight: usize,
    pub completed: u64,
    pub failed: u64,
    pub memory_usage: usize,
}

impl std::fmt::Display for TrackerStats {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "in_flight: {}, completed: {}, failed: {}, memory: {}MB",
            self.in_flight,
            self.completed,
            self.failed,
            self.memory_usage / (1024 * 1024)
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rdkafka::message::{OwnedHeaders, OwnedMessage, Timestamp};

    fn create_test_message(
        topic: &str,
        partition: i32,
        offset: i64,
        payload: &str,
    ) -> OwnedMessage {
        OwnedMessage::new(
            Some(payload.as_bytes().to_vec()),
            Some("test-key".as_bytes().to_vec()),
            topic.to_string(),
            Timestamp::now(),
            partition,
            offset,
            Some(OwnedHeaders::new()),
        )
    }

    #[tokio::test]
    async fn test_track_message() {
        let tracker = InFlightTracker::new();
        let message = create_test_message("test-topic", 0, 100, "test-payload");

        let (message_id, _handle) = tracker.track_message(&message, 1024).await;

        assert_eq!(tracker.in_flight_count().await, 1);
        assert_eq!(tracker.memory_usage().await, 1024);

        let stats = tracker.get_stats().await;
        assert_eq!(stats.in_flight, 1);
        assert_eq!(stats.memory_usage, 1024);
        assert_eq!(stats.completed, 0);
        assert_eq!(stats.failed, 0);

        // Verify message ID is sequential
        let (message_id_2, _) = tracker.track_message(&message, 512).await;
        assert_eq!(message_id_2, message_id + 1);
    }

    #[tokio::test]
    async fn test_completion_flow() {
        let tracker = InFlightTracker::new();
        let message = create_test_message("test-topic", 0, 0, "payload");

        let (_message_id, handle) = tracker.track_message(&message, 256).await;

        // Complete the message
        handle.complete(MessageResult::Success).await;

        // Process completions
        tracker.process_completions().await;

        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        // Check safe commit offsets
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(safe_offsets.get(&("test-topic".to_string(), 0)), Some(&0));
    }

    #[tokio::test]
    async fn test_multiple_partitions() {
        let tracker = InFlightTracker::new();

        // Track messages on different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 1, 0, "payload2");
        let msg3 = create_test_message("topic", 0, 1, "payload3");

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 200).await;
        let (_, handle3) = tracker.track_message(&msg3, 150).await;

        assert_eq!(tracker.in_flight_count().await, 3);
        assert_eq!(tracker.memory_usage().await, 450);

        // Complete messages
        handle1.complete(MessageResult::Success).await;
        handle2.complete(MessageResult::Success).await;
        handle3
            .complete(MessageResult::Failed("error".to_string()))
            .await;

        tracker.process_completions().await;

        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(safe_offsets.get(&("topic".to_string(), 0)), Some(&1)); // Both messages on partition 0 completed
        assert_eq!(safe_offsets.get(&("topic".to_string(), 1)), Some(&0)); // Message on partition 1 completed
    }

    #[tokio::test]
    async fn test_out_of_order_completion() {
        let tracker = InFlightTracker::new();

        // Track messages in order
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 0, 2, "payload3");

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 100).await;
        let (_, handle3) = tracker.track_message(&msg3, 100).await;

        // Complete out of order: 3, 1, 2
        handle3.complete(MessageResult::Success).await; // offset 2
        handle1.complete(MessageResult::Success).await; // offset 0
        handle2.complete(MessageResult::Success).await; // offset 1

        tracker.process_completions().await;

        // Should commit all the way to 2 once 1 is completed
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(safe_offsets.get(&("topic".to_string(), 0)), Some(&2));
    }

    #[tokio::test]
    async fn test_offset_gaps() {
        let tracker = InFlightTracker::new();

        // Track messages with a gap
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 2, "payload2"); // Gap at 1

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 100).await;

        // Complete both messages
        handle1.complete(MessageResult::Success).await;
        handle2.complete(MessageResult::Success).await;

        tracker.process_completions().await;

        // Should only commit up to 0 due to gap at 1
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(safe_offsets.get(&("topic".to_string(), 0)), Some(&0));
    }

    #[tokio::test]
    async fn test_wait_for_completion() {
        let tracker = Arc::new(InFlightTracker::new());
        let message = create_test_message("test-topic", 0, 0, "payload");

        let (_, handle) = tracker.track_message(&message, 64).await;

        // Start a task that will complete the message after a delay
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
            handle.complete(MessageResult::Success).await;
        });

        // Wait for completion
        let offsets = tracker.wait_for_completion().await;

        assert_eq!(offsets, vec![("test-topic".to_string(), 0, 0)]);
        assert_eq!(tracker.in_flight_count().await, 0);
    }

    #[tokio::test]
    async fn test_partition_fencing() {
        let tracker = InFlightTracker::new();

        // Initially all partitions should be active
        assert!(tracker.is_partition_active("topic1", 0).await);
        assert!(tracker.is_partition_active("topic1", 1).await);
        assert!(tracker.is_partition_active("topic2", 0).await);

        // Fence some partitions
        let partitions_to_fence = vec![("topic1".to_string(), 0), ("topic2".to_string(), 0)];
        tracker.fence_partitions(&partitions_to_fence).await;

        // Check partition states - fenced partitions should be inactive
        assert!(!tracker.is_partition_active("topic1", 0).await); // Fenced
        assert!(tracker.is_partition_active("topic1", 1).await); // Still active
        assert!(!tracker.is_partition_active("topic2", 0).await); // Fenced

        // Finalize revocation
        tracker.finalize_revocation(&partitions_to_fence).await;

        // Partitions should still be inactive (now revoked)
        assert!(!tracker.is_partition_active("topic1", 0).await);
        assert!(!tracker.is_partition_active("topic2", 0).await);

        // Mark partitions as active again
        tracker.mark_partitions_active(&partitions_to_fence).await;

        // All should be active again
        assert!(tracker.is_partition_active("topic1", 0).await);
        assert!(tracker.is_partition_active("topic1", 1).await);
        assert!(tracker.is_partition_active("topic2", 0).await);
    }

    #[tokio::test]
    async fn test_wait_for_partition_completion() {
        let tracker = InFlightTracker::new();

        // Track messages in different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 1, 0, "payload3");
        let msg4 = create_test_message("other", 0, 0, "payload4");

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 100).await;
        let (_, handle3) = tracker.track_message(&msg3, 100).await;
        let (_, handle4) = tracker.track_message(&msg4, 100).await;

        // Verify in-flight counts
        assert_eq!(tracker.in_flight_count().await, 4);

        // Complete messages in partition topic:0 in background
        let handle1_clone = handle1;
        let handle2_clone = handle2;
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
            handle1_clone.complete(MessageResult::Success).await;
            handle2_clone.complete(MessageResult::Success).await;
        });

        // Wait for specific partition completion
        let target_partitions = vec![("topic".to_string(), 0)];
        let offsets = tracker
            .wait_for_partition_completion(&target_partitions)
            .await;

        // Should get final offsets for the completed partition
        assert_eq!(offsets.len(), 1);
        assert_eq!(offsets[0], ("topic".to_string(), 0, 1)); // Last completed offset

        // Other messages should still be in-flight
        assert_eq!(tracker.in_flight_count().await, 2);

        // Clean up remaining messages
        handle3.complete(MessageResult::Success).await;
        handle4.complete(MessageResult::Success).await;
        tracker.process_completions().await;
    }

    #[tokio::test]
    async fn test_partition_completion_with_no_messages() {
        let tracker = InFlightTracker::new();

        // Wait for completion on partitions with no messages
        let target_partitions = vec![
            ("empty-topic".to_string(), 0),
            ("empty-topic".to_string(), 1),
        ];

        let offsets = tracker
            .wait_for_partition_completion(&target_partitions)
            .await;

        // Should return empty since no messages were tracked
        assert!(offsets.is_empty());
    }

    #[tokio::test]
    async fn test_partition_completion_multiple_partitions() {
        let tracker = InFlightTracker::new();

        // Track messages in multiple partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 1, 0, "payload2");
        let msg3 = create_test_message("topic", 2, 0, "payload3");

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 100).await;
        let (_, handle3) = tracker.track_message(&msg3, 100).await;

        // Complete messages in background with different timing
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
            handle1.complete(MessageResult::Success).await;

            tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
            handle2.complete(MessageResult::Success).await;

            tokio::time::sleep(tokio::time::Duration::from_millis(30)).await;
            handle3.complete(MessageResult::Success).await;
        });

        // Wait for specific partitions
        let target_partitions = vec![("topic".to_string(), 0), ("topic".to_string(), 1)];

        let offsets = tracker
            .wait_for_partition_completion(&target_partitions)
            .await;

        // Should get offsets for both partitions
        assert_eq!(offsets.len(), 2);
        assert!(offsets.contains(&("topic".to_string(), 0, 0)));
        assert!(offsets.contains(&("topic".to_string(), 1, 0)));

        // Partition 2 should still have in-flight message initially
        // Wait a bit more for the last message to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
        tracker.process_completions().await;
        assert_eq!(tracker.in_flight_count().await, 0);
    }

    #[tokio::test]
    async fn test_partition_revocation_workflow() {
        let tracker = InFlightTracker::new();

        // Track messages in different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 1, 0, "payload3");

        let (_, handle1) = tracker.track_message(&msg1, 100).await;
        let (_, handle2) = tracker.track_message(&msg2, 100).await;
        let (_, handle3) = tracker.track_message(&msg3, 100).await;

        // Simulate partition revocation workflow
        let revoked_partitions = vec![("topic".to_string(), 0)];

        // 1. Fence partitions immediately
        tracker.fence_partitions(&revoked_partitions).await;

        // Partition should be marked as inactive immediately
        assert!(!tracker.is_partition_active("topic", 0).await);
        assert!(tracker.is_partition_active("topic", 1).await);

        // 2. Complete in-flight messages in background
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
            handle1.complete(MessageResult::Success).await;
            handle2.complete(MessageResult::Success).await;
        });

        // 3. Wait for partition completion
        let offsets = tracker
            .wait_for_partition_completion(&revoked_partitions)
            .await;

        // Should get final offsets
        assert_eq!(offsets.len(), 1);
        assert_eq!(offsets[0], ("topic".to_string(), 0, 1));

        // 4. Finalize revocation
        tracker.finalize_revocation(&revoked_partitions).await;

        // Other partition should still have in-flight message
        assert_eq!(tracker.in_flight_count().await, 1);

        // Clean up
        handle3.complete(MessageResult::Success).await;
        tracker.process_completions().await;
    }
}
