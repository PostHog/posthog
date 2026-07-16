use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::{Offset, TopicPartitionList};
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::discovery::DiscoveryMode;
use crate::dispatcher::{Dispatcher, SubBatch};
use crate::order_sentinel::{CommitSentinel, OffsetSpan, SentinelContext};
use crate::transport::HttpTransport;
use crate::types::SerializedKafkaMessage;

/// Statistics gathered while collecting a batch, used to emit parity metrics.
struct BatchStats {
    /// Max Kafka message timestamp (ms) per (topic, partition) — for `latest_processed_timestamp_ms`.
    latest_kafka_ts: HashMap<(String, i32), i64>,
    /// Max ingestion lag (ms) per (topic, partition) — for `ingestion_lag_ms`.
    max_lag_ms: HashMap<(String, i32), i64>,
    /// Per-message (partition, lag_ms) pairs — for `ingestion_lag_ms_histogram`.
    message_lags_ms: Vec<(i32, i64)>,
    /// Total byte size of message payloads — for `consumer_batch_size_kb`.
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
    offsets: HashMap<(String, i32), OffsetSpan>,
    stats: BatchStats,
}

struct ProcessedBatch {
    offsets: HashMap<(String, i32), OffsetSpan>,
    stats: BatchStats,
    /// Messages accepted so far. Deferred groups (keys whose worker was
    /// draining/dead) are flushed in `complete_oldest_batch`, which adds to this.
    total_accepted: u32,
    /// Total messages in the batch; the batch commits only once `total_accepted`
    /// reaches it (i.e. all deferred groups have been flushed and ACKed).
    batch_size: u32,
    elapsed: Duration,
}

struct InFlightBatch {
    batch_id: String,
    handle: JoinHandle<anyhow::Result<ProcessedBatch>>,
}

/// Options for constructing an [`IngestionConsumer`] from pre-built parts.
/// Used in integration tests where the Kafka consumer is created externally.
pub struct IngestionConsumerOptions {
    pub batch_size: usize,
    pub batch_timeout: Duration,
    pub max_in_flight_batches: usize,
    pub group_id: String,
    /// Upper bound on how long `complete_oldest_batch` retries flushing a batch's
    /// deferred groups before failing the batch. `new` takes it from
    /// `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS` (default 60s).
    pub deferred_flush_timeout: Duration,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    pub debug_recorder: Option<Arc<DebugRecorder>>,
}

/// The main consumer loop: reads from Kafka, routes messages by distinct_id
/// via the health-aware Dispatcher, dispatches sub-batches to workers over
/// HTTP, and commits offsets only after all workers ACK.
pub struct IngestionConsumer {
    consumer: Arc<StreamConsumer<SentinelContext>>,
    dispatcher: Arc<Dispatcher>,
    transport: Arc<HttpTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_timeout: Duration,
    max_in_flight_batches: usize,
    deferred_flush_timeout: Duration,
    handle: Handle,
    group_id: String,
    /// Validates commit contiguity/monotonicity per partition. Shared with the
    /// consumer's [`SentinelContext`], which resets baselines on rebalance.
    commit_sentinel: Arc<CommitSentinel>,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
}

impl IngestionConsumer {
    /// Constructs a consumer from pre-built parts. Useful in integration tests
    /// where the Kafka consumer is created and subscribed externally.
    pub fn from_parts(
        consumer: StreamConsumer<SentinelContext>,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<HttpTransport>,
        worker_urls: Vec<String>,
        options: IngestionConsumerOptions,
        handle: Handle,
    ) -> Self {
        // Share the context's commit sentinel so rebalance callbacks reset the
        // same baselines the commit path checks against.
        let commit_sentinel = consumer.context().commit_sentinel();
        Self {
            commit_sentinel,
            debug_recorder: options.debug_recorder,
            consumer: Arc::new(consumer),
            dispatcher,
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_timeout: options.batch_timeout,
            max_in_flight_batches: options.max_in_flight_batches.max(1),
            deferred_flush_timeout: options.deferred_flush_timeout,
            handle,
            group_id: options.group_id,
        }
    }

