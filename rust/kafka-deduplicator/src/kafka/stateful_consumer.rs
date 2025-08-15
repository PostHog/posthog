use anyhow::Result;
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::Message;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{oneshot, Semaphore};
use tokio::time::timeout;
use tracing::{debug, error, info, warn};

use super::message::{AckableMessage, MessageProcessor};
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

    /// In-flight message tracker
    tracker: Arc<InFlightTracker>,

    /// Global semaphore to limit total in-flight messages
    global_semaphore: Arc<Semaphore>,

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
        message_processor: P,
        max_in_flight_messages: usize,
        commit_interval: Duration,
        shutdown_rx: oneshot::Receiver<()>,
    ) -> Result<Self> {
        let tracker = Arc::new(InFlightTracker::new());
        let context = StatefulConsumerContext::new(rebalance_handler, tracker.clone());

        let consumer: StreamConsumer<StatefulConsumerContext> =
            config.create_with_context(context)?;

        let global_semaphore = Arc::new(Semaphore::new(max_in_flight_messages));

        Ok(Self {
            consumer,
            message_processor: Arc::new(message_processor),
            tracker,
            global_semaphore,
            commit_interval,
            shutdown_rx,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(mut self) -> Result<()> {
        info!("Starting stateful Kafka message consumption");

        let mut commit_interval = tokio::time::interval(self.commit_interval);

        loop {
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

        // Acquire permit to control backpressure with timeout to prevent deadlocks
        let _permit = timeout(Duration::from_secs(30), self.global_semaphore.acquire())
            .await
            .map_err(|_| {
                anyhow::anyhow!("Timeout acquiring semaphore permit after 30s - possible deadlock")
            })??;

        debug!(
            "Processing message from topic {} partition {} offset {}",
            topic, partition, offset
        );

        // Convert to owned message and create ackable wrapper
        let owned_msg = msg.detach();
        let estimated_size = owned_msg.payload().map(|p| p.len()).unwrap_or(0)
            + owned_msg.key().map(|k| k.len()).unwrap_or(0)
            + topic.len();

        let (_message_id, message_handle) =
            self.tracker.track_message(&owned_msg, estimated_size).await;

        let ackable_msg = AckableMessage::new(owned_msg, message_handle);

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
        debug!("Committing offsets");

        // Get tracker statistics
        let stats = self.tracker.get_stats().await;
        debug!("Tracker stats before commit: in_flight={}", stats.in_flight);

        // Get safe commit offsets from tracker (only commits completed messages)
        let safe_offsets = self.tracker.get_safe_commit_offsets().await;

        if safe_offsets.is_empty() {
            debug!("No safe offsets to commit");
            return Ok(());
        }

        // Build TopicPartitionList with safe offsets
        let mut topic_partition_list = rdkafka::TopicPartitionList::new();
        for ((topic, partition), offset) in safe_offsets {
            debug!(
                "Adding safe commit offset: {}:{} -> {}",
                topic,
                partition,
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
                debug!("Successfully committed safe offsets");
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
