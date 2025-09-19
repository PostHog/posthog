use anyhow::Result;
use rdkafka::message::OwnedMessage;
use rdkafka::Message;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, OwnedSemaphorePermit, RwLock, Semaphore};
use tokio::task::JoinHandle;
use tokio::time::sleep;
use tracing::{debug, info, warn};

use crate::kafka::errors::TrackingError;
use crate::kafka::message::{AckableMessage, MessageResult};
use crate::kafka::metrics_consts::{
    COMPLETION_CHANNEL_FAILURES, KAFKA_CONSUMER_IN_FLIGHT_MEMORY_BYTES,
    KAFKA_CONSUMER_IN_FLIGHT_MESSAGES, MESSAGES_FORCE_CLEARED, MESSAGE_COMPLETION_DURATION,
    OUT_OF_ORDER_COMPLETIONS, PARTITION_LAST_COMMITTED_OFFSET, PARTITION_OFFSET_GAP_DETECTED,
    PARTITION_OFFSET_GAP_SIZE, PARTITION_PENDING_COMPLETIONS, PARTITION_SECONDS_SINCE_LAST_COMMIT,
};
use crate::kafka::types::{Partition, PartitionAssignment, PartitionOffset, PartitionState};

/// Global statistics shared between InFlightTracker and PartitionTrackers
#[derive(Debug)]
pub struct GlobalStats {
    completed_count: AtomicU64,
    failed_count: AtomicU64,
    in_flight_count: AtomicU64,
    memory_usage: AtomicU64,
}

impl GlobalStats {
    fn new() -> Self {
        Self {
            completed_count: AtomicU64::new(0),
            failed_count: AtomicU64::new(0),
            in_flight_count: AtomicU64::new(0),
            memory_usage: AtomicU64::new(0),
        }
    }

    /// Called when a message has been processed (either successfully or with failure)
    pub fn message_processed(&self, result: &MessageResult, memory_size: usize) {
        // Decrement in-flight counters
        self.in_flight_count.fetch_sub(1, Ordering::SeqCst);
        self.memory_usage
            .fetch_sub(memory_size as u64, Ordering::SeqCst);

        // Update success/failure counters
        match result {
            MessageResult::Success => {
                self.completed_count.fetch_add(1, Ordering::SeqCst);
            }
            MessageResult::Failed(_) => {
                self.failed_count.fetch_add(1, Ordering::SeqCst);
            }
        }
    }

    /// Called when a message starts being tracked
    pub fn message_tracked(&self, memory_size: usize) {
        self.in_flight_count.fetch_add(1, Ordering::SeqCst);
        self.memory_usage
            .fetch_add(memory_size as u64, Ordering::SeqCst);
    }
}

/// Completion signal for a message
#[derive(Debug, Clone)]
pub struct MessageCompletion {
    pub offset: i64,
    pub result: MessageResult,
    pub memory_size: usize,
    pub processing_duration_ms: u64,
}

/// Per-partition tracker that manages its own completion processing
struct PartitionTracker {
    /// Channel to send completion signals
    completion_tx: mpsc::UnboundedSender<MessageCompletion>,
    /// Highest committed offset for this partition (shared with processing task)
    last_committed_offset: Arc<RwLock<i64>>,
    /// Number of messages currently in-flight for this partition
    in_flight_count: Arc<AtomicU64>,
    /// Handle to the completion processing task
    _processor_handle: JoinHandle<()>,
    /// Shutdown signal for graceful cleanup
    shutdown_tx: Option<tokio::sync::oneshot::Sender<()>>,
}

impl Drop for PartitionTracker {
    fn drop(&mut self) {
        // Send shutdown signal if available
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
            debug!("Sent shutdown signal to PartitionTracker completion processor");
        }
        // The JoinHandle will be dropped, which will wait for task completion
        // The channel will be closed when completion_tx is dropped
        debug!("Dropping PartitionTracker - waiting for completion processor to finish");
    }
}

