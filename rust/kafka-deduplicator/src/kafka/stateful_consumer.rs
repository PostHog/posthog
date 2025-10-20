use anyhow::Result;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::Message;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc::UnboundedSender;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tracing::{debug, error, info};

use crate::kafka::metrics_consts::KAFKA_CONSUMER_AVAILABLE_PERMITS;
use crate::kafka::types::Partition;

use super::message::AckableMessage;
use super::rebalance_handler::RebalanceHandler;
use super::stateful_context::StatefulConsumerContext;
use super::tracker::{InFlightTracker, TrackerStats};

/// Stateful Kafka consumer that coordinates with external state systems
/// This consumer ensures sequential offset commits and coordinated partition revocation
pub struct StatefulKafkaConsumer {
    /// Kafka consumer instance with stateful context
    consumer: StreamConsumer<StatefulConsumerContext>,

    /// In-flight message tracker (owns the semaphore for backpressure)
    tracker: Arc<InFlightTracker>,

    /// How often to commit offsets
    commit_interval: Duration,

    /// Shutdown signal for graceful shutdown
    shutdown_rx: oneshot::Receiver<()>,

    /// Channel to send messages to the processor pool
    /// The pool handles routing and parallel processing
    message_sender: UnboundedSender<AckableMessage>,
}

