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
use crate::dispatcher::Dispatcher;
use crate::transport::HttpTransport;
use crate::types::SerializedKafkaMessage;

/// Statistics gathered while collecting a batch, used to emit parity metrics.
struct BatchStats {
    /// Max Kafka message timestamp (ms) per (topic, partition) — for `latestOffsetTimestampGauge`.
    latest_kafka_ts: HashMap<(String, i32), i64>,
    /// Max ingestion lag (ms) per (topic, partition) — for `ingestionLagGauge`.
    max_lag_ms: HashMap<(String, i32), i64>,
    /// Per-message (partition, lag_ms) pairs — for `ingestionLagHistogram`.
    message_lags_ms: Vec<(i32, i64)>,
    /// Total byte size of message payloads — for `consumerBatchSizeKb`.
    total_bytes: usize,
}

impl BatchStats {
    fn new() -> Self {
        Self {
            latest_kafka_ts: HashMap::new(),
            max_lag_ms: HashMap::new(),
            message_lags_ms: Vec::new(),
            total_bytes: 0,
        }
    }
}

/// Output of `collect_batch`.
struct CollectedBatch {
    messages: Vec<SerializedKafkaMessage>,
    offsets: HashMap<(String, i32), i64>,
    stats: BatchStats,
}

/// Options for constructing an [`IngestionConsumer`] from pre-built parts.
/// Used in integration tests where the Kafka consumer is created externally.
pub struct IngestionConsumerOptions {
    pub batch_size: usize,
    pub batch_timeout: Duration,
    pub group_id: String,
}

/// The main consumer loop: reads from Kafka, routes messages by distinct_id
/// via the health-aware Dispatcher, dispatches sub-batches to workers over
/// HTTP, and commits offsets only after all workers ACK.
pub struct IngestionConsumer {
    consumer: StreamConsumer,
    dispatcher: Arc<Dispatcher>,
    transport: Arc<HttpTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_timeout: Duration,
    handle: Handle,
    group_id: String,
}

impl IngestionConsumer {
    /// Constructs a consumer from pre-built parts. Useful in integration tests
    /// where the Kafka consumer is created and subscribed externally.
    pub fn from_parts(
        consumer: StreamConsumer,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<HttpTransport>,
        worker_urls: Vec<String>,
        options: IngestionConsumerOptions,
        handle: Handle,
    ) -> Self {
        Self {
            consumer,
            dispatcher,
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_timeout: options.batch_timeout,
            handle,
            group_id: options.group_id,
        }
    }