impl PartitionTracker {
    fn new(
        topic: String,
        partition: i32,
        global_stats: Arc<GlobalStats>,
        initial_offset: Option<i64>,
    ) -> Self {
        let (completion_tx, mut completion_rx) = mpsc::unbounded_channel::<MessageCompletion>();
        let (shutdown_tx, mut shutdown_rx) = tokio::sync::oneshot::channel();

        // Initialize last_committed based on initial_offset
        // If we have an initial_offset, we start from (initial_offset - 1) since last_committed
        // represents the last offset that was successfully processed
        let initial_last_committed = initial_offset.map(|o| o - 1).unwrap_or(-1);
        let last_committed_offset = Arc::new(RwLock::new(initial_last_committed));
        let in_flight_count = Arc::new(AtomicU64::new(0));

        // Clone for the processing task
        let last_committed_clone = last_committed_offset.clone();
        let in_flight_clone = in_flight_count.clone();

        // Spawn dedicated task to process completions for this partition
        let processor_handle = tokio::spawn(async move {
            let mut pending_completions: HashMap<i64, MessageCompletion> = HashMap::new();
            let mut last_commit_time = Instant::now();

            info!(
                "Started completion processor for partition {}-{} with initial_offset: {:?}",
                topic, partition, initial_offset
            );

            loop {
                tokio::select! {
                    // Process completions
                    Some(completion) = completion_rx.recv() => {
                // Save the processing duration before moving completion
                let processing_duration_ms = completion.processing_duration_ms;

                // Update global statistics
                global_stats.message_processed(&completion.result, completion.memory_size);

                // Decrement partition's in-flight count
                in_flight_clone.fetch_sub(1, Ordering::SeqCst);

                // Process the completion
                let mut last_committed = last_committed_clone.write().await;

                // Special case: if last_committed is -1 (no initial offset),
                // use the first message's offset to initialize
                if *last_committed == -1 {
                    info!(
                        "Partition {}-{}: initializing from first message at offset {} (setting last_committed to {})",
                        topic, partition, completion.offset, completion.offset - 1
                    );
                    // Set to offset - 1 so that this completion will be processed normally
                    // This maintains the invariant that last_committed is the last successfully processed offset
                    *last_committed = completion.offset - 1;
                    // Don't update last_commit_time here, let it be updated in the normal flow below
                }

                if completion.offset == *last_committed + 1 {
                    *last_committed = completion.offset;
                    last_commit_time = Instant::now();

                    // Process any pending completions that can now be committed
                    loop {
                        let next_offset = *last_committed + 1;
                        if let Some(_result) = pending_completions.remove(&next_offset) {
                            *last_committed = next_offset;
                        } else {
                            break;
                        }
                    }

                    // Emit metrics for successful commit
                    metrics::gauge!(PARTITION_LAST_COMMITTED_OFFSET,
                        "topic" => topic.clone(),
                    "partition" => partition.to_string()
                    )
                    .set(*last_committed as f64);

                    debug!(
                        "Partition {}-{}: committed offset {}",
                        topic, partition, *last_committed
                    );
                } else if completion.offset > *last_committed + 1 {
                    // Out of order - store for later
                    let offset = completion.offset;
                    pending_completions.insert(offset, completion);

                    // Increment out-of-order counter
                    metrics::counter!(OUT_OF_ORDER_COMPLETIONS,
                        "topic" => topic.clone(),
                        "partition" => partition.to_string()
                    )
                    .increment(1);

                    let gap_size = offset - (*last_committed + 1);

                    // Emit gap metrics
                    metrics::gauge!(PARTITION_OFFSET_GAP_SIZE,
                        "topic" => topic.clone(),
                        "partition" => partition.to_string()
                    )
                    .set(gap_size as f64);

                    metrics::counter!(PARTITION_OFFSET_GAP_DETECTED,
                        "topic" => topic.clone(),
                        "partition" => partition.to_string()
                    )
                    .increment(1);
                } else {
                    // completion.offset <= *last_committed - duplicate, ignore
                    warn!(
                        "Ignoring duplicate completion for offset {} (last_committed: {})",
                        completion.offset, *last_committed
                    );
                }


                // Emit metrics for pending completions and processing time
                metrics::gauge!(PARTITION_PENDING_COMPLETIONS,
                    "topic" => topic.clone(),
                    "partition" => partition.to_string()
                )
                .set(pending_completions.len() as f64);


                metrics::gauge!(PARTITION_SECONDS_SINCE_LAST_COMMIT,
                    "topic" => topic.clone(),
                    "partition" => partition.to_string()
                )
                .set(last_commit_time.elapsed().as_secs_f64());

                metrics::histogram!(MESSAGE_COMPLETION_DURATION,
                    "topic" => topic.clone(),
                    "partition" => partition.to_string()
                )
                .record(processing_duration_ms as f64);
                    }
                    // Handle shutdown signal
                    _ = &mut shutdown_rx => {
                        info!("Received shutdown signal for partition {}-{} completion processor", topic, partition);

                        // Process any remaining completions in the channel
                        let mut channel_messages_processed = 0;
                        while let Ok(completion) = completion_rx.try_recv() {
                            global_stats.message_processed(&completion.result, completion.memory_size);
                            in_flight_clone.fetch_sub(1, Ordering::SeqCst);
                            channel_messages_processed += 1;
                            warn!("Processed remaining completion during shutdown: offset={}", completion.offset);
                        }

                        // Clear pending_completions and emit metrics for lost messages
                        let pending_count = pending_completions.len();
                        if pending_count > 0 {
                            warn!(
                                "Dropping {} pending completions for partition {}-{} during revocation",
                                pending_count, topic, partition
                            );

                            // Emit metrics for messages lost during revocation
                            metrics::counter!(
                                "partition_messages_lost_during_revocation",
                                "topic" => topic.clone(),
                                "partition" => partition.to_string()
                            ).increment(pending_count as u64);

                            // Log the offset ranges being dropped for debugging
                            if let (Some(min), Some(max)) = (pending_completions.keys().min(), pending_completions.keys().max()) {
                                warn!(
                                    "Lost pending completions in offset range [{}, {}] for partition {}-{}",
                                    min, max, topic, partition
                                );
                            }

                            pending_completions.clear();
                        }

                        info!(
                            "Shutdown cleanup complete for partition {}-{}: processed {} channel messages, dropped {} pending completions",
                            topic, partition, channel_messages_processed, pending_count
                        );

                        break;
                    }
                }
            }

            info!(
                "Completion processor for partition {}-{} stopped, in_flight={}",
                topic,
                partition,
                in_flight_clone.load(Ordering::SeqCst)
            );
        });

        Self {
            completion_tx,
            last_committed_offset,
            in_flight_count,
            _processor_handle: processor_handle,
            shutdown_tx: Some(shutdown_tx),
        }
    }

    /// Get the number of in-flight messages for this partition
    fn get_in_flight_count(&self) -> usize {
        self.in_flight_count.load(Ordering::SeqCst) as usize
    }

    /// Force clear all in-flight messages for this partition
    /// This should only be called when the partition is being revoked
    fn force_clear_inflight(&self) {
        let count = self.in_flight_count.swap(0, Ordering::SeqCst);
        if count > 0 {
            warn!(
                "Force cleared {} in-flight messages during partition revocation",
                count
            );
            metrics::counter!(MESSAGES_FORCE_CLEARED).increment(count);
        }
    }
}

/// Message handle that contains completion info
#[derive(Debug)]
pub struct MessageHandle {
    pub message_id: String,
    pub partition: i32,
    pub offset: i64,
    pub memory_size: usize,
    pub created_at: Instant,
    pub(crate) completion_tx: mpsc::UnboundedSender<MessageCompletion>,
}

impl MessageHandle {
    pub(crate) fn new(
        message_id: String,
        partition: i32,
        offset: i64,
        memory_size: usize,
        completion_tx: mpsc::UnboundedSender<MessageCompletion>,
    ) -> Self {
        Self {
            message_id,
            partition,
            offset,
            memory_size,
            created_at: Instant::now(),
            completion_tx,
        }
    }

    /// Send completion signal
    pub async fn complete(&self, result: MessageResult) {
        let completion = MessageCompletion {
            offset: self.offset,
            result,
            memory_size: self.memory_size,
            processing_duration_ms: self.created_at.elapsed().as_millis() as u64,
        };

        if self.completion_tx.send(completion).is_err() {
            warn!(
                "Failed to send completion signal for message at offset {}",
                self.offset
            );
            metrics::counter!(COMPLETION_CHANNEL_FAILURES).increment(1);
        }
    }
}

