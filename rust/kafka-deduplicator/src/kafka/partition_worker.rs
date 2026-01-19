//! Partition Worker - Dedicated worker for processing messages from a single partition
//!
//! Each partition gets its own worker with a bounded channel, ensuring:
//! 1. Ordering is preserved within each partition
//! 2. Parallelism is achieved across partitions
//! 3. Backpressure is applied when processing falls behind

use std::sync::Arc;

use anyhow::Result;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{debug, error, info, warn};

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::types::Partition;

/// A batch of messages for a single partition
pub struct PartitionBatch<T> {
    pub partition: Partition,
    pub messages: Vec<KafkaMessage<T>>,
    /// Sequential batch ID for ordering verification
    pub batch_id: u64,
}

impl<T> PartitionBatch<T> {
    pub fn new(partition: Partition, messages: Vec<KafkaMessage<T>>, batch_id: u64) -> Self {
        Self {
            partition,
            messages,
            batch_id,
        }
    }

    /// Compute the maximum offset from the messages in this batch
    /// Returns None if the batch is empty
    pub fn max_offset(&self) -> Option<i64> {
        self.messages.iter().map(|m| m.get_offset()).max()
    }
}

/// Configuration for partition workers
#[derive(Debug, Clone)]
pub struct PartitionWorkerConfig {
    /// Size of the channel buffer per partition
    pub channel_buffer_size: usize,
}

impl Default for PartitionWorkerConfig {
    fn default() -> Self {
        Self {
            channel_buffer_size: 10, // Buffer up to 10 batches per partition
        }
    }
}

/// A worker that processes messages for a single partition
pub struct PartitionWorker<T: Send + 'static> {
    partition: Partition,
    sender: mpsc::Sender<PartitionBatch<T>>,
    handle: Option<JoinHandle<()>>,
}