    pub fn new(
        config: &Config,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<HttpTransport>,
        handle: Handle,
        debug_recorder: Option<Arc<DebugRecorder>>,
    ) -> anyhow::Result<Self> {
        // In endpointslice mode the worker set comes from discovery, so there is
        // no static readiness list — main gates startup on the first discovered
        // worker. In static mode we keep the configured list for readiness.
        let worker_urls = match config.worker_discovery_mode {
            DiscoveryMode::Static => config.worker_urls(),
            DiscoveryMode::EndpointSlice => Vec::new(),
        };
        if config.worker_discovery_mode == DiscoveryMode::Static && worker_urls.is_empty() {
            anyhow::bail!("No worker addresses configured");
        }

        let client_config = config.build_consumer_config();
        let commit_sentinel = Arc::new(CommitSentinel::new());
        commit_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        let key_sentinel = dispatcher.key_order_sentinel();
        key_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        let context = SentinelContext::new(Arc::clone(&commit_sentinel), key_sentinel);
        let consumer: StreamConsumer<SentinelContext> =
            client_config.create_with_context(context)?;
        consumer.subscribe(&[&config.ingestion_consumer_consume_topic])?;

        info!(
            topic = %config.ingestion_consumer_consume_topic,
            group = %config.ingestion_consumer_group_id,
            workers = worker_urls.len(),
            batch_size = config.consumer_batch_size,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer: Arc::new(consumer),
            commit_sentinel,
            debug_recorder,
            dispatcher,
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            max_in_flight_batches: config.consumer_max_background_tasks.max(1),
            deferred_flush_timeout: Duration::from_millis(
                config.consumer_deferred_flush_timeout_ms,
            ),
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
        record_if(&self.debug_recorder, || DebugEventKind::ConsumerStarted {
            group_id: self.group_id.clone(),
            workers: self.worker_urls.clone(),
        });

        // Verify async commits actually land: librdkafka drops the result of
        // manual async commits (see the note on SentinelContext), so poll the
        // broker's committed offsets instead. Aborted on drop so a consumer
        // torn down mid-test doesn't keep the rdkafka client alive.
        let _commit_monitor = AbortOnDrop(tokio::spawn(run_commit_monitor(
            Arc::clone(&self.consumer),
            Arc::clone(&self.commit_sentinel),
            self.handle.clone(),
        )));

        let mut in_flight_batches = VecDeque::new();
        let mut accepting_new_batches = true;

        while accepting_new_batches || !in_flight_batches.is_empty() {
            // Consumer-level concurrency: how many Kafka batches are being
            // processed in parallel, bounded by `max_in_flight_batches`.
            gauge!("ingestion_consumer_in_flight_batches").set(in_flight_batches.len() as f64);

            if accepting_new_batches && in_flight_batches.len() < self.max_in_flight_batches {
                tokio::select! {
                    _ = self.handle.shutdown_recv() => {
                        info!(
                            in_flight = in_flight_batches.len(),
                            "Shutdown signal received, draining in-flight batches"
                        );
                        accepting_new_batches = false;
                    }
                    result = self.collect_batch() => {
                        let collected = match result {
                            Ok(collected) => collected,
                            Err(err) => {
                                self.fail_batch_processing(err);
                                return;
                            }
                        };

                        if collected.messages.is_empty() {
                            self.handle.report_healthy();
                            if in_flight_batches.is_empty() {
                                continue;
                            }
                        } else {
                            in_flight_batches.push_back(self.spawn_batch_processing(collected));
                            self.handle.report_healthy();

                            if in_flight_batches.len() < self.max_in_flight_batches {
                                continue;
                            }
                        }
                    }
                }
            }

            if let Err(err) = self.complete_oldest_batch(&mut in_flight_batches).await {
                self.fail_batch_processing(err);
                return;
            }
        }

        info!("Consumer loop stopped");
    }

    fn spawn_batch_processing(&self, collected: CollectedBatch) -> InFlightBatch {
        let batch_size = collected.messages.len();
        let batch_id = make_batch_id();
        record_if(&self.debug_recorder, || DebugEventKind::BatchDispatched {
            batch_id: batch_id.clone(),
            messages: batch_size,
            partitions: debug_partition_offsets(&collected.offsets, &collected.stats.max_lag_ms),
        });
        let task_batch_id = batch_id.clone();
        let dispatcher = Arc::clone(&self.dispatcher);
        let transport = Arc::clone(&self.transport);
        let group_id = self.group_id.clone();
        let max_batch_size = self.batch_size;

        let handle = tokio::spawn(async move {
            Self::process_collected_batch(
                collected,
                task_batch_id,
                dispatcher,
                transport,
                group_id,
                max_batch_size,
            )
            .await
        });

        info!(
            batch_id = %batch_id,
            messages = batch_size,
            "Kafka batch dispatched"
        );

        InFlightBatch { batch_id, handle }
    }

    async fn complete_oldest_batch(
        &self,
        in_flight_batches: &mut VecDeque<InFlightBatch>,
    ) -> anyhow::Result<()> {
        let Some(batch) = in_flight_batches.pop_front() else {
            return Ok(());
        };

        let batch_id = batch.batch_id.clone();
        let mut processed = self.await_processed_batch(batch).await?;

        // Flush this batch's deferred groups (keys whose worker was draining/dead)
        // in order, re-routing them to healthy workers. Doing it here — serialized,
        // oldest batch first — preserves per-distinct_id order across batches. The
        // batch isn't committable until all its messages are accepted.
        self.flush_deferred(&batch_id, &mut processed).await?;

        if processed.total_accepted < processed.batch_size {
            anyhow::bail!(
                "accepted {}/{} messages — not committing offsets",
                processed.total_accepted,
                processed.batch_size
            );
        }

        // Commit only the oldest completed batch. Later successful batches stay
        // uncommitted behind any earlier failed batch, preserving at-least-once
        // delivery across worker or pipeline failures.
        self.commit_offsets(&processed.offsets)?;
        emit_latest_processed_timestamp_metrics(&processed.stats, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::BatchCommitted {
            batch_id: batch_id.clone(),
            accepted: processed.total_accepted,
            duration_ms: processed.elapsed.as_millis() as u64,
            partitions: debug_partition_offsets(&processed.offsets, &processed.stats.max_lag_ms),
        });

        histogram!("ingestion_consumer_batch_processing_duration_seconds")
            .record(processed.elapsed.as_secs_f64());
        counter!("ingestion_consumer_messages_processed_total")
            .increment(processed.total_accepted as u64);
        counter!("ingestion_consumer_batches_processed_total").increment(1);
        self.handle.report_healthy();

        Ok(())
    }

    async fn await_processed_batch(&self, batch: InFlightBatch) -> anyhow::Result<ProcessedBatch> {
        let batch_id = batch.batch_id;
        let mut handle = batch.handle;
        let mut heartbeat = tokio::time::interval(Duration::from_secs(10));

        loop {
            tokio::select! {
                result = &mut handle => {
                    let processed = result??;
                    info!(batch_id = %batch_id, "Kafka batch processing completed");
                    return Ok(processed);
                }
                _ = heartbeat.tick() => {
                    self.handle.report_healthy();
                }
            }
        }
    }

    /// Flush a completed batch's deferred groups (keys whose worker was
    /// draining/dead), re-routing them to healthy workers and accumulating the
    /// accepted count. Retries with backoff while a flush can't route (no healthy
    /// worker yet), bounded by `deferred_flush_timeout`. Called serialized,
    /// oldest-first, so a key's deferred messages flush in Kafka order.
    async fn flush_deferred(
        &self,
        batch_id: &str,
        processed: &mut ProcessedBatch,
    ) -> anyhow::Result<()> {
        if !self.dispatcher.has_deferred(batch_id) {
            return Ok(());
        }
        let deadline = Instant::now() + self.deferred_flush_timeout;
        while self.dispatcher.has_deferred(batch_id) {
            // Bound the whole loop, not just the no-healthy-worker branch: a
            // flapping worker (visible in `healthy_workers` but failing sends)
            // re-defers on every scatter and would otherwise spin here forever,
            // pinning this batch's offsets indefinitely.
            if Instant::now() >= deadline {
                anyhow::bail!("deferred messages could not be flushed within timeout");
            }
            let sub_batches = self.dispatcher.flush_deferred(batch_id);
            if sub_batches.is_empty() {
                // Nothing routable right now (no healthy worker) — wait and retry.
                tokio::select! {
                    _ = self.handle.shutdown_recv() => {
                        anyhow::bail!("shutdown while flushing deferred messages");
                    }
                    _ = tokio::time::sleep(Duration::from_millis(200)) => {}
                }
                continue;
            }
            processed.total_accepted += Self::scatter(
                &self.dispatcher,
                &self.transport,
                batch_id,
                sub_batches,
                true,
            )
            .await?;
        }
        Ok(())
    }

    fn fail_batch_processing(&self, err: anyhow::Error) {
        error!(error = %err, "Batch processing failed");
        counter!("ingestion_consumer_batch_errors_total").increment(1);
        record_if(&self.debug_recorder, || DebugEventKind::BatchFailed {
            batch_id: None,
            error: format!("{err:#}"),
        });
        self.handle
            .signal_failure(format!("Batch processing failed: {err:#}"));
    }

    /// Assign a collected batch via the Dispatcher, scatter to workers, gather
    /// results, and feed passive health signals. Offset commits happen later,
    /// in Kafka batch order, in `complete_oldest_batch`.
    async fn process_collected_batch(
        collected: CollectedBatch,
        batch_id: String,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<HttpTransport>,
        group_id: String,
        max_batch_size: usize,
    ) -> anyhow::Result<ProcessedBatch> {
        let batch_size = collected.messages.len();
        let start = Instant::now();

        counter!("ingestion_consumer_messages_received_total").increment(batch_size as u64);
        gauge!("ingestion_consumer_batch_size").set(batch_size as f64);

        // Batch fill ratio (batch size / configured max) — matches Node.js
        // `consumer_batch_utilization`. A useful scaling signal: sustained high
        // utilization means batches are saturating and the consumer is demand-bound.
        if max_batch_size > 0 {
            gauge!("consumer_batch_utilization", "groupId" => group_id.clone())
                .set(batch_size as f64 / max_batch_size as f64);
        }

        // Batch size distribution — matches Node.js `consumer_batch_size` histogram.
        histogram!("consumer_batch_size").record(batch_size as f64);
        histogram!("consumer_batch_size_kb").record(collected.stats.total_bytes as f64 / 1024.0);

        // Per-partition ingestion lag gauge — matches Node.js `ingestion_lag_ms`.
        for ((topic, partition), max_lag) in &collected.stats.max_lag_ms {
            gauge!(
                "ingestion_lag_ms",
                "topic" => topic.clone(),
                "partition" => partition.to_string(),
                "groupId" => group_id.clone()
            )
            .set(*max_lag as f64);
        }

        // Per-message lag histogram — matches Node.js `ingestion_lag_ms_histogram`.
        for (partition, lag_ms) in &collected.stats.message_lags_ms {
            histogram!(
                "ingestion_lag_ms_histogram",
                "groupId" => group_id.clone(),
                "partition" => partition.to_string()
            )
            .record(*lag_ms as f64);
        }

        // Health-aware assignment: groups by routing key, honors stickiness,
        // skips unhealthy/dead workers, and defers keys whose worker is
        // draining/dead (held in the dispatcher's stash, flushed at completion).
        let sub_batches = dispatcher.assign(&batch_id, collected.messages);

        // Nothing to send and nothing deferred to wait for → no usable workers.
        if sub_batches.is_empty() && !dispatcher.has_deferred(&batch_id) {
            counter!("ingestion_consumer_no_healthy_workers_total").increment(1);
            anyhow::bail!("No healthy workers available to route batch");
        }

        let total_accepted =
            Self::scatter(&dispatcher, &transport, &batch_id, sub_batches, false).await?;

        Ok(ProcessedBatch {
            offsets: collected.offsets,
            stats: collected.stats,
            total_accepted,
            batch_size: batch_size as u32,
            elapsed: start.elapsed(),
        })
    }

    /// Send sub-batches to workers in parallel and resolve each in the
    /// dispatcher. On a send failure (the worker died mid-send), the failed
    /// messages are deferred — before the resolve, so the pin isn't evicted —
    /// to be replayed in order. Returns the number of messages accepted.
    ///
    /// `from_flush` is true when sending sub-batches produced by `flush_deferred`:
    /// the resolve then clears one deferral per key, so a key stays deferring from
    /// when it was first held until its flushed messages actually land (preventing
    /// a newer batch from racing them).
    async fn scatter(
        dispatcher: &Arc<Dispatcher>,
        transport: &Arc<HttpTransport>,
        batch_id: &str,
        sub_batches: Vec<SubBatch>,
        from_flush: bool,
    ) -> anyhow::Result<u32> {
        let mut handles = Vec::with_capacity(sub_batches.len());
        for sub_batch in sub_batches {
            let transport = Arc::clone(transport);
            let dispatcher = Arc::clone(dispatcher);
            let worker = sub_batch.worker.clone();
            let bid = batch_id.to_string();
            let routing_keys = sub_batch.routing_keys.clone();
            let key_offsets = sub_batch.key_offsets.clone();
            let message_count = sub_batch.messages.len();

            handles.push(tokio::spawn(async move {
                match transport
                    .send_batch(&worker, &bid, sub_batch.messages, from_flush)
                    .await
                {
                    Ok(accepted) => {
                        // Advance ACK high-water marks before the resolve, which
                        // may evict the keys' sentinel state.
                        dispatcher.on_sub_batch_acked(&key_offsets);
                        dispatcher.on_sub_batch_resolved(
                            &worker,
                            message_count,
                            &routing_keys,
                            from_flush,
                        );
                        dispatcher.record_send_outcome(&worker, false);
                        accepted
                    }
                    Err(send_err) => {
                        // Re-defer the failed messages first, so the ref-count drop
                        // in `on_sub_batch_resolved` doesn't evict the pin while the
                        // key still has work to replay. On the flush path this pairs
                        // with the `clears_deferral` decrement in the resolve, so the
                        // outstanding count nets to unchanged (never dipping to zero)
                        // and the key keeps deferring across the retry.
                        dispatcher.defer_failed(&bid, send_err.messages);
                        dispatcher.on_sub_batch_resolved(
                            &worker,
                            message_count,
                            &routing_keys,
                            from_flush,
                        );
                        dispatcher.record_send_outcome(&worker, true);
                        0
                    }
                }
            }));
        }

        let mut accepted = 0u32;
        for handle in handles {
            accepted += handle.await?;
        }
        Ok(accepted)
    }

    /// Collect messages from Kafka up to batch_size or batch_timeout.
    async fn collect_batch(&self) -> anyhow::Result<CollectedBatch> {
        let mut messages = Vec::with_capacity(self.batch_size);
        let mut offsets: HashMap<(String, i32), OffsetSpan> = HashMap::new();
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

            let poll_wait = remaining.min(Duration::from_secs(10));
            match tokio::time::timeout(poll_wait, stream.next()).await {
                Ok(Some(Ok(borrowed_message))) => {
                    let topic = borrowed_message.topic().to_string();
                    let partition = borrowed_message.partition();
                    let offset = borrowed_message.offset();

                    offsets
                        .entry((topic.clone(), partition))
                        .and_modify(|span| span.extend(offset))
                        .or_insert_with(|| OffsetSpan::new(offset));

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
                    // A fatal client error (such as UnreleasedInstanceId from a
                    // static-membership collision) permanently disables the
                    // consumer. Propagate it so the process exits and Kubernetes
                    // restarts the pod, instead of re-polling a dead client forever
                    // while still reporting healthy.
                    if let Some((code, reason)) = self.consumer.client().fatal_error() {
                        anyhow::bail!("fatal Kafka client error ({code:?}): {reason}");
                    }
                    break;
                }
                Ok(None) => break,
                Err(_) => {
                    self.handle.report_healthy();
                    if Instant::now() >= deadline {
                        break;
                    }
                }
            }
        }

        Ok(CollectedBatch {
            messages,
            offsets,
            stats,
        })
    }