struct PartitionTrackingInfo {
    state: PartitionState,
    tracker: Option<PartitionTracker>,
    initial_offset: Option<i64>,
}

impl PartitionTrackingInfo {
    /// Transition to a new state with validation
    fn transition_to(&mut self, new_state: PartitionState) -> Result<()> {
        // Validate state transitions
        match (&self.state, &new_state) {
            // Valid transitions
            (PartitionState::Active, PartitionState::Fenced) => {}
            (PartitionState::Fenced, PartitionState::Revoked) => {
                // Force clear any in-flight messages and clean up tracker when revoking
                if let Some(tracker) = &self.tracker {
                    tracker.force_clear_inflight();
                }
                self.tracker = None;
            }
            (PartitionState::Fenced, PartitionState::Active) => {
                // Unfencing - clean tracker for fresh start
                if let Some(tracker) = &self.tracker {
                    tracker.force_clear_inflight();
                }
                self.tracker = None;
            }
            (PartitionState::Revoked, PartitionState::Active) => {
                // Reactivating after revocation
                self.tracker = None;
            }
            (PartitionState::Active, PartitionState::Revoked) => {
                // Direct revocation from active (e.g., during fast rebalance)
                self.tracker = None;
            }
            // No-op transitions (already in target state)
            (current, target) if current == target => {
                return Err(anyhow::anyhow!("Already in state {:?}", current));
            }
            // Invalid transitions
            _ => {
                return Err(anyhow::anyhow!(
                    "Invalid state transition from {:?} to {:?}",
                    self.state,
                    new_state
                ));
            }
        }

        self.state = new_state;
        Ok(())
    }
}

/// Tracks in-flight messages using channels per partition
pub struct InFlightTracker {
    /// Per-partition trackers
    partitions: Arc<RwLock<HashMap<Partition, PartitionTrackingInfo>>>,

    /// Global statistics shared with PartitionTrackers
    global_stats: Arc<GlobalStats>,

    /// Semaphore to limit total in-flight messages
    in_flight_semaphore: Arc<Semaphore>,
}

impl Default for InFlightTracker {
    fn default() -> Self {
        Self::with_capacity(100) // Default to 100 for tests
    }
}

impl InFlightTracker {
    pub fn new() -> Self {
        Self::with_capacity(100) // Default to 100 for backward compatibility
    }

    pub fn with_capacity(max_in_flight: usize) -> Self {
        Self {
            partitions: Arc::new(RwLock::new(HashMap::new())),
            global_stats: Arc::new(GlobalStats::new()),
            in_flight_semaphore: Arc::new(Semaphore::new(max_in_flight)),
        }
    }

    /// Track a message and return an AckableMessage that owns the permit
    pub async fn track_message(
        &self,
        message: OwnedMessage,
        memory_size: usize,
        permit: OwnedSemaphorePermit,
    ) -> Result<AckableMessage, TrackingError> {
        let topic = message.topic().to_string();
        let partition = message.partition();
        let offset = message.offset();
        let message_id = format!("{topic}-{partition}-{offset}");

        let completion_tx = {
            let partitions = self.partitions.read().await;
            let partition_key = Partition::new(topic.clone(), partition);

            // Get the partition info - it should exist from assignment
            match partitions.get(&partition_key) {
                Some(info) => {
                    // Check if partition is active
                    if info.state != PartitionState::Active {
                        return Err(TrackingError::InactivePartition {
                            topic,
                            partition,
                            state: info.state,
                        });
                    }

                    let tracker = info
                        .tracker
                        .as_ref()
                        .expect("Tracker should exist for active partition");

                    // Increment partition's in-flight count
                    tracker.in_flight_count.fetch_add(1, Ordering::SeqCst);

                    tracker.completion_tx.clone()
                }
                None => {
                    return Err(TrackingError::UnassignedPartition { topic, partition });
                }
            }
        };

        // Increment global counters only after validation
        self.global_stats.message_tracked(memory_size);

        debug!(
            "Tracking message with permit: topic={}, partition={}, offset={}, memory={}, available_permits={}",
            topic, partition, offset, memory_size, self.in_flight_semaphore.available_permits()
        );

        let handle = MessageHandle::new(message_id, partition, offset, memory_size, completion_tx);

        // Create and return the AckableMessage with ownership of both message and permit
        Ok(AckableMessage::new(message, handle, permit))
    }

    /// Get current number of in-flight messages globally
    pub async fn in_flight_count(&self) -> usize {
        self.global_stats.in_flight_count.load(Ordering::SeqCst) as usize
    }

    /// Get current memory usage globally
    pub async fn memory_usage(&self) -> usize {
        self.global_stats.memory_usage.load(Ordering::SeqCst) as usize
    }

    /// Get safe commit offsets for all partitions
    pub async fn get_safe_commit_offsets(&self) -> HashMap<Partition, i64> {
        let partitions = self.partitions.read().await;
        let mut safe_offsets = HashMap::new();

        // Collect safe offsets from each partition
        for (partition_key, partition_tracker_info) in partitions.iter() {
            if let Some(tracker) = &partition_tracker_info.tracker {
                let last_committed = *tracker.last_committed_offset.read().await;

                info!(
                    "Partition {}:{} - last_committed_offset={}",
                    partition_key.topic(),
                    partition_key.partition_number(),
                    last_committed
                );

                if last_committed >= 0 {
                    safe_offsets.insert(partition_key.clone(), last_committed);
                }
            }
        }

        if safe_offsets.is_empty() {
            info!("No partitions have committable offsets (all have last_committed_offset < 0)");
        }

        safe_offsets
    }

    /// Wait for all in-flight messages to complete and return final offsets
    /// This is a convenience method that waits for ALL partitions
    pub async fn wait_for_completion(&self) -> Vec<PartitionOffset> {
        // Get all active partitions and wait for them
        let partitions = {
            let partitions_guard = self.partitions.read().await;
            partitions_guard.keys().cloned().collect::<Vec<_>>()
        };

        if partitions.is_empty() {
            return Vec::new();
        }

        self.wait_for_partition_completion(&partitions).await
    }