impl StatefulKafkaConsumer {
    /// Create a new stateful Kafka consumer with integrated tracker and context
    /// The message_sender channel connects to a processor pool that handles the actual processing
    pub fn from_config(
        config: &rdkafka::ClientConfig,
        rebalance_handler: Arc<dyn RebalanceHandler>,
        message_sender: UnboundedSender<AckableMessage>,
        max_in_flight_messages: usize,
        commit_interval: Duration,
        shutdown_rx: oneshot::Receiver<()>,
    ) -> Result<Self> {
        let tracker = Arc::new(InFlightTracker::with_capacity(max_in_flight_messages));
        let context = StatefulConsumerContext::new(rebalance_handler, tracker.clone());

        let consumer: StreamConsumer<StatefulConsumerContext> =
            config.create_with_context(context)?;

        Ok(Self {
            consumer,
            tracker,
            commit_interval,
            shutdown_rx,
            message_sender,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(mut self) -> Result<()> {
        info!("Starting stateful Kafka message consumption");

        let mut commit_interval = tokio::time::interval(self.commit_interval);
        // Publish metrics every 10 seconds for observability
        let mut metrics_interval = tokio::time::interval(Duration::from_secs(10));

        loop {
            // Check capacity BEFORE polling Kafka
            let permits_available = self.tracker.available_permits();

            if permits_available == 0 {
                // No capacity - don't poll Kafka, just handle control operations
                tokio::select! {
                    // Check for shutdown signal
                    _ = &mut self.shutdown_rx => {
                        info!("Shutdown signal received, starting graceful shutdown");
                        break;
                    }

                    // Wait briefly for capacity to become available
                    _ = tokio::time::sleep(Duration::from_millis(50)) => {
                        debug!("No permits available, waiting for capacity");
                        continue;
                    }

                    // Publish metrics every 10 seconds
                    _ = metrics_interval.tick() => {
                        info!("Starting metrics publication cycle");

                        let stats = self.tracker.get_stats().await;
                        let available_permits = self.tracker.available_permits();
                        let partition_health = self.tracker.get_partition_health().await;

                        info!(
                            "Global Metrics: in_flight={}, completed={}, failed={}, memory={}MB, available_permits={}",
                            stats.in_flight, stats.completed, stats.failed,
                            stats.memory_usage / (1024 * 1024),
                            available_permits
                        );

                        // Log partition health status
                        for health in &partition_health {
                            info!(
                                "Partition {}-{}: last_committed={}, in_flight={}",
                                health.topic, health.partition,
                                health.last_committed_offset, health.in_flight_count
                            );
                        }

                        stats.publish_metrics();

                        // Also publish semaphore permit metrics from the tracker
                        metrics::gauge!(KAFKA_CONSUMER_AVAILABLE_PERMITS)
                            .set(available_permits as f64);

                        info!("Metrics published successfully");
                    }

                    // Commit offsets periodically
                    _ = commit_interval.tick() => {
                        if let Err(e) = self.commit_offsets().await {
                            error!("Failed to commit offsets: {}", e);
                        }
                    }
                }
            } else {
                // We have capacity - poll Kafka with short timeout
                tokio::select! {
                    // Check for shutdown signal
                    _ = &mut self.shutdown_rx => {
                        info!("Shutdown signal received, starting graceful shutdown");
                        break;
                    }

                    // Poll for messages
                    msg_result = timeout(Duration::from_millis(10), self.consumer.recv()) => {
                        match msg_result {
                            Ok(Ok(msg)) => {
                                // Send message to processor pool
                                self.send_to_processor(msg).await?;
                            }
                            Ok(Err(e)) => {
                                error!("Error receiving message: {}", e);
                                tokio::time::sleep(Duration::from_millis(100)).await;
                            }
                            Err(_) => {
                                // Timeout, this is expected when no messages available
                            }
                        }
                    }

                    // Publish metrics every 10 seconds
                    _ = metrics_interval.tick() => {
                        info!("Starting metrics publication cycle");

                        let stats = self.tracker.get_stats().await;
                        let available_permits = self.tracker.available_permits();
                        let partition_health = self.tracker.get_partition_health().await;

                        info!(
                            "Global Metrics: in_flight={}, completed={}, failed={}, memory={}MB, available_permits={}",
                            stats.in_flight, stats.completed, stats.failed,
                            stats.memory_usage / (1024 * 1024),
                            available_permits
                        );

                        // Log partition health status
                        for health in &partition_health {
                            info!(
                                "Partition {}-{}: last_committed={}, in_flight={}",
                                health.topic, health.partition,
                                health.last_committed_offset, health.in_flight_count
                            );
                        }

                        stats.publish_metrics();

                        // Also publish semaphore permit metrics from the tracker
                        metrics::gauge!(KAFKA_CONSUMER_AVAILABLE_PERMITS)
                            .set(available_permits as f64);

                        info!("Metrics published successfully");
                    }

                    // Commit offsets periodically
                    _ = commit_interval.tick() => {
                        if let Err(e) = self.commit_offsets().await {
                            error!("Failed to commit offsets: {}", e);
                        }
                    }
                }
            }
        }

        // Graceful shutdown: wait for in-flight messages to complete
        info!("Waiting for in-flight messages to complete");

        let final_offsets = self.tracker.wait_for_completion().await;
        info!(
            "All in-flight messages completed. Final offsets: {:?}",
            final_offsets
        );

        // Final commit
        if let Err(e) = self.commit_offsets().await {
            error!("Failed to commit final offsets: {}", e);
        } else {
            info!("Final offsets committed successfully");
        }

        // Drop the sender to signal no more messages
        drop(self.message_sender);

        info!("Graceful shutdown completed");
        Ok(())
    }

    /// Send a message to the processor pool
    async fn send_to_processor<'a>(
        &self,
        msg: rdkafka::message::BorrowedMessage<'a>,
    ) -> Result<()> {
        // First check if we should process this message (partition not revoked)
        let topic = msg.topic();
        let partition_num = msg.partition();
        let offset = msg.offset();
        let partition = Partition::new(topic.to_string(), partition_num);

        if !self.tracker.is_partition_active(&partition).await {
            // Increment metric instead of logging to reduce noise
            metrics::counter!(
                crate::kafka::metrics_consts::MESSAGES_SKIPPED_REVOKED,
                "topic" => topic.to_string(),
                "partition" => partition_num.to_string()
            )
            .increment(1);

            // Only log occasionally for debugging
            debug!(
                "Skipping message from revoked partition {}:{} offset {}",
                topic, partition_num, offset
            );
            return Ok(());
        }

        // Acquire permit from tracker before sending
        // This provides backpressure - we won't send more than max_in_flight_messages
        let permit = self
            .tracker
            .in_flight_semaphore_clone()
            .acquire_owned()
            .await
            .map_err(|_| anyhow::anyhow!("Semaphore closed"))?;

        // Calculate message size for tracking
        let estimated_size = msg.payload().map(|p| p.len()).unwrap_or(0)
            + msg.key().map(|k| k.len()).unwrap_or(0)
            + topic.len();

        // Detach the message and track it
        let owned_msg = msg.detach();
        let ackable_msg = self
            .tracker
            .track_message(owned_msg, estimated_size, permit)
            .await;

        // Send to processor pool - they handle the actual processing
        if self.message_sender.send(ackable_msg).is_err() {
            error!("Processor pool channel closed, cannot send message");
            return Err(anyhow::anyhow!("Processor pool is dead"));
        }

        debug!(
            "Sent message to processor pool (topic: {}, partition: {}, offset: {})",
            topic, partition_num, offset
        );

        Ok(())
    }

    async fn commit_offsets(&self) -> Result<()> {
        info!("Starting offset commit process");

        // Get tracker statistics and publish metrics
        let stats = self.tracker.get_stats().await;
        stats.publish_metrics();

        info!(
            "Tracker stats before commit: in_flight={}, completed={}, failed={}, available_permits={}",
            stats.in_flight, stats.completed, stats.failed, self.tracker.available_permits()
        );

        // Get safe commit offsets from tracker (only commits completed messages)
        let safe_offsets = self.tracker.get_safe_commit_offsets().await;

        if safe_offsets.is_empty() {
            info!(
                "No safe offsets to commit - this may indicate messages are not being acknowledged"
            );
            return Ok(());
        }

        info!(
            "Found {} partition(s) with safe offsets to commit",
            safe_offsets.len()
        );

        // Build TopicPartitionList with safe offsets
        let mut topic_partition_list = rdkafka::TopicPartitionList::new();
        for (partition, offset) in safe_offsets {
            info!(
                "Adding safe commit offset: topic={}, partition={}, offset={} (will commit {})",
                partition.topic(),
                partition.partition_number(),
                offset,
                offset + 1
            );
            topic_partition_list.add_partition_offset(
                partition.topic(),
                partition.partition_number(),
                rdkafka::Offset::Offset(offset + 1),
            )?;
        }

        // Commit only the safe offsets
        match self
            .consumer
            .commit(&topic_partition_list, CommitMode::Async)
        {
            Ok(_) => {
                info!(
                    "Successfully committed offsets for {} partition(s)",
                    topic_partition_list.count()
                );
                Ok(())
            }
            Err(e) => {
                error!("Failed to commit safe offsets: {}", e);
                Err(e.into())
            }
        }
    }

    /// Get current tracker statistics
    pub async fn get_tracker_stats(&self) -> TrackerStats {
        self.tracker.get_stats().await
    }

    /// Get the underlying consumer (for advanced usage)
    pub fn inner_consumer(&self) -> &StreamConsumer<StatefulConsumerContext> {
        &self.consumer
    }
}
