use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::TopicPartitionList;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::router::MessageRouter;
use crate::transport::HttpTransport;
use crate::types::SerializedKafkaMessage;

/// The main consumer loop: reads from Kafka, routes messages by distinct_id,
/// dispatches sub-batches to workers via HTTP, and commits offsets on ACK.
///
/// This is the single-in-flight-batch version (Stage 2). It processes one
/// batch at a time — no concurrent batch tracking or in-flight stickiness.
pub struct IngestionConsumer {
    consumer: StreamConsumer,
    router: MessageRouter,
    transport: Arc<HttpTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_timeout: Duration,
    handle: Handle,
}

impl IngestionConsumer {
    pub fn new(
        config: &Config,
        transport: Arc<HttpTransport>,
        handle: Handle,
    ) -> anyhow::Result<Self> {
        let worker_urls = config.worker_urls();
        if worker_urls.is_empty() {
            anyhow::bail!("No worker addresses configured");
        }

        let router = MessageRouter::new(worker_urls.len());

        let client_config = config.build_consumer_config();
        let consumer: StreamConsumer = client_config.create()?;
        consumer.subscribe(&[&config.ingestion_consumer_consume_topic])?;

        info!(
            topic = %config.ingestion_consumer_consume_topic,
            group = %config.ingestion_consumer_group_id,
            workers = worker_urls.len(),
            batch_size = config.consumer_batch_size,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer,
            router,
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            handle,
        })
    }

    /// Run the consumer loop until shutdown is signalled via the lifecycle handle.
    /// Waits for all workers to be ready before starting to consume from Kafka.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();

        info!("Waiting for workers to be ready");
        if let Err(err) = self
            .transport
            .wait_for_workers_ready(&self.worker_urls, &self.handle)
            .await
        {
            error!(error = %err, "Failed waiting for workers");
            self.handle
                .signal_failure("Workers not ready before shutdown".to_string());
            return;
        }

        info!("Consumer loop starting");

        loop {
            tokio::select! {
                _ = self.handle.shutdown_recv() => {
                    info!("Shutdown signal received, draining");
                    break;
                }
                result = self.process_batch() => {
                    match result {
                        Ok(count) => {
                            if count > 0 {
                                self.handle.report_healthy();
                                counter!("ingestion_consumer_batches_processed_total").increment(1);
                            }
                        }
                        Err(err) => {
                            error!(error = %err, "Batch processing failed");
                            counter!("ingestion_consumer_batch_errors_total").increment(1);
                            tokio::time::sleep(Duration::from_secs(1)).await;
                        }
                    }
                }
            }
        }

        info!("Consumer loop stopped");
    }

    /// Collect a batch, route it, scatter to workers, gather ACKs, commit offsets.
    async fn process_batch(&self) -> anyhow::Result<usize> {
        let (messages, offsets) = self.collect_batch().await?;
        if messages.is_empty() {
            return Ok(0);
        }

        let batch_size = messages.len();
        let batch_id = make_batch_id();
        let start = Instant::now();

        counter!("ingestion_consumer_messages_received_total").increment(batch_size as u64);
        gauge!("ingestion_consumer_batch_size").set(batch_size as f64);

        // Route messages to workers
        let groups = self.router.route_batch(messages);

        // Scatter: send sub-batches to workers in parallel
        let mut handles = Vec::with_capacity(groups.len());
        for (worker_idx, sub_batch) in groups {
            let transport = self.transport.clone();
            let url = self.worker_urls[worker_idx].clone();
            let bid = batch_id.clone();
            handles.push(tokio::spawn(async move {
                transport.send_batch(&url, &bid, sub_batch).await
            }));
        }

        // Gather: wait for all workers to ACK
        let mut total_accepted = 0u32;
        for handle in handles {
            let result = handle.await??;
            total_accepted += result;
        }

        if total_accepted < batch_size as u32 {
            anyhow::bail!(
                "Workers accepted {total_accepted}/{batch_size} messages — not committing offsets"
            );
        }

        // All workers ACK'd all messages — commit offsets
        self.commit_offsets(&offsets)?;

        let elapsed = start.elapsed();
        histogram!("ingestion_consumer_batch_processing_duration_seconds")
            .record(elapsed.as_secs_f64());
        counter!("ingestion_consumer_messages_processed_total").increment(total_accepted as u64);

        Ok(batch_size)
    }

    /// Collect messages from Kafka up to batch_size or batch_timeout.
    async fn collect_batch(
        &self,
    ) -> anyhow::Result<(Vec<SerializedKafkaMessage>, HashMap<(String, i32), i64>)> {
        let mut messages = Vec::with_capacity(self.batch_size);
        let mut offsets: HashMap<(String, i32), i64> = HashMap::new();
        let deadline = Instant::now() + self.batch_timeout;

        let mut stream = self.consumer.stream();

        loop {
            if messages.len() >= self.batch_size {
                break;
            }

            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }

            match tokio::time::timeout(remaining, stream.next()).await {
                Ok(Some(Ok(borrowed_message))) => {
                    let topic = borrowed_message.topic().to_string();
                    let partition = borrowed_message.partition();
                    let offset = borrowed_message.offset();

                    offsets
                        .entry((topic.clone(), partition))
                        .and_modify(|o| {
                            if offset > *o {
                                *o = offset;
                            }
                        })
                        .or_insert(offset);

                    let mut headers = HashMap::new();
                    if let Some(rdkafka_headers) = borrowed_message.headers() {
                        use rdkafka::message::Headers;
                        for i in 0..rdkafka_headers.count() {
                            let header = rdkafka_headers.get(i);
                            if let Some(value) = header.value {
                                if let Ok(value_str) = std::str::from_utf8(value) {
                                    headers.insert(header.key.to_string(), value_str.to_string());
                                }
                            }
                        }
                    }

                    let serialized = SerializedKafkaMessage {
                        topic,
                        partition,
                        offset,
                        timestamp: borrowed_message.timestamp().to_millis().unwrap_or(0),
                        key: borrowed_message
                            .key()
                            .and_then(|k| std::str::from_utf8(k).ok())
                            .map(|s| s.to_string()),
                        value: borrowed_message
                            .payload()
                            .and_then(|v| std::str::from_utf8(v).ok())
                            .map(|s| s.to_string()),
                        headers,
                    };

                    messages.push(serialized);
                }
                Ok(Some(Err(err))) => {
                    warn!(error = %err, "Kafka recv error");
                    counter!("ingestion_consumer_kafka_errors_total").increment(1);
                    break;
                }
                Ok(None) => break,
                Err(_) => break, // Timeout
            }
        }

        Ok((messages, offsets))
    }

    /// Commit the max offset for each topic-partition.
    fn commit_offsets(&self, offsets: &HashMap<(String, i32), i64>) -> anyhow::Result<()> {
        if offsets.is_empty() {
            return Ok(());
        }

        let mut tpl = TopicPartitionList::new();
        for ((topic, partition), offset) in offsets {
            // Commit offset + 1 (Kafka convention: committed offset = next to read)
            tpl.add_partition_offset(topic, *partition, rdkafka::Offset::Offset(offset + 1))?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);

        Ok(())
    }
}

fn make_batch_id() -> String {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let rand: u32 = rand::random();
    format!("{ts:x}-{rand:08x}")
}