    /// Get statistics about message processing
    pub async fn get_stats(&self) -> TrackerStats {
        let in_flight = self.in_flight_count().await;
        let memory_usage = self.memory_usage().await;
        let completed = self.global_stats.completed_count.load(Ordering::SeqCst);
        let failed = self.global_stats.failed_count.load(Ordering::SeqCst);

        TrackerStats {
            in_flight,
            completed,
            failed,
            memory_usage,
        }
    }

    /// Get available permits from the semaphore
    pub fn available_permits(&self) -> usize {
        self.in_flight_semaphore.available_permits()
    }

    /// Get a clone of the semaphore for acquiring permits
    pub fn in_flight_semaphore_clone(&self) -> Arc<Semaphore> {
        self.in_flight_semaphore.clone()
    }

    /// Get health status of all partitions for monitoring
    pub async fn get_partition_health(&self) -> Vec<PartitionHealth> {
        let partitions = self.partitions.read().await;
        let mut health_reports = Vec::new();

        for (partition_key, partition_tracker_info) in partitions.iter() {
            if let Some(tracker) = &partition_tracker_info.tracker {
                let last_committed = *tracker.last_committed_offset.read().await;
                let in_flight = tracker.get_in_flight_count();

                health_reports.push(PartitionHealth {
                    topic: partition_key.topic().to_string(),
                    partition: partition_key.partition_number(),
                    last_committed_offset: last_committed,
                    in_flight_count: in_flight,
                });
            }
        }

        health_reports
    }

    /// Check if a partition is active (not fenced or revoked) - fast non-blocking check
    pub async fn is_partition_active(&self, partition: &Partition) -> bool {
        let partitions = self.partitions.read().await;
        if let Some(partition_info) = partitions.get(partition) {
            return partition_info.state == PartitionState::Active;
        }
        // Return false for unknown partitions - we only process messages for explicitly tracked partitions
        false
    }

    /// Fence partitions immediately (non-blocking) to stop accepting new messages
    pub async fn fence_partitions(&self, partitions_to_fence: &[Partition]) {
        let mut partitions = self.partitions.write().await;

        for partition in partitions_to_fence {
            info!(
                "Fencing partition {}:{}",
                partition.topic(),
                partition.partition_number()
            );

            if let Some(partition_info) = partitions.get_mut(partition) {
                match partition_info.transition_to(PartitionState::Fenced) {
                    Ok(()) => {
                        info!(
                            "Successfully fenced partition {}:{}",
                            partition.topic(),
                            partition.partition_number()
                        );
                    }
                    Err(e) => {
                        debug!(
                            "Partition {}:{} state transition: {}",
                            partition.topic(),
                            partition.partition_number(),
                            e
                        );
                    }
                }
            } else {
                // Create new entry as fenced for unknown partition
                partitions.insert(
                    partition.clone(),
                    PartitionTrackingInfo {
                        state: PartitionState::Fenced,
                        tracker: None,
                        initial_offset: None,
                    },
                );
                info!(
                    "Created new fenced entry for partition {}:{}",
                    partition.topic(),
                    partition.partition_number()
                );
            }
        }
    }

    /// Finalize revocation after cleanup is complete
    pub async fn finalize_revocation(&self, partitions_to_revoke: &[Partition]) {
        let mut partitions = self.partitions.write().await;

        for partition in partitions_to_revoke {
            info!(
                "Finalizing revocation for partition {}:{}",
                partition.topic(),
                partition.partition_number()
            );

            if let Some(partition_info) = partitions.get_mut(partition) {
                match partition_info.transition_to(PartitionState::Revoked) {
                    Ok(()) => {
                        info!(
                            "Successfully revoked partition {}:{}",
                            partition.topic(),
                            partition.partition_number()
                        );
                    }
                    Err(e) => {
                        debug!(
                            "Partition {}:{} state transition: {}",
                            partition.topic(),
                            partition.partition_number(),
                            e
                        );
                    }
                }
            } else {
                warn!(
                    "Could not revoke partition {}:{} - not found",
                    partition.topic(),
                    partition.partition_number()
                );
            }
        }
    }

    /// Mark partitions as active (remove from revoked set and unfence)
    pub async fn mark_partitions_active(&self, partitions_to_unfence: &[PartitionAssignment]) {
        let mut partitions = self.partitions.write().await;

        for partition in partitions_to_unfence {
            info!(
                "Marking partition {}:{} offset:{:?} as active",
                partition.topic(),
                partition.partition_number(),
                partition.offset()
            );

            if let Some(partition_info) = partitions.get_mut(partition.partition()) {
                match partition_info.transition_to(PartitionState::Active) {
                    Ok(()) => {
                        // Create a new tracker for this partition with the initial offset from Kafka
                        let tracker = PartitionTracker::new(
                            partition.topic().to_string(),
                            partition.partition_number(),
                            self.global_stats.clone(),
                            partition.offset(),
                        );
                        partition_info.tracker = Some(tracker);
                        partition_info.initial_offset = partition.offset();

                        info!(
                            "Successfully activated partition {}:{} with initial offset {:?}",
                            partition.topic(),
                            partition.partition_number(),
                            partition.offset()
                        );
                    }
                    Err(e) => {
                        debug!(
                            "Partition {}:{} state transition: {}",
                            partition.topic(),
                            partition.partition_number(),
                            e
                        );
                    }
                }
            } else {
                // Create new entry for unknown partition with tracker
                let tracker = PartitionTracker::new(
                    partition.topic().to_string(),
                    partition.partition_number(),
                    self.global_stats.clone(),
                    partition.offset(),
                );

                partitions.insert(
                    partition.partition().clone(),
                    PartitionTrackingInfo {
                        state: PartitionState::Active,
                        tracker: Some(tracker),
                        initial_offset: partition.offset(),
                    },
                );
                info!(
                    "Created new active entry for partition {}:{} with initial offset {:?}",
                    partition.topic(),
                    partition.partition_number(),
                    partition.offset()
                );
            }
        }
    }