    /// Commit the max offset for each topic-partition.
    fn commit_offsets(&self, offsets: &HashMap<(String, i32), OffsetSpan>) -> anyhow::Result<()> {
        if offsets.is_empty() {
            // Unreachable while batches require messages to be spawned; counted
            // so "no empty commits" is a measurable guarantee, not an assumption.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Commit requested with no offsets");
            return Ok(());
        }

        // Validate contiguity/monotonicity per partition before committing, so
        // a violation is attributed to the batch that caused it.
        self.commit_sentinel.check_commit(offsets);

        let mut tpl = TopicPartitionList::new();
        for ((topic, partition), span) in offsets {
            // Commit offset + 1 (Kafka convention: committed offset = next to read)
            tpl.add_partition_offset(topic, *partition, rdkafka::Offset::Offset(span.last + 1))?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);

        Ok(())
    }
}

/// Per-partition max offset + observed lag for the debug UI's batch events.
fn debug_partition_offsets(
    offsets: &HashMap<(String, i32), OffsetSpan>,
    max_lag_ms: &HashMap<(String, i32), i64>,
) -> Vec<PartitionOffset> {
    offsets
        .iter()
        .map(|((topic, partition), span)| PartitionOffset {
            topic: topic.clone(),
            partition: *partition,
            offset: span.last,
            lag_ms: max_lag_ms
                .get(&(topic.clone(), *partition))
                .copied()
                .unwrap_or(0),
        })
        .collect()
}

