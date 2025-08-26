use anyhow::Result;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::Message;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;
use tokio::time::timeout;
use tracing::{debug, error, info, warn};

use super::message::MessageProcessor;
use super::rebalance_handler::RebalanceHandler;
use super::stateful_context::StatefulConsumerContext;
use super::tracker::{InFlightTracker, TrackerStats};

/// Stateful Kafka consumer that coordinates with external state systems
/// This consumer ensures sequential offset commits and coordinated partition revocation
pub struct StatefulKafkaConsumer<P: MessageProcessor> {
    /// Kafka consumer instance with stateful context
    consumer: StreamConsumer<StatefulConsumerContext>,

    /// Message processor for handling business logic
    message_processor: Arc<P>,

    /// In-flight message tracker (owns the semaphore for backpressure)
    tracker: Arc<InFlightTracker>,

    /// How often to commit offsets
    commit_interval: Duration,

    /// Shutdown signal for graceful shutdown
    shutdown_rx: oneshot::Receiver<()>,
}

impl<P: MessageProcessor> StatefulKafkaConsumer<P> {
    /// Create a new stateful Kafka consumer with integrated tracker and context
    /// This is the recommended way to create consumers for production use
    pub fn from_config(
        config: &rdkafka::ClientConfig,
        rebalance_handler: Arc<dyn RebalanceHandler>,
        message_processor: Arc<P>,
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
            message_processor,
            tracker,
            commit_interval,
            shutdown_rx,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(mut self) -> Result<()> {
        info!("Starting stateful Kafka message consumption");

        let mut commit_interval = tokio::time::interval(self.commit_interval);
        // Publish metrics every 10 seconds for observability
        let mut metrics_interval = tokio::time::interval(Duration::from_secs(10));

        loop {
            // Process completions at the start of each loop iteration to keep counts accurate
            self.tracker.process_completions().await;

            tokio::select! {
                // Check for shutdown signal
                _ = &mut self.shutdown_rx => {
                    info!("Shutdown signal received, starting graceful shutdown");
                    break;
                }

                // Poll for messages
                msg_result = timeout(Duration::from_secs(1), self.consumer.recv()) => {
                    match msg_result {
                        Ok(Ok(msg)) => {
                            self.handle_message(msg).await?;
                            // Process completions after each message to keep counts accurate
                            self.tracker.process_completions().await;
                        }
                        Ok(Err(e)) => {
                            error!("Error receiving message: {}", e);
                            tokio::time::sleep(Duration::from_millis(100)).await;
                        }
                        Err(_) => {
                            // Timeout - continue
                            debug!("Consumer poll timeout");
                        }
                    }
                }

                // Publish metrics every 10 seconds
                _ = metrics_interval.tick() => {
                    // Process any pending completions first to get accurate stats
                    self.tracker.process_completions().await;

                    let stats = self.tracker.get_stats().await;
                    stats.publish_metrics();

                    // Also publish semaphore permit metrics from the tracker
                    metrics::gauge!("kafka_consumer_available_permits")
                        .set(self.tracker.available_permits() as f64);

                    debug!("Published metrics: {}, available_permits={}",
                        stats, self.tracker.available_permits());
                }

                // Commit offsets periodically
                _ = commit_interval.tick() => {
                    if let Err(e) = self.commit_offsets().await {
                        error!("Failed to commit offsets: {}", e);
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

        info!("Graceful shutdown completed");
        Ok(())
    }

    async fn handle_message<'a>(&self, msg: rdkafka::message::BorrowedMessage<'a>) -> Result<()> {
        let topic = msg.topic();
        let partition = msg.partition();
        let offset = msg.offset();

        // Check if partition is still active (not revoked)
        if !self.tracker.is_partition_active(topic, partition).await {
            warn!(
                "Skipping message from revoked partition {}:{} offset {}",
                topic, partition, offset
            );
            return Ok(());
        }

        // First check if we have permits available
        if self.tracker.available_permits() == 0 {
            debug!(
                "No permits available, applying backpressure. Topic {} partition {} offset {}. In-flight: {}",
                topic, partition, offset,
                self.tracker.in_flight_count().await
            );
            // Process completions to potentially free up permits
            self.tracker.process_completions().await;

            // Check again after processing completions
            if self.tracker.available_permits() == 0 {
                // Still no permits - apply backpressure by not consuming this message
                return Ok(());
            }
        }

        // Calculate size before detaching
        let estimated_size = msg.payload().map(|p| p.len()).unwrap_or(0)
            + msg.key().map(|k| k.len()).unwrap_or(0)
            + topic.len();

        // Try to acquire a permit BEFORE detaching the message
        // This way we never lose a message
        let permit = match tokio::time::timeout(
            Duration::from_secs(1),
            self.tracker.in_flight_semaphore_clone().acquire_owned(),
        )
        .await
        {
            Ok(Ok(permit)) => permit,
            Ok(Err(_)) => {
                error!("Semaphore was closed - this is a fatal error");
                return Err(anyhow::anyhow!("Semaphore closed"));
            }
            Err(_) => {
                // Timeout - apply backpressure
                debug!(
                    "Timeout acquiring permit, applying backpressure. Topic {} partition {} offset {}",
                    topic, partition, offset
                );
                return Ok(());
            }
        };

        // NOW we can safely detach since we have the permit
        let owned_msg = msg.detach();

        // Track the message and get back an AckableMessage that owns everything
        let ackable_msg = self
            .tracker
            .track_message(owned_msg, estimated_size, permit)
            .await;

        debug!(
            "Tracking message from topic {} partition {} offset {} (available permits: {})",
            topic,
            partition,
            offset,
            self.tracker.available_permits()
        );

        // Process message through user's processor
        match self.message_processor.process_message(ackable_msg).await {
            Ok(_) => {
                debug!(
                    "Successfully processed message from topic {} partition {} offset {}",
                    topic, partition, offset
                );
                // Note: AckableMessage handles the actual acking
            }
            Err(e) => {
                error!(
                    "Failed to process message from topic {} partition {} offset {}: {}",
                    topic, partition, offset, e
                );
                // Note: AckableMessage should handle nacking in this case
            }
        }

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
        for ((topic, partition), offset) in safe_offsets {
            info!(
                "Adding safe commit offset: topic={}, partition={}, offset={} (will commit {})",
                topic,
                partition,
                offset,
                offset + 1
            );
            topic_partition_list.add_partition_offset(
                &topic,
                partition,
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