    /// Wait for all in-flight messages in specific partitions to complete
    pub async fn wait_for_partition_completion(
        &self,
        partitions: &[Partition],
    ) -> Vec<PartitionOffset> {
        info!(
            "Waiting for {} partitions to complete processing",
            partitions.len()
        );

        loop {
            // Process any pending completions
            // Give PartitionTrackers time to process any pending completions
            sleep(Duration::from_millis(10)).await;

            // Check if specified partitions have any in-flight messages
            let partitions_guard = self.partitions.read().await;
            let mut total_in_flight = 0;

            for partition in partitions {
                let partition_key =
                    Partition::new(partition.topic().to_string(), partition.partition_number());
                if let Some(partition_tracker_info) = partitions_guard.get(&partition_key) {
                    if let Some(tracker) = &partition_tracker_info.tracker {
                        total_in_flight += tracker.get_in_flight_count();
                    }
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
            .filter_map(|partition| {
                safe_offsets
                    .get(partition)
                    .map(|offset| PartitionOffset::new(partition.clone(), *offset))
            })
            .collect()
    }

    /// Reset statistics (useful for testing)
    pub async fn reset_stats(&self) {
        self.global_stats.completed_count.store(0, Ordering::SeqCst);
        self.global_stats.failed_count.store(0, Ordering::SeqCst);
        self.global_stats.in_flight_count.store(0, Ordering::SeqCst);
        self.global_stats.memory_usage.store(0, Ordering::SeqCst);

        let mut partitions = self.partitions.write().await;
        partitions.clear();
    }
}

#[derive(Debug, Clone)]
pub struct PartitionHealth {
    pub topic: String,
    pub partition: i32,
    pub last_committed_offset: i64,
    pub in_flight_count: usize,
}

#[derive(Debug, Clone)]
pub struct TrackerStats {
    pub in_flight: usize,
    pub completed: u64,
    pub failed: u64,
    pub memory_usage: usize,
}

impl TrackerStats {
    /// Publish tracker statistics as global metrics
    pub fn publish_metrics(&self) {
        // Publish in-flight messages gauge
        metrics::gauge!(KAFKA_CONSUMER_IN_FLIGHT_MESSAGES).set(self.in_flight as f64);

        // Publish in-flight memory usage gauge
        metrics::gauge!(KAFKA_CONSUMER_IN_FLIGHT_MEMORY_BYTES).set(self.memory_usage as f64);
    }
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
    use crate::common::test_utils::assign_test_partitions;
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

        // Assign the partition first
        assign_test_partitions(&tracker, "test-topic", vec![0]).await;

        let message = create_test_message("test-topic", 0, 100, "test-payload");
        let message2 = create_test_message("test-topic", 0, 101, "test-payload2");

        // Acquire permit for test
        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let _ackable = tracker.track_message(message, 1024, permit).await.unwrap();

        assert_eq!(tracker.in_flight_count().await, 1);
        assert_eq!(tracker.memory_usage().await, 1024);

        let stats = tracker.get_stats().await;
        assert_eq!(stats.in_flight, 1);
        assert_eq!(stats.memory_usage, 1024);
        assert_eq!(stats.completed, 0);
        assert_eq!(stats.failed, 0);

        // Track another message - should succeed since we have capacity
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let _ackable2 = tracker.track_message(message2, 512, permit2).await.unwrap();

        // Both messages should be tracked
        assert_eq!(tracker.in_flight_count().await, 2);
    }

    #[tokio::test]
    async fn test_completion_flow() {
        let tracker = InFlightTracker::new();

        // Assign the partition first
        assign_test_partitions(&tracker, "test-topic", vec![0]).await;

        let message = create_test_message("test-topic", 0, 0, "payload");

        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable = tracker.track_message(message, 256, permit).await.unwrap();

        // Complete the message
        ackable.ack().await;

        // Process completions
        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;

        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        // Check safe commit offsets
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&0)
        );
    }

    #[tokio::test]
    async fn test_multiple_partitions() {
        let tracker = InFlightTracker::new();

        // Assign the partitions first
        assign_test_partitions(&tracker, "topic", vec![0, 1]).await;

        // Track messages on different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 1, 0, "payload2");
        let msg3 = create_test_message("topic", 0, 1, "payload3");

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit3 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 200, permit2).await.unwrap();
        let ackable3 = tracker.track_message(msg3, 150, permit3).await.unwrap();

        assert_eq!(tracker.in_flight_count().await, 3);
        assert_eq!(tracker.memory_usage().await, 450);