/// Aborts the wrapped task when dropped, covering every `process()` exit path.
struct AbortOnDrop(JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

/// How often the commit monitor fetches the group's broker-committed offsets.
const COMMIT_MONITOR_INTERVAL: Duration = Duration::from_secs(30);

/// Periodically fetch the broker's committed offsets for the current
/// assignment (an OffsetFetch round trip) and feed them to the commit
/// sentinel, which compares them against attempted commits and stamps the
/// last-successful-commit gauge on progress.
async fn run_commit_monitor(
    consumer: Arc<StreamConsumer<SentinelContext>>,
    sentinel: Arc<CommitSentinel>,
    handle: Handle,
) {
    loop {
        tokio::select! {
            _ = handle.shutdown_recv() => return,
            _ = tokio::time::sleep(COMMIT_MONITOR_INTERVAL) => {}
        }

        let fetch_consumer = Arc::clone(&consumer);
        // assignment() and committed_offsets() block on librdkafka.
        let fetched = tokio::task::spawn_blocking(move || {
            let assignment = fetch_consumer.assignment()?;
            if assignment.count() == 0 {
                return Ok(None);
            }
            fetch_consumer
                .committed_offsets(assignment, Duration::from_secs(5))
                .map(Some)
        })
        .await;

        match fetched {
            Ok(Ok(Some(committed))) => {
                let observed: Vec<(String, i32, i64)> = committed
                    .elements()
                    .iter()
                    .filter_map(|e| match e.offset() {
                        Offset::Offset(offset) => {
                            Some((e.topic().to_string(), e.partition(), offset))
                        }
                        // Invalid = no offset stored for the partition yet.
                        _ => None,
                    })
                    .collect();
                sentinel.observe_broker_committed(observed);
            }
            Ok(Ok(None)) => {} // no assignment yet (e.g. before first rebalance)
            Ok(Err(err)) => {
                counter!("ingestion_consumer_commit_monitor_errors_total").increment(1);
                warn!(error = %err, "Commit monitor failed to fetch committed offsets");
            }
            Err(err) => {
                counter!("ingestion_consumer_commit_monitor_errors_total").increment(1);
                warn!(error = %err, "Commit monitor task join error");
            }
        }
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

fn emit_latest_processed_timestamp_metrics(stats: &BatchStats, group_id: &str) {
    // Per-partition latest committed timestamp — matches Node.js
    // `latest_processed_timestamp_ms`.
    for ((topic, partition), ts_ms) in &stats.latest_kafka_ts {
        gauge!(
            "latest_processed_timestamp_ms",
            "topic" => topic.clone(),
            "partition" => partition.to_string(),
            "groupId" => group_id.to_string()
        )
        .set(*ts_ms as f64);
    }
}