impl<T: Send + 'static> PartitionWorker<T> {
    /// Create a new partition worker
    pub fn new<P>(
        partition: Partition,
        processor: Arc<P>,
        offset_tracker: Arc<OffsetTracker>,
        config: &PartitionWorkerConfig,
    ) -> Self
    where
        P: BatchConsumerProcessor<T> + 'static,
    {
        let (sender, receiver) = mpsc::channel(config.channel_buffer_size);
        let partition_clone = partition.clone();

        let handle = tokio::spawn(async move {
            Self::run_worker(partition_clone, receiver, processor, offset_tracker).await;
        });

        Self {
            partition,
            sender,
            handle: Some(handle),
        }
    }

    /// Send a batch to this worker for processing
    /// Awaits until channel has capacity. Returns error only if channel is closed (receiver dropped)
    pub async fn send(
        &self,
        batch: PartitionBatch<T>,
    ) -> Result<(), mpsc::error::SendError<PartitionBatch<T>>> {
        self.sender.send(batch).await
    }

    /// Try to send a batch without blocking
    /// Returns error if the channel is full or closed
    pub fn try_send(
        &self,
        batch: PartitionBatch<T>,
    ) -> Result<(), mpsc::error::TrySendError<PartitionBatch<T>>> {
        self.sender.try_send(batch)
    }

    /// Check if the channel has capacity
    pub fn has_capacity(&self) -> bool {
        self.sender.capacity() > 0
    }

    /// Get a clone of the sender for use outside of DashMap guards
    ///
    /// This allows callers to release DashMap guards before awaiting on send operations,
    /// preventing blocking of other DashMap operations during backpressure.
    pub fn sender(&self) -> mpsc::Sender<PartitionBatch<T>> {
        self.sender.clone()
    }

    /// Get the current capacity of the channel
    pub fn capacity(&self) -> usize {
        self.sender.capacity()
    }

    /// Get the partition this worker handles
    pub fn partition(&self) -> &Partition {
        &self.partition
    }

    /// Shutdown the worker gracefully
    pub async fn shutdown(mut self) {
        // Drop the sender to signal the worker to stop
        drop(self.sender);

        // Wait for the worker to finish
        if let Some(handle) = self.handle.take() {
            match handle.await {
                Ok(()) => {
                    debug!(
                        "Partition worker for {}:{} shut down gracefully",
                        self.partition.topic(),
                        self.partition.partition_number()
                    );
                }
                Err(e) => {
                    warn!(
                        "Partition worker for {}:{} panicked during shutdown: {}",
                        self.partition.topic(),
                        self.partition.partition_number(),
                        e
                    );
                }
            }
        }
    }

    /// The main worker loop
    async fn run_worker<P>(
        partition: Partition,
        mut receiver: mpsc::Receiver<PartitionBatch<T>>,
        processor: Arc<P>,
        offset_tracker: Arc<OffsetTracker>,
    ) where
        P: BatchConsumerProcessor<T> + 'static,
    {
        info!(
            "Starting partition worker for {}:{}",
            partition.topic(),
            partition.partition_number()
        );

        while let Some(batch) = receiver.recv().await {
            let message_count = batch.messages.len();
            let first_offset = batch.messages.first().map(|m| m.get_offset());
            let last_offset = batch.messages.last().map(|m| m.get_offset());
            let batch_id = batch.batch_id;

            debug!(
                topic = partition.topic(),
                partition = partition.partition_number(),
                message_count = message_count,
                batch_id = batch_id,
                first_offset = ?first_offset,
                last_offset = ?last_offset,
                "Processing batch"
            );

            // Compute max_offset before consuming messages (process_batch takes ownership)
            let max_offset = batch.max_offset();

            match processor.process_batch(batch.messages).await {
                Ok(()) => {
                    // Mark batch as processed - the next offset to consume is max_offset + 1
                    // Only mark if we had messages (max_offset is Some)
                    if let Some(max_offset) = max_offset {
                        offset_tracker.mark_processed(&partition, batch_id, max_offset + 1);
                        debug!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            batch_id = batch_id,
                            committed_offset = max_offset + 1,
                            "Batch processed successfully"
                        );
                    } else {
                        debug!(
                            topic = partition.topic(),
                            partition = partition.partition_number(),
                            batch_id = batch_id,
                            "Empty batch processed - no offset to commit"
                        );
                    }
                }
                Err(e) => {
                    error!(
                        topic = partition.topic(),
                        partition = partition.partition_number(),
                        message_count = message_count,
                        batch_id = batch_id,
                        first_offset = ?first_offset,
                        last_offset = ?last_offset,
                        error = %e,
                        error_chain = ?e,
                        "Error processing batch - offset not advanced"
                    );
                    // Don't mark as processed on error - offset won't advance
                    // Continue processing next batches
                }
            }
        }

        info!(
            "Partition worker for {}:{} shutting down",
            partition.topic(),
            partition.partition_number()
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::async_trait;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use tokio::time::{sleep, Duration};

    struct TestProcessor {
        processed_count: AtomicUsize,
        delay_ms: u64,
    }

    impl TestProcessor {
        fn new(delay_ms: u64) -> Self {
            Self {
                processed_count: AtomicUsize::new(0),
                delay_ms,
            }
        }
    }

    #[async_trait]
    impl BatchConsumerProcessor<String> for TestProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<String>>) -> Result<()> {
            if self.delay_ms > 0 {
                sleep(Duration::from_millis(self.delay_ms)).await;
            }
            self.processed_count
                .fetch_add(messages.len(), Ordering::SeqCst);
            Ok(())
        }
    }

    /// Test processor that fails a configurable number of times before succeeding
    struct FailingProcessor {
        fail_count: AtomicUsize,
        max_failures: usize,
        processed_after_failures: AtomicUsize,
    }

    impl FailingProcessor {
        fn new(max_failures: usize) -> Self {
            Self {
                fail_count: AtomicUsize::new(0),
                max_failures,
                processed_after_failures: AtomicUsize::new(0),
            }
        }
    }

    #[async_trait]
    impl BatchConsumerProcessor<String> for FailingProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<String>>) -> Result<()> {
            let count = self.fail_count.fetch_add(1, Ordering::SeqCst);
            if count < self.max_failures {
                Err(anyhow::anyhow!("Simulated processor error {}", count + 1))
            } else {
                self.processed_after_failures
                    .fetch_add(messages.len(), Ordering::SeqCst);
                Ok(())
            }
        }
    }

    /// Test processor that tracks whether it was ever called
    struct TrackingProcessor {
        batch_count: AtomicUsize,
        message_count: AtomicUsize,
        delay_ms: u64,
        started: AtomicBool,
    }

    impl TrackingProcessor {
        fn new(delay_ms: u64) -> Self {
            Self {
                batch_count: AtomicUsize::new(0),
                message_count: AtomicUsize::new(0),
                delay_ms,
                started: AtomicBool::new(false),
            }
        }
    }

    #[async_trait]
    impl BatchConsumerProcessor<String> for TrackingProcessor {
        async fn process_batch(&self, messages: Vec<KafkaMessage<String>>) -> Result<()> {
            self.started.store(true, Ordering::SeqCst);
            if self.delay_ms > 0 {
                sleep(Duration::from_millis(self.delay_ms)).await;
            }
            self.batch_count.fetch_add(1, Ordering::SeqCst);
            self.message_count
                .fetch_add(messages.len(), Ordering::SeqCst);
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_partition_worker_basic() {
        let partition = Partition::new("test-topic".to_string(), 0);
        let processor = Arc::new(TestProcessor::new(0));
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionWorkerConfig {
            channel_buffer_size: 5,
        };

        let worker = PartitionWorker::new(
            partition.clone(),
            processor.clone(),
            offset_tracker,
            &config,
        );

        // Send a batch
        let batch = PartitionBatch::new(partition.clone(), vec![], 1);
        worker.send(batch).await.unwrap();

        // Give time for processing
        sleep(Duration::from_millis(10)).await;

        // Shutdown
        worker.shutdown().await;
    }

    #[tokio::test]
    async fn test_partition_worker_backpressure() {
        let partition = Partition::new("test-topic".to_string(), 0);
        let processor = Arc::new(TestProcessor::new(100)); // 100ms delay
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionWorkerConfig {
            channel_buffer_size: 2, // Small buffer
        };

        let worker = PartitionWorker::new(
            partition.clone(),
            processor.clone(),
            offset_tracker,
            &config,
        );

        // Fill the channel
        for i in 0..2 {
            let batch = PartitionBatch::new(partition.clone(), vec![], (i + 1) as u64);
            worker.send(batch).await.unwrap();
        }

        // Channel should be at capacity now
        assert!(!worker.has_capacity() || worker.capacity() <= 1);

        // Shutdown
        worker.shutdown().await;
    }

    #[tokio::test]
    async fn test_partition_worker_handles_processor_errors() {
        // Verify that the worker continues processing after processor errors
        let partition = Partition::new("test-topic".to_string(), 0);
        let processor = Arc::new(FailingProcessor::new(3)); // Fail first 3 batches
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionWorkerConfig {
            channel_buffer_size: 10,
        };

        let worker = PartitionWorker::new(
            partition.clone(),
            processor.clone(),
            offset_tracker,
            &config,
        );

        // Send 5 batches - first 3 will fail, last 2 should succeed
        for i in 0..5 {
            let messages = vec![KafkaMessage::new_for_test(
                partition.clone(),
                i,
                format!("msg{i}"),
            )];
            let batch = PartitionBatch::new(partition.clone(), messages, (i + 1) as u64);
            worker.send(batch).await.unwrap();
        }

        // Give time for processing
        sleep(Duration::from_millis(50)).await;

        // Worker should have continued after failures
        assert_eq!(processor.fail_count.load(Ordering::SeqCst), 5);
        // Last 2 batches should have been processed successfully
        assert_eq!(processor.processed_after_failures.load(Ordering::SeqCst), 2);

        // Worker should still be alive and functional
        let messages = vec![KafkaMessage::new_for_test(
            partition.clone(),
            5,
            "msg5".to_string(),
        )];
        let batch = PartitionBatch::new(partition.clone(), messages, 6);
        worker.send(batch).await.unwrap();

        sleep(Duration::from_millis(10)).await;
        assert_eq!(processor.processed_after_failures.load(Ordering::SeqCst), 3);

        worker.shutdown().await;
    }

    #[tokio::test]
    async fn test_partition_worker_drains_queue_on_shutdown() {
        // Verify that all queued messages are processed before shutdown completes
        let partition = Partition::new("test-topic".to_string(), 0);
        let processor = Arc::new(TrackingProcessor::new(20)); // 20ms delay per batch
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionWorkerConfig {
            channel_buffer_size: 10,
        };

        let worker = PartitionWorker::new(
            partition.clone(),
            processor.clone(),
            offset_tracker,
            &config,
        );

        // Queue up 5 batches with messages
        for i in 0..5 {
            let messages = vec![
                KafkaMessage::new_for_test(partition.clone(), i * 2, format!("msg{}", i * 2)),
                KafkaMessage::new_for_test(
                    partition.clone(),
                    i * 2 + 1,
                    format!("msg{}", i * 2 + 1),
                ),
            ];
            let batch = PartitionBatch::new(partition.clone(), messages, (i + 1) as u64);
            worker.send(batch).await.unwrap();
        }

        // Immediately initiate shutdown - should drain all queued batches
        worker.shutdown().await;

        // All 5 batches (10 messages) should have been processed
        assert_eq!(
            processor.batch_count.load(Ordering::SeqCst),
            5,
            "All queued batches should be processed during shutdown"
        );
        assert_eq!(
            processor.message_count.load(Ordering::SeqCst),
            10,
            "All queued messages should be processed during shutdown"
        );
    }

    #[tokio::test]
    async fn test_partition_worker_channel_closes_on_sender_drop() {
        // Verify that the worker task exits when all senders are dropped
        let partition = Partition::new("test-topic".to_string(), 0);
        let processor = Arc::new(TrackingProcessor::new(0));
        let offset_tracker = Arc::new(OffsetTracker::new());
        let config = PartitionWorkerConfig {
            channel_buffer_size: 5,
        };

        let worker = PartitionWorker::new(
            partition.clone(),
            processor.clone(),
            offset_tracker,
            &config,
        );

        // Send a message then drop the worker (which drops its sender)
        let messages = vec![KafkaMessage::new_for_test(
            partition.clone(),
            0,
            "msg0".to_string(),
        )];
        let batch = PartitionBatch::new(partition.clone(), messages, 1);
        worker.send(batch).await.unwrap();

        // Drop worker - this drops the sender but doesn't wait for task
        drop(worker);

        // Give the worker task time to process remaining messages and exit
        sleep(Duration::from_millis(50)).await;

        // The message should have been processed before the task exited
        assert_eq!(
            processor.message_count.load(Ordering::SeqCst),
            1,
            "Message should be processed even when worker is dropped without explicit shutdown"
        );
    }
}