        // Complete messages
        ackable1.ack().await;
        ackable2.ack().await;
        ackable3.nack("error".to_string()).await;

        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;

        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);

        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("topic".to_string(), 0)),
            Some(&1)
        ); // Both messages on partition 0 completed
        assert_eq!(
            safe_offsets.get(&Partition::new("topic".to_string(), 1)),
            Some(&0)
        ); // Message on partition 1 completed
    }

    #[tokio::test]
    async fn test_out_of_order_completion() {
        let tracker = InFlightTracker::new();

        // Assign the partition first
        assign_test_partitions(&tracker, "topic", vec![0]).await;

        // Track messages in order
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 0, 2, "payload3");

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit3 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 100, permit2).await.unwrap();
        let ackable3 = tracker.track_message(msg3, 100, permit3).await.unwrap();

        // Complete out of order: 3, 1, 2
        ackable3.ack().await; // offset 2
        ackable1.ack().await; // offset 0
        ackable2.ack().await; // offset 1

        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;

        // Should commit all the way to 2 once 1 is completed
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("topic".to_string(), 0)),
            Some(&2)
        );
    }

    #[tokio::test]
    async fn test_offset_gaps() {
        let tracker = InFlightTracker::new();

        // Assign the partition first
        assign_test_partitions(&tracker, "topic", vec![0]).await;

        // Track messages with a gap
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 2, "payload2"); // Gap at 1

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 100, permit2).await.unwrap();

        // Complete both messages
        ackable1.ack().await;
        ackable2.ack().await;

        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;

        // Should only commit up to 0 due to gap at 1
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("topic".to_string(), 0)),
            Some(&0)
        );
    }

    #[tokio::test]
    async fn test_wait_for_completion() {
        let tracker = Arc::new(InFlightTracker::new());

        // Assign the partition first
        assign_test_partitions(&tracker, "test-topic", vec![0]).await;

        let message = create_test_message("test-topic", 0, 0, "payload");

        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable = tracker.track_message(message, 64, permit).await.unwrap();

        // Start a task that will complete the message after a delay
        tokio::spawn(async move {
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
            ackable.ack().await;
        });

        // Wait for completion
        let offsets = tracker.wait_for_completion().await;

        assert_eq!(
            offsets,
            vec![PartitionOffset::new(
                Partition::new("test-topic".to_string(), 0),
                0
            )]
        );
        assert_eq!(tracker.in_flight_count().await, 0);
    }

    #[tokio::test]
    async fn test_partition_fencing() {
        let tracker = InFlightTracker::new();

        // Initially unknown partitions should be inactive (not tracked)
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 0))
                .await
        );
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 1))
                .await
        );

        // Mark some partitions as active first
        let partitions_to_activate = vec![
            PartitionAssignment::new(Partition::new("topic1".to_string(), 0), None),
            PartitionAssignment::new(Partition::new("topic1".to_string(), 1), None),
            PartitionAssignment::new(Partition::new("topic2".to_string(), 0), None),
        ];
        tracker
            .mark_partitions_active(&partitions_to_activate)
            .await;

        // Now they should be active
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 0))
                .await
        );
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 1))
                .await
        );

        // Fence some partitions
        let partitions_to_fence = vec![
            Partition::new("topic1".to_string(), 0),
            Partition::new("topic2".to_string(), 0),
        ];

        let partition_assignments: Vec<PartitionAssignment> = partitions_to_fence
            .iter()
            .map(|p| PartitionAssignment::new(p.clone(), None))
            .collect();
        tracker.fence_partitions(&partitions_to_fence).await;

        // Check partition states - fenced partitions should be inactive
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 0))
                .await
        ); // Fenced
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 1))
                .await
        ); // Still active

        // Finalize revocation
        tracker.finalize_revocation(&partitions_to_fence).await;

        // Partitions should still be inactive (now revoked)
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 0))
                .await
        );
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic2".to_string(), 0))
                .await
        );

        // Mark partitions as active again
        tracker.mark_partitions_active(&partition_assignments).await;

        // All should be active again
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 0))
                .await
        );
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic1".to_string(), 1))
                .await
        );
    }

    #[tokio::test]
    async fn test_wait_for_partition_completion() {
        let tracker = InFlightTracker::new();

        // Assign the partitions first
        assign_test_partitions(&tracker, "topic", vec![0, 1]).await;
        assign_test_partitions(&tracker, "other", vec![0]).await;

        // Track messages in different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 1, 0, "payload3");
        let msg4 = create_test_message("other", 0, 0, "payload4");

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit3 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit4 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 100, permit2).await.unwrap();
        let ackable3 = tracker.track_message(msg3, 100, permit3).await.unwrap();
        let ackable4 = tracker.track_message(msg4, 100, permit4).await.unwrap();

        // Verify in-flight counts
        assert_eq!(tracker.in_flight_count().await, 4);

        // Complete messages in partition topic:0 in background
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
            ackable1.ack().await;
            ackable2.ack().await;
        });

        // Wait for specific partition completion
        let target_partitions = vec![Partition::new("topic".to_string(), 0)];
        let offsets = tracker
            .wait_for_partition_completion(&target_partitions)
            .await;

        // Should get final offsets for the completed partition
        assert_eq!(offsets.len(), 1);
        assert_eq!(
            offsets[0],
            PartitionOffset::new(Partition::new("topic".to_string(), 0), 1)
        ); // Last completed offset

        // Other messages should still be in-flight
        assert_eq!(tracker.in_flight_count().await, 2);

        // Clean up remaining messages
        ackable3.ack().await;
        ackable4.ack().await;
        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;
    }

    #[tokio::test]
    async fn test_partition_completion_with_no_messages() {
        let tracker = InFlightTracker::new();

        // Wait for completion on partitions with no messages
        let target_partitions = vec![
            Partition::new("empty-topic".to_string(), 0),
            Partition::new("empty-topic".to_string(), 1),
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

        // Assign the partitions first
        assign_test_partitions(&tracker, "topic", vec![0, 1, 2]).await;

        // Track messages in multiple partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 1, 0, "payload2");
        let msg3 = create_test_message("topic", 2, 0, "payload3");

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit3 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 100, permit2).await.unwrap();
        let ackable3 = tracker.track_message(msg3, 100, permit3).await.unwrap();

        // Complete messages in background with different timing
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
            ackable1.ack().await;

            tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
            ackable2.ack().await;

            tokio::time::sleep(tokio::time::Duration::from_millis(30)).await;
            ackable3.ack().await;
        });

        // Wait for specific partitions
        let target_partitions = vec![
            Partition::new("topic".to_string(), 0),
            Partition::new("topic".to_string(), 1),
        ];

        let offsets = tracker
            .wait_for_partition_completion(&target_partitions)
            .await;

        // Should get offsets for both partitions
        assert_eq!(offsets.len(), 2);
        assert!(offsets.contains(&PartitionOffset::new(
            Partition::new("topic".to_string(), 0),
            0
        )));
        assert!(offsets.contains(&PartitionOffset::new(
            Partition::new("topic".to_string(), 1),
            0
        )));

        // Partition 2 should still have in-flight message initially
        // Wait a bit more for the last message to complete
        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;
        assert_eq!(tracker.in_flight_count().await, 0);
    }

    #[tokio::test]
    async fn test_partition_revocation_workflow() {
        let tracker = InFlightTracker::new();

        // Assign the partitions first
        assign_test_partitions(&tracker, "topic", vec![0, 1]).await;

        // Track messages in different partitions
        let msg1 = create_test_message("topic", 0, 0, "payload1");
        let msg2 = create_test_message("topic", 0, 1, "payload2");
        let msg3 = create_test_message("topic", 1, 0, "payload3");

        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit3 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();
        let ackable2 = tracker.track_message(msg2, 100, permit2).await.unwrap();
        let ackable3 = tracker.track_message(msg3, 100, permit3).await.unwrap();

        // Simulate partition revocation workflow
        let revoked_partitions = vec![Partition::new("topic".to_string(), 0)];

        // 1. Fence partitions immediately
        tracker.fence_partitions(&revoked_partitions).await;

        // Partition should be marked as inactive immediately
        assert!(
            !tracker
                .is_partition_active(&Partition::new("topic".to_string(), 0))
                .await
        );
        assert!(
            tracker
                .is_partition_active(&Partition::new("topic".to_string(), 1))
                .await
        );

        // 2. Complete in-flight messages in background
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
            ackable1.ack().await;
            ackable2.ack().await;
        });

        // 3. Wait for partition completion
        let offsets = tracker
            .wait_for_partition_completion(&revoked_partitions)
            .await;

        // Should get final offsets
        assert_eq!(offsets.len(), 1);
        assert_eq!(
            offsets[0],
            PartitionOffset::new(Partition::new("topic".to_string(), 0), 1)
        );

        // 4. Finalize revocation
        tracker.finalize_revocation(&revoked_partitions).await;

        // Other partition should still have in-flight message
        assert_eq!(tracker.in_flight_count().await, 1);

        // Clean up
        ackable3.ack().await;
        // Give PartitionTracker time to process
        sleep(Duration::from_millis(50)).await;
    }

    #[tokio::test]
    async fn test_track_message_unassigned_partition() {
        use crate::kafka::errors::TrackingError;

        let tracker = InFlightTracker::new();

        // Try to track a message for an unassigned partition
        let message = create_test_message("unassigned-topic", 0, 100, "test-payload");
        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let result = tracker.track_message(message, 100, permit).await;

        // Should return an error for unassigned partition
        assert!(result.is_err());
        match result.err().unwrap() {
            TrackingError::UnassignedPartition { topic, partition } => {
                assert_eq!(topic, "unassigned-topic");
                assert_eq!(partition, 0);
            }
            _ => panic!("Expected UnassignedPartition error"),
        }

        // No messages should be tracked
        assert_eq!(tracker.in_flight_count().await, 0);
        assert_eq!(tracker.memory_usage().await, 0);
    }

    #[tokio::test]
    async fn test_track_message_fenced_partition() {
        use crate::kafka::errors::TrackingError;

        let tracker = InFlightTracker::new();

        // Assign a partition
        assign_test_partitions(&tracker, "test-topic", vec![0]).await;

        // Track a message successfully
        let msg1 = create_test_message("test-topic", 0, 100, "payload1");
        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();

        // Fence the partition
        tracker
            .fence_partitions(&[Partition::new("test-topic".to_string(), 0)])
            .await;

        // Try to track another message for the fenced partition
        let msg2 = create_test_message("test-topic", 0, 101, "payload2");
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let result = tracker.track_message(msg2, 100, permit2).await;

        // Should return an error for inactive partition
        assert!(result.is_err());
        match result.err().unwrap() {
            TrackingError::InactivePartition {
                topic,
                partition,
                state,
            } => {
                assert_eq!(topic, "test-topic");
                assert_eq!(partition, 0);
                assert_eq!(state, PartitionState::Fenced);
            }
            _ => panic!("Expected InactivePartition error"),
        }

        // Only the first message should be tracked
        assert_eq!(tracker.in_flight_count().await, 1);

        // Clean up
        ackable1.ack().await;
        sleep(Duration::from_millis(10)).await;
    }

    #[tokio::test]
    async fn test_track_message_revoked_partition() {
        use crate::kafka::errors::TrackingError;

        let tracker = InFlightTracker::new();

        // Assign a partition
        assign_test_partitions(&tracker, "test-topic", vec![0]).await;

        // Track a message successfully
        let msg1 = create_test_message("test-topic", 0, 100, "payload1");
        let permit1 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable1 = tracker.track_message(msg1, 100, permit1).await.unwrap();

        // Fence and then revoke the partition
        let partition = Partition::new("test-topic".to_string(), 0);
        tracker.fence_partitions(&[partition.clone()]).await;

        // Complete the message
        ackable1.ack().await;

        // Wait for completion
        tracker
            .wait_for_partition_completion(&[partition.clone()])
            .await;

        // Finalize revocation (transitions from Fenced to Revoked)
        tracker.finalize_revocation(&[partition.clone()]).await;

        // Try to track another message for the revoked partition
        let msg2 = create_test_message("test-topic", 0, 101, "payload2");
        let permit2 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let result = tracker.track_message(msg2, 100, permit2).await;

        // Should return an error for inactive partition
        assert!(result.is_err());
        match result.err().unwrap() {
            TrackingError::InactivePartition {
                topic,
                partition,
                state,
            } => {
                assert_eq!(topic, "test-topic");
                assert_eq!(partition, 0);
                assert_eq!(state, PartitionState::Revoked);
            }
            _ => panic!("Expected InactivePartition error with Revoked state"),
        }

        // No messages should be tracked
        assert_eq!(tracker.in_flight_count().await, 0);
    }

    #[tokio::test]
    async fn test_completion_with_initial_offset() {
        let tracker = Arc::new(InFlightTracker::new());

        // Assign a partition with initial offset 100
        let assignments = vec![PartitionAssignment::new(
            Partition::new("test-topic".to_string(), 0),
            Some(100), // Start from offset 100
        )];
        tracker.mark_partitions_active(&assignments).await;

        // Track messages starting from offset 100
        let msg100 = create_test_message("test-topic", 0, 100, "payload100");
        let msg101 = create_test_message("test-topic", 0, 101, "payload101");
        let msg102 = create_test_message("test-topic", 0, 102, "payload102");

        let permit100 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit101 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let permit102 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();

        let ackable100 = tracker.track_message(msg100, 100, permit100).await.unwrap();
        let ackable101 = tracker.track_message(msg101, 100, permit101).await.unwrap();
        let ackable102 = tracker.track_message(msg102, 100, permit102).await.unwrap();

        // Complete messages out of order: 101, 102, then 100
        ackable101.ack().await;
        ackable102.ack().await;

        // Give time for processing
        sleep(Duration::from_millis(10)).await;

        // Should have no commits yet (waiting for 100)
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert!(
            safe_offsets.is_empty()
                || safe_offsets.get(&Partition::new("test-topic".to_string(), 0)) == Some(&99)
        );

        // Now complete 100
        ackable100.ack().await;
        sleep(Duration::from_millis(10)).await;

        // Should have committed through 102
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&102)
        );
    }

    #[tokio::test]
    async fn test_duplicate_completion_ignored() {
        let tracker = Arc::new(InFlightTracker::new());

        // Assign a partition with initial offset 100
        let assignments = vec![PartitionAssignment::new(
            Partition::new("test-topic".to_string(), 0),
            Some(100),
        )];
        tracker.mark_partitions_active(&assignments).await;

        // Track and complete message 100
        let msg100 = create_test_message("test-topic", 0, 100, "payload100");
        let permit100 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable100 = tracker.track_message(msg100, 100, permit100).await.unwrap();
        ackable100.ack().await;
        sleep(Duration::from_millis(10)).await;

        // Try to track a message with offset 99 (before initial offset)
        // This should still work at the tracking level, but completion should be ignored
        let msg99 = create_test_message("test-topic", 0, 99, "payload99");
        let permit99 = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable99 = tracker.track_message(msg99, 100, permit99).await.unwrap();
        ackable99.ack().await;
        sleep(Duration::from_millis(10)).await;

        // Safe offset should still be 100, not affected by the duplicate
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&100)
        );
    }

    #[tokio::test]
    async fn test_high_concurrency_out_of_order_completions() {
        use rand::seq::SliceRandom;
        use rand::thread_rng;
        use std::collections::HashSet;

        const NUM_MESSAGES: i64 = 500; // Test with 500 messages for high concurrency

        // Create tracker with capacity for all messages we'll track
        let tracker = Arc::new(InFlightTracker::with_capacity(NUM_MESSAGES as usize));

        // Assign partition starting from offset 1000
        let assignments = vec![PartitionAssignment::new(
            Partition::new("test-topic".to_string(), 0),
            Some(1000),
        )];
        tracker.mark_partitions_active(&assignments).await;
        let mut ackable_messages = Vec::new();

        // Track all messages
        for i in 0..NUM_MESSAGES {
            let offset = 1000 + i;
            let msg = create_test_message("test-topic", 0, offset, &format!("payload{offset}"));
            let permit = tracker
                .in_flight_semaphore_clone()
                .acquire_owned()
                .await
                .unwrap();
            let ackable = tracker.track_message(msg, 100, permit).await.unwrap();
            ackable_messages.push((offset, ackable));
        }

        // Verify all messages are tracked
        assert_eq!(tracker.in_flight_count().await, NUM_MESSAGES as usize);

        // Create a random completion order
        let mut rng = thread_rng();
        ackable_messages.shuffle(&mut rng);

        // Complete messages in random order, simulating high concurrency
        let mut handles = Vec::new();
        for (offset, ackable) in ackable_messages {
            let handle = tokio::spawn(async move {
                // Add random delay to simulate processing time
                let delay = rand::random::<u64>() % 5;
                sleep(Duration::from_millis(delay)).await;
                ackable.ack().await;
                offset
            });
            handles.push(handle);
        }

        // Wait for all completions
        let mut completed_offsets = HashSet::new();
        for handle in handles {
            let offset = handle.await.unwrap();
            completed_offsets.insert(offset);
        }

        // Verify all messages were completed
        assert_eq!(completed_offsets.len(), NUM_MESSAGES as usize);

        // Give PartitionTracker time to process all completions
        sleep(Duration::from_millis(100)).await;

        // Verify final state
        assert_eq!(tracker.in_flight_count().await, 0);

        // The safe commit offset should be the last message (1000 + NUM_MESSAGES - 1)
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&(1000 + NUM_MESSAGES - 1))
        );

        // Get partition health to verify the state
        let health = tracker.get_partition_health().await;
        assert_eq!(health.len(), 1);
        assert_eq!(health[0].last_committed_offset, 1000 + NUM_MESSAGES - 1);
        assert_eq!(health[0].in_flight_count, 0);
    }

    #[tokio::test]
    async fn test_concurrent_completions_with_gaps() {
        let tracker = Arc::new(InFlightTracker::new());

        // Assign partition starting from offset 2000
        let assignments = vec![PartitionAssignment::new(
            Partition::new("test-topic".to_string(), 0),
            Some(2000),
        )];
        tracker.mark_partitions_active(&assignments).await;

        // Track messages with some gaps (simulating lost messages)
        let offsets_to_track = vec![
            2000, 2001, 2002, 2003, 2004, // Sequential block
            2006, 2007, 2008, // Gap at 2005
            2010, 2011, 2012, // Gap at 2009
            2015, 2016, 2017, // Gap at 2013, 2014
        ];

        let mut ackables = Vec::new();
        for offset in &offsets_to_track {
            let msg = create_test_message("test-topic", 0, *offset, &format!("payload{offset}"));
            let permit = tracker
                .in_flight_semaphore_clone()
                .acquire_owned()
                .await
                .unwrap();
            let ackable = tracker.track_message(msg, 100, permit).await.unwrap();
            ackables.push((*offset, ackable));
        }

        // Complete in reverse order (worst case for pending_completions)
        for (_, ackable) in ackables.into_iter().rev() {
            ackable.ack().await;
            sleep(Duration::from_millis(5)).await;
        }

        // Give time for processing
        sleep(Duration::from_millis(50)).await;

        // Should only commit up to 2004 (last sequential from start)
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&2004),
            "Should only commit up to the last sequential offset before the first gap"
        );

        // Now simulate filling the gap at 2005
        let msg2005 = create_test_message("test-topic", 0, 2005, "payload2005");
        let permit = tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .unwrap();
        let ackable2005 = tracker.track_message(msg2005, 100, permit).await.unwrap();
        ackable2005.ack().await;
        sleep(Duration::from_millis(50)).await;

        // Should now commit up to 2008
        let safe_offsets = tracker.get_safe_commit_offsets().await;
        assert_eq!(
            safe_offsets.get(&Partition::new("test-topic".to_string(), 0)),
            Some(&2008),
            "After filling gap at 2005, should commit up to 2008"
        );
    }
}
