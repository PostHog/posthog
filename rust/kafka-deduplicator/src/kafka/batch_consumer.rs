use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use crate::kafka::batch_context::BatchConsumerContext;
use crate::kafka::batch_message::{Batch, BatchError, KafkaMessage};
use crate::kafka::metrics_consts::{BATCH_CONSUMER_KAFKA_ERRORS, BATCH_CONSUMER_MESSAGES_RECEIVED};
use crate::kafka::rebalance_handler::RebalanceHandler;
use crate::kafka::types::Partition;

use anyhow::anyhow;
use anyhow::{Context, Result};
use futures_util::StreamExt;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{CommitMode, Consumer, MessageStream, StreamConsumer};
use rdkafka::error::KafkaResult;
use rdkafka::message::Message;
use rdkafka::TopicPartitionList;
use serde::Deserialize;
use tokio::sync::mpsc::UnboundedSender;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

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
    sender: UnboundedSender<Batch<T>>,

    // shutdown signal from parent process which
    // we assume will be wrapping start_consumption
    // in a spawned thread
    shutdown_token: CancellationToken,
}

impl<T> BatchConsumer<T>
where
    T: for<'de> Deserialize<'de>,
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        config: &ClientConfig,
        rebalance_handler: Arc<dyn RebalanceHandler>,
        sender: UnboundedSender<Batch<T>>,
        shutdown_token: CancellationToken,
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
            sender,
            shutdown_token,
        })
    }

    /// Start consuming messages in a loop with graceful shutdown support
    pub async fn start_consumption(self) -> Result<()> {
        info!("Starting batch Kafka message consumption...");

        let batch_timeout = self.batch_timeout;
        let batch_size = self.batch_size;
        let mut commit_interval = tokio::time::interval(self.commit_interval);

        // consume the clients and channels needed to operate the loop
        let shutdown_token = self.shutdown_token.clone();
        let sender = self.sender;
        let consumer = self.consumer;
        let mut stream = consumer.stream();

        loop {
            tokio::select! {
                // Check for shutdown signal
                _ = shutdown_token.cancelled() => {
                    info!("Shutdown signal received, starting graceful shutdown");
                    break;
                }

                // Poll for messages
                batch_result = Self::consume_batch(&mut stream, shutdown_token.clone(), batch_size, batch_timeout) => {
                    match batch_result {
                        Ok(batch) => {
                            // track latest offsets with rdkafka consumer
                            Self::store_offsets(&consumer, &batch);
                            // if there are no errors or messages to report, skip sending
                            if batch.is_empty() {
                                continue;
                            }
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "success")
                            .increment(batch.message_count() as u64);
                            metrics::counter!(BATCH_CONSUMER_MESSAGES_RECEIVED, "status" => "error")
                            .increment(batch.error_count() as u64);

                            if let Err(e) = sender.send(batch) {
                                // TODO: stat this
                                error!("Error sending Batch for processing: {e}");
                            }
                        }

                        Err(e) => {
                            metrics::counter!(BATCH_CONSUMER_KAFKA_ERRORS).increment(1);
                            error!("Error consuming Batch from stream: {e}");
                        }
                    }
                }

                // Commit offsets periodically that we store after each batch
                // NOTE: this replicates stateful consumer direct commit handling
                // since I assume we will initially share a ClientConfig used by
                // stateful now when we transition. However, we can configure
                // rdkafka internal client to *autocommit but manually store* offsets
                // and keep the store-after-batch-created logic, and remove this manual
                // commit operation entirely once we transition to batch consumer
                _ = commit_interval.tick() => {
                    let _ = Self::commit_offsets(&consumer);
                }
            }
        }
        info!("Batch consumer loop shutting down...");

        // Drop the sender to signal no more messages
        drop(sender);
        info!("Graceful shutdown completed");

        Ok(())
    }

    // NOT FOR PROD - handy for integration smoke tests
    pub fn inner_consumer(&self) -> &StreamConsumer<BatchConsumerContext> {
        &self.consumer
    }

    /// best-effort attempt to store latest offsets seen in the supplied Batch
    fn store_offsets(consumer: &StreamConsumer<BatchConsumerContext>, batch: &Batch<T>) {
        let mut offsets = HashMap::<Partition, i64>::new();
        for kmsg in batch.get_messages() {
            let partition = kmsg.get_topic_partition();

            if let Some(current) = offsets.get(&partition) {
                if kmsg.get_offset() + 1 > *current {
                    offsets.insert(partition, kmsg.get_offset() + 1);
                }
            } else {
                offsets.insert(partition, kmsg.get_offset() + 1);
            }
        }

        let mut list = TopicPartitionList::new();
        for (partition, max_offset) in offsets {
            let _ = list.add_partition_offset(
                partition.topic(),
                partition.partition_number(),
                rdkafka::Offset::Offset(max_offset),
            );
        }

        let _ = consumer.store_offsets(&list);
    }

    fn commit_offsets(consumer: &StreamConsumer<BatchConsumerContext>) -> Result<()> {
        info!("Committing offsets...");

        // Commit only the safe offsets
        match consumer.commit_consumer_state(CommitMode::Async) {
            Ok(_) => {
                info!("Successfully committed offsets");
                Ok(())
            }
            Err(e) => {
                warn!("Failed to commit safe offsets: {e}");
                Err(e.into())
            }
        }
    }

    /// Consumes a batch of messages based on the configured batch size and timeout
    async fn consume_batch(
        stream: &mut MessageStream<'_, BatchConsumerContext>,
        shutdown_token: CancellationToken,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> KafkaResult<Batch<T>> {
        let mut batch = Batch::new_with_size_hint(batch_size);
        let mut batch_complete = tokio::time::interval(batch_timeout);

        loop {
            tokio::select! {
                // Exit if the parent process signalled shutdown
                _ = shutdown_token.cancelled() => {
                    break;
                }

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
                            // KafkaError - for now, let's return these and fail fast
                            return Err(e);
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

        Ok(batch)
    }
}
