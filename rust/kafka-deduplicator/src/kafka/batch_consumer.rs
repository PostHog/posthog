use std::sync::Arc;
use std::time::{Duration, Instant};

use crate::kafka::batch_context::BatchConsumerContext;
use crate::kafka::batch_message::{Batch, BatchError, KafkaMessage};
use crate::kafka::metrics_consts::{
    BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS, BATCH_CONSUMER_BATCH_FILL_RATIO,
    BATCH_CONSUMER_BATCH_SIZE, BATCH_CONSUMER_KAFKA_ERROR, BATCH_CONSUMER_MESSAGES_RECEIVED,
};
use crate::kafka::offset_tracker::OffsetTracker;
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;

use anyhow::anyhow;
use anyhow::{Context, Result};
use axum::async_trait;
use futures_util::StreamExt;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{CommitMode, Consumer, MessageStream, StreamConsumer};
use rdkafka::error::{KafkaError, KafkaResult, RDKafkaErrorCode};
use rdkafka::message::Message;
use rdkafka::TopicPartitionList;
use serde::Deserialize;
use tokio::sync::oneshot::Receiver;
use tokio::time::sleep;
use tracing::{error, info, warn};

#[async_trait]
pub trait BatchConsumerProcessor<T>: Send + Sync {
    async fn process_batch(&self, messages: Vec<KafkaMessage<T>>) -> Result<()>;
}

pub struct BatchConsumer<T> {
    consumer: StreamConsumer<BatchConsumerContext>,

    // group offset commit interval
    commit_interval: Duration,

    // batch configs - how big should batches get
    // and how long to wait before we publish one
    // for downstream processing
    batch_size: usize,
    batch_timeout: Duration,

    // where we send batches after consuming them
    processor: Arc<dyn BatchConsumerProcessor<T>>,

    // tracks processed offsets per partition for safe commits
    offset_tracker: Arc<OffsetTracker>,

    // shutdown signal from parent process which
    // we assume will be wrapping start_consumption
    // in a spawned thread
    shutdown_rx: Receiver<()>,
}