    pub fn new(
        config: &Config,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<HttpTransport>,
        handle: Handle,
    ) -> anyhow::Result<Self> {
        let worker_urls = config.worker_urls();
        if worker_urls.is_empty() {
            anyhow::bail!("No worker addresses configured");
        }

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
            dispatcher,
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            handle,
            group_id: config.ingestion_consumer_group_id.clone(),
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

    /// Collect a batch, assign it via the Dispatcher, scatter to workers,
    /// gather results, feed passive health signals, and commit offsets.
    async fn process_batch(&self) -> anyhow::Result<usize> {
        let collected = self.collect_batch().await?;
        if collected.messages.is_empty() {
            return Ok(0);
        }

        let batch_size = collected.messages.len();
        let batch_id = make_batch_id();
        let start = Instant::now();

        counter!("ingestion_consumer_messages_received_total").increment(batch_size as u64);
        gauge!("ingestion_consumer_batch_size").set(batch_size as f64);

        // Batch size distribution — matches Node.js `consumerBatchSize` histogram.
        histogram!("consumerBatchSize").record(batch_size as f64);
        histogram!("consumerBatchSizeKb").record(collected.stats.total_bytes as f64 / 1024.0);

        // Per-partition latest committed timestamp — matches Node.js `latestOffsetTimestampGauge`.
        for ((topic, partition), ts_ms) in &collected.stats.latest_kafka_ts {
            gauge!(
                "latestOffsetTimestampGauge",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
                "groupId" => self.group_id.clone()
            )
            .set(*ts_ms as f64);
        }

        // Per-partition ingestion lag gauge — matches Node.js `ingestionLagGauge`.
        for ((topic, partition), max_lag) in &collected.stats.max_lag_ms {
            gauge!(
                "ingestionLagGauge",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
                "groupId" => self.group_id.clone()
            )
            .set(*max_lag as f64);
        }

        // Per-message lag histogram — matches Node.js `ingestionLagHistogram`.
        for (partition, lag_ms) in &collected.stats.message_lags_ms {
            histogram!(
                "ingestionLagHistogram",
                "groupId" => self.group_id.clone(),
                "partition" => partition.to_string()
            )
            .record(*lag_ms as f64);
        }

        // Health-aware assignment: groups by routing key, honors stickiness,
        // skips unhealthy/dead workers.
        let sub_batches = self.dispatcher.assign(collected.messages);

        if sub_batches.is_empty() {
            counter!("ingestion_consumer_no_healthy_workers_total").increment(1);
            anyhow::bail!("No healthy workers available to route batch");
        }

        // Scatter: send sub-batches to workers in parallel.
        let mut handles = Vec::with_capacity(sub_batches.len());
        for sub_batch in sub_batches {
            let transport = Arc::clone(&self.transport);
            let dispatcher = Arc::clone(&self.dispatcher);
            let url = self.worker_urls[sub_batch.worker_idx].clone();
            let bid = batch_id.clone();
            let worker_idx = sub_batch.worker_idx;
            let routing_keys = sub_batch.routing_keys.clone();

            handles.push(tokio::spawn(async move {
                let result = transport.send_batch(&url, &bid, sub_batch.messages).await;
                let is_error = result.is_err();

                dispatcher.on_sub_batch_resolved(worker_idx, &routing_keys);
                dispatcher.record_send_outcome(worker_idx, is_error);

                result
            }));
        }

        // Gather: wait for all workers to ACK.
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

        // All workers ACK'd — commit offsets.
        self.commit_offsets(&collected.offsets)?;

        let elapsed = start.elapsed();
        histogram!("ingestion_consumer_batch_processing_duration_seconds")
            .record(elapsed.as_secs_f64());
        counter!("ingestion_consumer_messages_processed_total").increment(total_accepted as u64);

        Ok(batch_size)
    }

    /// Collect messages from Kafka up to batch_size or batch_timeout.
    async fn collect_batch(&self) -> anyhow::Result<CollectedBatch> {
        let mut messages = Vec::with_capacity(self.batch_size);
        let mut offsets: HashMap<(String, i32), i64> = HashMap::new();
        let mut stats = BatchStats::new();
        let deadline = Instant::now() + self.batch_timeout;
        let batch_start_ms = current_time_ms();

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

                    let kafka_ts = borrowed_message.timestamp().to_millis().unwrap_or(0);
                    stats
                        .latest_kafka_ts
                        .entry((topic.clone(), partition))
                        .and_modify(|t| {
                            if kafka_ts > *t {
                                *t = kafka_ts;
                            }
                        })
                        .or_insert(kafka_ts);

                    let payload_bytes = borrowed_message.payload().map(|v| v.len()).unwrap_or(0);
                    stats.total_bytes += payload_bytes;

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

                    if let Some(capture_ms) = headers.get("now").and_then(|v| parse_now_ms(v)) {
                        let lag_ms = (batch_start_ms - capture_ms).max(0);
                        stats
                            .max_lag_ms
                            .entry((topic.clone(), partition))
                            .and_modify(|l| {
                                if lag_ms > *l {
                                    *l = lag_ms;
                                }
                            })
                            .or_insert(lag_ms);
                        stats.message_lags_ms.push((partition, lag_ms));
                    }

                    let serialized = SerializedKafkaMessage {
                        topic,
                        partition,
                        offset,
                        timestamp: kafka_ts,
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

        Ok(CollectedBatch {
            messages,
            offsets,
            stats,
        })
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

fn current_time_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

/// Parse an ISO 8601 / RFC 3339 timestamp string into milliseconds since epoch.
/// Returns `None` if the string is missing or unparseable.
fn parse_now_ms(value: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|dt| dt.timestamp_millis())
}