impl<T> BatchConsumer<T>
where
    T: for<'de> Deserialize<'de>,
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        config: &ClientConfig,
        rebalance_handler: Arc<dyn RebalanceHandler>,
        processor: Arc<dyn BatchConsumerProcessor<T>>,
        offset_tracker: Arc<OffsetTracker>,
        shutdown_rx: Receiver<()>,
        topic: &str,
        batch_size: usize,
        batch_timeout: Duration,
        commit_interval: Duration,
    ) -> Result<Self> {
        let consumer_ctx = BatchConsumerContext::new(rebalance_handler);

        // TODO: when we transition off stateful consumer, we must ensure we update the
        // incoming production-env ClientConfig to set:
        // - auto-store of offsets to DISABLED (we handle this directly after each batch in code)
        // - auto-commit ENABLED or DISABLED (if enabled, we can remove the manual commit
        //                                    operation in the batch consumer loop!)
        let consumer: StreamConsumer<BatchConsumerContext> = config
            .create_with_context(consumer_ctx)
            .context("Failed to create Kafka consumer")?;

        let err_msg = format!("Failed to subscribe to topic: {topic}");
        consumer.subscribe(&[topic]).context(err_msg)?;

        Ok(Self {
            consumer,
            commit_interval,
            batch_size,
            batch_timeout,
            processor,
            offset_tracker,
            shutdown_rx,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(mut self) -> Result<()> {
        info!("Starting batch Kafka message consumption...");

        let batch_timeout = self.batch_timeout;
        let batch_size = self.batch_size;
        let mut commit_interval = tokio::time::interval(self.commit_interval);

        let consumer = self.consumer;
        let mut stream = consumer.stream();

        loop {
            tokio::select! {
                // Check for shutdown signal
                _ = &mut self.shutdown_rx => {
                    info!("Shutdown signal received, starting graceful shutdown");
                    break;
                }

                // Poll for messages
                batch_result = Self::consume_batch(&mut stream, batch_size, batch_timeout) => {
                    match batch_result {
                        Ok((batch, collection_duration)) => {
                            // Record batch collection duration
                            metrics::histogram!(BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS)
                                .record(collection_duration.as_millis() as f64);

                            // if there are no errors or messages to report, skip sending
                            if batch.is_empty() {
                                continue;
                            }
                            let message_count = batch.message_count();
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "success")
                                .increment(message_count as u64);
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "error")
                                .increment(batch.error_count() as u64);
                            metrics::histogram!(BATCH_CONSUMER_BATCH_SIZE)
                                .record(message_count as f64);

                            // Record batch fill ratio (how full the batch was)
                            let fill_ratio = message_count as f64 / batch_size as f64;
                            metrics::histogram!(BATCH_CONSUMER_BATCH_FILL_RATIO)
                                .record(fill_ratio);

                            let (messages, _errors) = batch.unpack();
                            if let Err(e) = self.processor.process_batch(messages).await {
                                // TODO: stat this
                                error!("Error processing batch: {e}");
                            }
                        }

                        Err(e) => {
                            // Kafka error handler logs/stats these in detail prior to bubbling up here
                            return Err(e.into());
                        }
                    }
                }

                // Commit offsets periodically from the offset tracker
                // The offset tracker contains offsets that have been successfully processed
                // by partition workers, ensuring we only commit what's been processed
                _ = commit_interval.tick() => {
                    Self::commit_tracked_offsets(&consumer, &self.offset_tracker);
                }
            }
        }
        info!("Batch consumer loop shutting down...");

        info!("Graceful shutdown completed");

        Ok(())
    }

    async fn handle_kafka_error(e: KafkaError, current_count: u64) -> Option<KafkaError> {
        match &e {
            KafkaError::MessageConsumption(code) => {
                match code {
                    RDKafkaErrorCode::PartitionEOF => {
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "info"), ("error", "partition_eof"),]
                        )
                        .increment(1);
                    }
                    RDKafkaErrorCode::OperationTimedOut => {
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "info"), ("error", "op_timed_out"),]
                        )
                        .increment(1);
                    }
                    RDKafkaErrorCode::OffsetOutOfRange => {
                        // "auto.offset.reset" will trigger a seek to head or tail
                        // of the partition in coordination with the broker
                        warn!("Offset out of range - seeking to configured offset reset policy",);
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "info"), ("error", "offset_out_of_range"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(500)).await;
                    }
                    _ => {
                        warn!("Kafka consumer error: {code:?}");
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "warn"), ("error", "consumer"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(100 * current_count.min(10))).await;
                    }
                }

                None
            }

            KafkaError::MessageConsumptionFatal(code) => {
                error!("Fatal Kafka consumer error: {code:?}");
                metrics::counter!(
                    BATCH_CONSUMER_KAFKA_ERROR,
                    &[("level", "fatal"), ("error", "consumer"),]
                )
                .increment(1);

                Some(e)
            }

            // Connection issues
            KafkaError::Global(code) => {
                match code {
                    RDKafkaErrorCode::AllBrokersDown => {
                        warn!("All brokers down: {code:?} - waiting for reconnect");
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "warn"), ("error", "all_brokers_down"),]
                        )
                        .increment(1);
                        sleep(Duration::from_secs(current_count.min(5))).await;
                    }
                    RDKafkaErrorCode::BrokerTransportFailure => {
                        warn!("Broker transport failure: {code:?} - waiting for reconnect");
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "warn"), ("error", "broker_transport"),]
                        )
                        .increment(1);
                        sleep(Duration::from_secs(current_count.min(3))).await;
                    }
                    RDKafkaErrorCode::Authentication => {
                        error!("Authentication failed: {code:?}");
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "fatal"), ("error", "authentication"),]
                        )
                        .increment(1);
                        return Some(e);
                    }
                    _ => {
                        warn!("Global Kafka error: {code:?}");
                        metrics::counter!(
                            BATCH_CONSUMER_KAFKA_ERROR,
                            &[("level", "warn"), ("error", "global"),]
                        )
                        .increment(1);
                        sleep(Duration::from_millis(500 * current_count.min(6))).await;
                    }
                }

                None
            }

            // Shutdown signal
            KafkaError::Canceled => {
                info!("Consumer canceled - shutting down");
                metrics::counter!(
                    BATCH_CONSUMER_KAFKA_ERROR,
                    &[("level", "info"), ("error", "canceled"),]
                )
                .increment(1);

                Some(e)
            }

            // Other errors
            _ => {
                error!("Unexpected error: {:?}", e);
                metrics::counter!(
                    BATCH_CONSUMER_KAFKA_ERROR,
                    &[("level", "fatal"), ("error", "unexpected"),]
                )
                .increment(1);
                sleep(Duration::from_millis(100 * current_count.min(10))).await;

                None
            }
        }
    }

    // NOT FOR PROD - handy for integration smoke tests
    pub fn inner_consumer(&self) -> &StreamConsumer<BatchConsumerContext> {
        &self.consumer
    }

    /// Commit offsets from the offset tracker to Kafka
    ///
    /// This commits only offsets that have been successfully processed by partition
    /// workers, ensuring we never commit offsets for messages that haven't been processed.
    ///
    /// Commits are skipped during rebalancing to avoid committing offsets for partitions
    /// that may have been revoked.
    ///
    /// After a successful commit, updates the offset tracker's committed offsets which
    /// are used for checkpointing to track the true recovery point.
    fn commit_tracked_offsets(
        consumer: &StreamConsumer<BatchConsumerContext>,
        offset_tracker: &OffsetTracker,
    ) {
        let offsets = match offset_tracker.get_committable_offsets() {
            Ok(offsets) => offsets,
            Err(crate::kafka::offset_tracker::OffsetTrackerError::RebalanceInProgress) => {
                info!("Skipping offset commit during rebalancing");
                metrics::counter!(
                    crate::kafka::metrics_consts::OFFSET_TRACKER_COMMITS_SKIPPED_REBALANCING
                )
                .increment(1);
                return;
            }
        };

        if offsets.is_empty() {
            return;
        }

        let mut list = TopicPartitionList::new();
        for (partition, next_offset) in &offsets {
            let _ = list.add_partition_offset(
                partition.topic(),
                partition.partition_number(),
                rdkafka::Offset::Offset(*next_offset),
            );
        }

        // Use synchronous commit so we know exactly when offsets are committed.
        // This is important for checkpointing - we need to track the committed
        // offset (not just processed) for disaster recovery.
        match consumer.commit(&list, CommitMode::Sync) {
            Ok(_) => {
                info!("Committed offsets for {} partitions", offsets.len());
                // Update the offset tracker with the committed offsets
                // These are used for checkpointing to track the true recovery point
                offset_tracker.mark_committed(&offsets);
            }
            Err(e) => {
                warn!("Failed to commit tracked offsets: {e}");
            }
        }
    }

    /// Consumes a batch of messages based on the configured batch size and timeout.
    /// Returns the batch and the duration spent collecting it.
    async fn consume_batch(
        stream: &mut MessageStream<'_, BatchConsumerContext>,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> KafkaResult<(Batch<T>, Duration)> {
        let start = Instant::now();
        let mut batch = Batch::new_with_size_hint(batch_size);
        let mut batch_complete = tokio::time::interval(batch_timeout);
        let mut kafka_error_count = 0;

        loop {
            tokio::select! {
                // Exit if the batch timeout is reached before a full batch is collected
                _ = batch_complete.tick() => {
                    break;
                }

                // Try to get next message within the remaining batch time
                next_msg = stream.next() => {
                    match next_msg {
                        Some(Ok(borrowed_message)) => {
                            match KafkaMessage::<T>::from_borrowed_message(&borrowed_message) {
                                Ok(kafka_message) => {
                                    batch.push_message(kafka_message);
                                    kafka_error_count = 0;
                                }
                                Err(e) => {
                                    let wrapped_err = anyhow!("Error deserializing message: {e}");
                                    batch.push_error(BatchError::new(
                                        wrapped_err,
                                        Some(Partition::new(
                                            borrowed_message.topic().to_owned(),
                                            borrowed_message.partition(),
                                        )),
                                        Some(borrowed_message.offset()),
                                    ));
                                }
                            }
                        }
                        Some(Err(e)) => {
                            kafka_error_count += 1;
                            if let Some(ke) = Self::handle_kafka_error(e, kafka_error_count).await {
                                // only fatal, unhandleable, or retriable errors that have
                                // exhausted attempts will be returned, which breaks the
                                // consume loop and ends processing, causing pod to reset
                                return Err(ke);
                            }
                        }
                        None => {
                            // Stream ended - return what we have
                            break;
                        }
                    }

                    // if the batch is now at size, bail out and return it
                    if batch.message_count() >= batch_size {
                        break;
                    }
                }
            }
        }

        Ok((batch, start.elapsed()))
    }
}
