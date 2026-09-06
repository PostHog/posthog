use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{
    Charge, GroupCompletion, Offset, Partition, Settlement, TopicOffsetLedger, TopicPartition,
};
use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::TopicPartitionList;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::batcher::{make_batch_id, Batcher, BatcherOutputs};
use crate::config::{Config, LedgerMode};
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::discovery::DiscoveryMode;
use crate::dispatcher::Dispatcher;
use crate::grpc_transport::GrpcTransport;
use crate::ledger_shadow::LedgerShadow;
use crate::order_sentinel::{CommitSentinel, OffsetSpan, SentinelContext};
use crate::types::{Accumulator, SerializedKafkaMessage};

/// Batch-wide statistics gathered while collecting, used to emit parity
/// metrics. Per-partition facts live on [`PartitionDeliveries`].
struct BatchStats {
    /// Per-message (partition, lag_ms) pairs — for `ingestion_lag_ms_histogram`.
    message_lags_ms: Vec<(i32, i64)>,
    /// Total byte size of message payloads — for `consumer_batch_size_kb`.
    total_bytes: usize,
}

impl BatchStats {
    fn new() -> Self {
        Self {
            message_lags_ms: Vec::new(),
            total_bytes: 0,
        }
    }
}

/// One delivered message, as the batch records it against its partition.
struct Delivery {
    offset: i64,
    charge: Charge,
    /// Kafka message timestamp (ms).
    kafka_ts: i64,
    /// Ingestion lag (ms); `None` without a parseable `now` header.
    lag_ms: Option<i64>,
}

/// What a batch saw delivered from one partition, folded in one map entry
/// per message. The span feeds the commit; the stamped charges feed the
/// shadow ledger.
struct PartitionDeliveries {
    /// The offsets the commit path commits, as `last + 1`.
    span: OffsetSpan,
    /// Ledger generation the charges are stamped with.
    generation: u64,
    /// Ledger generations version seen when the charges were last stamped.
    /// Comparing it per message is cheaper than reading the generation.
    generations_version_seen: u64,
    /// The slice charged to the ledger: offsets delivered under `generation`.
    charges: Vec<(Offset, Charge)>,
    /// Max Kafka message timestamp (ms) — for `latest_processed_timestamp_ms`.
    latest_kafka_ts: i64,
    /// Max ingestion lag (ms) — for `ingestion_lag_ms`.
    max_lag_ms: Option<i64>,
}

impl PartitionDeliveries {
    fn new(generation: u64, generations_version: u64, delivery: &Delivery) -> Self {
        Self {
            span: OffsetSpan::new(delivery.offset),
            generation,
            generations_version_seen: generations_version,
            charges: vec![(Offset(delivery.offset), delivery.charge)],
            latest_kafka_ts: delivery.kafka_ts,
            max_lag_ms: delivery.lag_ms,
        }
    }

    /// Record one more delivery. `generation` is consulted only when
    /// `generations_version` moved since the last stamp. A moved generation
    /// means the partition was revoked and regained inside this batch: the
    /// offsets buffered so far belong to the old assignment and Kafka
    /// redelivers them, so the ledger slice restarts. The commit span keeps
    /// them, as the commit path does today.
    fn record(
        &mut self,
        generations_version: u64,
        generation: impl FnOnce() -> u64,
        delivery: &Delivery,
    ) {
        self.span.extend(delivery.offset);
        self.latest_kafka_ts = self.latest_kafka_ts.max(delivery.kafka_ts);
        if let Some(lag_ms) = delivery.lag_ms {
            self.max_lag_ms = Some(self.max_lag_ms.map_or(lag_ms, |max| max.max(lag_ms)));
        }
        if generations_version != self.generations_version_seen {
            self.generations_version_seen = generations_version;
            let generation = generation();
            if generation != self.generation {
                self.generation = generation;
                self.charges.clear();
            }
        }
        self.charges
            .push((Offset(delivery.offset), delivery.charge));
    }
}

/// Output of `collect_batch`.
struct CollectedBatch {
    /// The poll's messages, demuxed per partition and routing key.
    accumulator: Accumulator,
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
    stats: BatchStats,
}

/// One submitted poll, awaiting its group completions. The consumer
/// correlates completions to it by assignment epoch, partition, and offset;
/// the poll commits only once completions cover every message.
struct InFlightPoll {
    /// Consumer-side id for logs and debug events only; the batcher's
    /// internal batch id never crosses the boundary.
    poll_id: String,
    /// The epoch the batcher stamped on this poll's completions.
    assignment_epoch: u64,
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
    message_count: u32,
    /// Messages covered by completions so far, accepted or not.
    covered: u32,
    /// Worker-accepted messages so far. The poll commits only when this
    /// reaches `message_count`.
    accepted: u32,
    dispatched_at: Instant,
}

impl InFlightPoll {
    fn is_complete(&self) -> bool {
        self.covered >= self.message_count
    }

    fn contains(&self, partition: Partition, offset: i64) -> bool {
        self.partitions.iter().any(|(topic_partition, deliveries)| {
            topic_partition.partition == partition.0
                && deliveries.span.first <= offset
                && offset <= deliveries.span.last
        })
    }
}

/// Credit a completion to the poll it belongs to: the one collected under the
/// same assignment epoch whose offset span holds the completion's offsets.
/// Within one epoch, poll spans are disjoint per partition, so at most one
/// poll matches. A completion that matches no in-flight poll (its partition
/// was revoked and reassigned while the group was out, or its poll is gone)
/// is discarded and counted.
fn apply_completion(in_flight: &mut VecDeque<InFlightPoll>, completion: GroupCompletion) {
    let Some(first) = completion.offsets.first().map(|offset| offset.0) else {
        return;
    };
    let Some(poll) = in_flight.iter_mut().find(|poll| {
        poll.assignment_epoch == completion.assignment_epoch
            && poll.contains(completion.partition, first)
    }) else {
        counter!("ingestion_consumer_stale_group_completions_total").increment(1);
        warn!(
            partition = %completion.partition,
            offset = first,
            epoch = completion.assignment_epoch,
            "Discarding group completion that matches no in-flight poll"
        );
        return;
    };
    poll.covered += completion.offsets.len() as u32;
    poll.accepted += completion.accepted;
}

/// Options for constructing an [`IngestionConsumer`] from pre-built parts.
/// Used in integration tests where the Kafka consumer is created externally.
pub struct IngestionConsumerOptions {
    pub batch_size: usize,
    /// Payload-byte bound on a batch; `0` disables it (count-only collection).
    /// See `Config::consumer_batch_size_kb`.
    pub batch_size_bytes: usize,
    pub batch_timeout: Duration,
    pub max_in_flight_batches: usize,
    pub group_id: String,
    /// No-progress bound on flushing a batch's deferred groups, enforced by
    /// the batcher's flush driver: the deadline resets whenever any of the
    /// batch's messages land, and the batch fails only after a full window
    /// with zero progress. Production takes it from
    /// `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS` (default 60s).
    pub deferred_flush_timeout: Duration,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    pub debug_recorder: Option<Arc<DebugRecorder>>,
    /// Whether the offset ledger observes or owns the commit path.
    pub ledger_mode: LedgerMode,
}

/// The main consumer loop: reads from Kafka, demuxes each poll into groups,
/// submits them to the [`Batcher`] (which routes, dispatches, and flushes),
/// and commits offsets once the batcher's completions cover a poll.
pub struct IngestionConsumer {
    consumer: Arc<StreamConsumer<SentinelContext>>,
    batcher: Batcher,
    /// Taken once by `process`.
    outputs: Option<BatcherOutputs>,
    transport: Arc<GrpcTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_size_bytes: usize,
    batch_timeout: Duration,
    max_in_flight_batches: usize,
    handle: Handle,
    group_id: String,
    /// Validates commit contiguity/monotonicity per partition. Shared with the
    /// consumer's [`SentinelContext`], which resets baselines on rebalance.
    commit_sentinel: Arc<CommitSentinel>,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
    ledger_shadow: LedgerShadow,
    /// Selects whether commits come from the batch spans or the ledger.
    ledger_mode: LedgerMode,
}

impl IngestionConsumer {
    /// Constructs a consumer from pre-built parts. Useful in integration tests
    /// where the Kafka consumer is created and subscribed externally. Builds
    /// the batcher from the dispatcher and transport; `new` instead takes one
    /// built in `main`.
    pub fn from_parts(
        consumer: StreamConsumer<SentinelContext>,
        dispatcher: Arc<Dispatcher>,
        transport: Arc<GrpcTransport>,
        worker_urls: Vec<String>,
        options: IngestionConsumerOptions,
        handle: Handle,
    ) -> Self {
        // Share the context's commit sentinel and ledger so rebalance
        // callbacks reset the same baselines the commit path checks against.
        // The shadow runs whenever the context carries a ledger: `new` builds
        // one unless the mode is off, and a detached context always carries
        // one.
        let commit_sentinel = consumer.context().commit_sentinel();
        let topic_offset_ledger = consumer.context().topic_offset_ledger();
        let (batcher, outputs) = Batcher::new(
            dispatcher,
            Arc::clone(&transport),
            handle.clone(),
            options.deferred_flush_timeout,
        );
        Self {
            commit_sentinel,
            debug_recorder: options.debug_recorder,
            ledger_shadow: LedgerShadow::new(topic_offset_ledger),
            ledger_mode: options.ledger_mode,
            consumer: Arc::new(consumer),
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_size_bytes: options.batch_size_bytes,
            batch_timeout: options.batch_timeout,
            max_in_flight_batches: options.max_in_flight_batches.max(1),
            handle,
            group_id: options.group_id,
        }
    }

    pub fn new(
        config: &Config,
        batcher: Batcher,
        outputs: BatcherOutputs,
        transport: Arc<GrpcTransport>,
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
        // After the build, so the caps reported are the ones the client runs
        // with rather than the settings that seeded them.
        crate::kafka_stats::export_limits(
            &client_config,
            config.consumer_batch_size,
            config.consumer_batch_size_kb,
        );
        let commit_sentinel = Arc::new(CommitSentinel::new());
        commit_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        let key_sentinel = batcher.key_order_sentinel();
        key_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        // Off, the consumer has no ledger at all: the rebalance callbacks
        // have nothing to forget and the shadow nothing to charge.
        let topic_offset_ledger = (config.consumer_offset_ledger_mode != LedgerMode::Off)
            .then(|| Arc::new(TopicOffsetLedger::new()));
        let mut context = SentinelContext::new(
            Arc::clone(&commit_sentinel),
            key_sentinel,
            topic_offset_ledger.clone(),
        );
        context.set_assignment_epoch(transport.assignment_epoch());
        let consumer: StreamConsumer<SentinelContext> =
            client_config.create_with_context(context)?;
        consumer.subscribe(&[&config.ingestion_consumer_consume_topic])?;

        info!(
            topic = %config.ingestion_consumer_consume_topic,
            group = %config.ingestion_consumer_group_id,
            workers = worker_urls.len(),
            batch_size = config.consumer_batch_size,
            batch_size_kb = config.consumer_batch_size_kb,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer: Arc::new(consumer),
            commit_sentinel,
            debug_recorder,
            ledger_shadow: LedgerShadow::new(topic_offset_ledger),
            ledger_mode: config.consumer_offset_ledger_mode,
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_size_bytes: config.consumer_batch_size_kb.saturating_mul(1024),
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            max_in_flight_batches: config.consumer_max_background_tasks.max(1),
            handle,
            group_id: config.ingestion_consumer_group_id.clone(),
        })
    }

    /// Run the consumer loop until shutdown is signalled via the lifecycle handle.
    /// Waits for all workers to be ready before starting to consume from Kafka.
    pub async fn process(mut self) {
        let _guard = self.handle.process_scope();
        let BatcherOutputs {
            mut completions,
            mut errors,
        } = self.outputs.take().expect("process is called once");

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

        let mut in_flight_polls: VecDeque<InFlightPoll> = VecDeque::new();
        let mut accepting_new_batches = true;

        while accepting_new_batches || !in_flight_polls.is_empty() {
            // Consumer-level concurrency: how many Kafka batches are being
            // processed in parallel, bounded by `max_in_flight_batches`.
            gauge!("ingestion_consumer_in_flight_batches").set(in_flight_polls.len() as f64);

            if accepting_new_batches && in_flight_polls.len() < self.max_in_flight_batches {
                tokio::select! {
                    _ = self.handle.shutdown_recv() => {
                        info!(
                            in_flight = in_flight_polls.len(),
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

                        if collected.accumulator.message_count() == 0 {
                            self.handle.report_healthy();
                            if in_flight_polls.is_empty() {
                                continue;
                            }
                        } else {
                            in_flight_polls.push_back(self.submit_poll(collected));
                            self.handle.report_healthy();

                            if in_flight_polls.len() < self.max_in_flight_batches {
                                continue;
                            }
                        }
                    }
                }
            }

            if let Err(err) = self
                .complete_oldest_poll(&mut in_flight_polls, &mut completions, &mut errors)
                .await
            {
                self.fail_batch_processing(err);
                return;
            }
        }

        info!("Consumer loop stopped");
    }

    /// Submit one collected poll to the batcher and track it as in flight.
    fn submit_poll(&self, collected: CollectedBatch) -> InFlightPoll {
        let CollectedBatch {
            accumulator,
            partitions,
            stats,
        } = collected;
        let message_count = accumulator.message_count();
        let poll_id = make_batch_id();
        record_if(&self.debug_recorder, || DebugEventKind::BatchDispatched {
            batch_id: poll_id.clone(),
            messages: message_count,
            partitions: debug_partition_offsets(&partitions),
        });
        emit_poll_stats(
            &stats,
            &partitions,
            message_count,
            &self.group_id,
            self.batch_size,
            self.batch_size_bytes,
        );

        let assignment_epoch = self.batcher.submit(accumulator);

        info!(
            batch_id = %poll_id,
            messages = message_count,
            "Kafka batch dispatched"
        );

        InFlightPoll {
            poll_id,
            assignment_epoch,
            partitions,
            message_count: message_count as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        }
    }

    /// Wait for completions to cover the oldest in-flight poll, then commit
    /// it. Commits only the oldest poll: later completed polls stay
    /// uncommitted behind any earlier one, preserving at-least-once delivery
    /// across worker or pipeline failures. Completions for newer polls are
    /// still credited while waiting.
    async fn complete_oldest_poll(
        &self,
        in_flight_polls: &mut VecDeque<InFlightPoll>,
        completions: &mut mpsc::UnboundedReceiver<GroupCompletion>,
        errors: &mut mpsc::UnboundedReceiver<String>,
    ) -> anyhow::Result<()> {
        if in_flight_polls.front().is_none() {
            return Ok(());
        }

        let mut heartbeat = tokio::time::interval(Duration::from_secs(1));
        while !in_flight_polls
            .front()
            .expect("front is present")
            .is_complete()
        {
            tokio::select! {
                completion = completions.recv() => match completion {
                    Some(completion) => apply_completion(in_flight_polls, completion),
                    None => anyhow::bail!("batcher completion channel closed"),
                },
                failure = errors.recv() => match failure {
                    Some(message) => anyhow::bail!(message),
                    None => anyhow::bail!("batcher error channel closed"),
                },
                _ = heartbeat.tick() => self.handle.report_healthy(),
            }
        }

        let poll = in_flight_polls.pop_front().expect("front is present");
        if poll.accepted < poll.message_count {
            anyhow::bail!(
                "accepted {}/{} messages — not committing offsets",
                poll.accepted,
                poll.message_count
            );
        }

        self.commit_offsets(&poll.partitions)?;
        emit_latest_processed_timestamp_metrics(&poll.partitions, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::BatchCommitted {
            batch_id: poll.poll_id.clone(),
            accepted: poll.accepted,
            duration_ms: poll.dispatched_at.elapsed().as_millis() as u64,
            partitions: debug_partition_offsets(&poll.partitions),
        });

        counter!("ingestion_consumer_messages_processed_total").increment(poll.accepted as u64);
        counter!("ingestion_consumer_batches_processed_total").increment(1);
        self.handle.report_healthy();

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

    /// Collect messages from Kafka until the first of `batch_size` messages,
    /// `batch_size_bytes` of payload (when enabled), or `batch_timeout`.
    ///
    /// The byte bound is checked at the top of the loop, where accumulated
    /// bytes are those of messages already appended: a batch therefore always
    /// carries at least one message — a single payload larger than the whole
    /// bound still moves rather than wedging the partition — and overshoot is
    /// at most one message, itself bounded by `fetch.message.max.bytes`.
    async fn collect_batch(&self) -> anyhow::Result<CollectedBatch> {
        let mut accumulator = Accumulator::default();
        let mut partitions: HashMap<TopicPartition, PartitionDeliveries> = HashMap::new();
        let mut stats = BatchStats::new();
        let deadline = Instant::now() + self.batch_timeout;
        let batch_start_ms = current_time_ms();

        let mut stream = self.consumer.stream();

        loop {
            if accumulator.message_count() >= self.batch_size {
                break;
            }

            if self.batch_size_bytes > 0 && stats.total_bytes >= self.batch_size_bytes {
                counter!("ingestion_consumer_batches_byte_capped_total").increment(1);
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
                    let kafka_ts = borrowed_message.timestamp().to_millis().unwrap_or(0);

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

                    let lag_ms = headers
                        .get("now")
                        .and_then(|v| parse_now_ms(v))
                        .map(|capture_ms| (batch_start_ms - capture_ms).max(0));
                    if let Some(lag_ms) = lag_ms {
                        stats.message_lags_ms.push((partition, lag_ms));
                    }

                    let delivery = Delivery {
                        offset,
                        charge: message_charge(&borrowed_message),
                        kafka_ts,
                        lag_ms,
                    };
                    let key = TopicPartition::new(topic.clone(), partition);
                    let generations_version = self.ledger_shadow.generations_version();
                    match partitions.get_mut(&key) {
                        Some(deliveries) => deliveries.record(
                            generations_version,
                            || self.ledger_shadow.generation(&key),
                            &delivery,
                        ),
                        None => {
                            let generation = self.ledger_shadow.generation(&key);
                            partitions.insert(
                                key,
                                PartitionDeliveries::new(
                                    generation,
                                    generations_version,
                                    &delivery,
                                ),
                            );
                        }
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

                    accumulator.push(Partition(partition), serialized.into());
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

        // One ledger call per partition keeps the lock and the gauge labels
        // off the per-message path.
        for (topic_partition, partition) in &partitions {
            self.ledger_shadow
                .charge(topic_partition, partition.generation, &partition.charges);
        }

        Ok(CollectedBatch {
            accumulator,
            partitions,
            stats,
        })
    }

    /// Commit either the existing per-batch max offset or the verified ledger
    /// frontier for each topic-partition.
    fn commit_offsets(
        &self,
        partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    ) -> anyhow::Result<()> {
        if partitions.is_empty() {
            // Unreachable while batches require messages to be spawned; counted
            // so "no empty commits" is a measurable guarantee, not an assumption.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Commit requested with no offsets");
            return Ok(());
        }

        match self.ledger_mode {
            LedgerMode::Off | LedgerMode::Shadow => self.commit_offset_spans(partitions),
            LedgerMode::Commit => self.commit_frontiers(partitions),
        }
    }

    /// Off and shadow modes: commit the per-batch max offsets unchanged, then
    /// settle the ledger against them for comparison only. Off has no ledger,
    /// so the settlement is a no-op there.
    fn commit_offset_spans(
        &self,
        partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    ) -> anyhow::Result<()> {
        self.submit_commit(
            partitions
                .iter()
                .map(|(topic_partition, partition)| (topic_partition, &partition.span)),
        )?;
        for (topic_partition, partition) in partitions {
            if self.settle(topic_partition, partition).is_some() {
                self.ledger_shadow.drain(topic_partition);
            }
        }
        Ok(())
    }

    /// Commit mode: settle the batch against the ledger and commit each
    /// partition's frontier. A partition without a frontier is not committed
    /// and stays on its last committed offset.
    fn commit_frontiers(
        &self,
        partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    ) -> anyhow::Result<()> {
        let mut settled = Vec::with_capacity(partitions.len());
        let mut frontier_spans = Vec::with_capacity(partitions.len());
        for (topic_partition, partition) in partitions {
            let Some(settlement) = self.settle(topic_partition, partition) else {
                continue;
            };
            settled.push(topic_partition);
            if let Some(span) = frontier_span(&partition.span, settlement.frontier) {
                frontier_spans.push((topic_partition, span));
            }
        }

        if frontier_spans.is_empty() {
            warn!("No ledger frontier available for completed offsets; skipping commit");
            return Ok(());
        }

        self.submit_commit(
            frontier_spans
                .iter()
                .map(|(topic_partition, span)| (*topic_partition, span)),
        )?;
        for topic_partition in settled {
            self.ledger_shadow.drain(topic_partition);
        }
        Ok(())
    }

    /// Settle one partition's slice of a batch against the ledger.
    fn settle(
        &self,
        topic_partition: &TopicPartition,
        partition: &PartitionDeliveries,
    ) -> Option<Settlement> {
        self.ledger_shadow.settle(
            topic_partition,
            partition.generation,
            partition.charges.iter().map(|(offset, _)| *offset),
            &partition.span,
        )
    }

    /// Validate and submit one commit to Kafka.
    fn submit_commit<'a>(
        &self,
        spans: impl IntoIterator<Item = (&'a TopicPartition, &'a OffsetSpan)>,
    ) -> anyhow::Result<()> {
        let spans: Vec<_> = spans.into_iter().collect();
        // Validate contiguity/monotonicity per partition before committing, so
        // a violation is attributed to the batch that caused it.
        self.commit_sentinel.check_commit(spans.iter().copied());

        let mut tpl = TopicPartitionList::new();
        for (topic_partition, span) in &spans {
            // Commit offset + 1 (Kafka convention: committed offset = next to read)
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(span.last + 1),
            )?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);

        Ok(())
    }
}

/// Map a settled frontier back to the span the commit path submits: the
/// frontier is next-to-read and the span is last-processed, so the commit
/// adds the 1 back and submits the frontier verbatim. `None` for a partition
/// that settled without a frontier; it stays on its last commit.
fn frontier_span(span: &OffsetSpan, frontier: Option<Offset>) -> Option<OffsetSpan> {
    frontier.map(|frontier| OffsetSpan {
        first: span.first,
        last: frontier.0 - 1,
    })
}

/// Emit the per-poll parity metrics (received counts, batch sizes,
/// utilization, and lag) right after collection, before the poll is
/// submitted.
fn emit_poll_stats(
    stats: &BatchStats,
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    batch_size: usize,
    group_id: &str,
    max_batch_size: usize,
    max_batch_bytes: usize,
) {
    counter!("ingestion_consumer_messages_received_total").increment(batch_size as u64);
    gauge!("ingestion_consumer_batch_size").set(batch_size as f64);

    // Batch fill ratio (batch size / configured max) — matches Node.js
    // `consumer_batch_utilization`. A useful scaling signal: sustained high
    // utilization means batches are saturating and the consumer is demand-bound.
    if max_batch_size > 0 {
        gauge!("consumer_batch_utilization", "groupId" => group_id.to_string())
            .set(batch_size as f64 / max_batch_size as f64);
    }

    // The same ratio against the byte bound. Reported separately because the
    // two disagree on lanes whose events are large: a count utilization can
    // sit far below 1.0 while batches are in fact full, simply because the
    // byte bound (or the prefetch queue behind it) ends collection first.
    // Reading only the count ratio there invites raising a cap that cannot
    // be reached. Absent when the byte bound is disabled.
    if max_batch_bytes > 0 {
        gauge!("consumer_batch_utilization_bytes", "groupId" => group_id.to_string())
            .set(stats.total_bytes as f64 / max_batch_bytes as f64);
    }

    // Batch size distribution — matches Node.js `consumer_batch_size` histogram.
    histogram!("consumer_batch_size").record(batch_size as f64);
    histogram!("consumer_batch_size_kb").record(stats.total_bytes as f64 / 1024.0);

    // Per-partition ingestion lag gauge — matches Node.js `ingestion_lag_ms`.
    for (topic_partition, partition) in partitions {
        let Some(max_lag) = partition.max_lag_ms else {
            continue;
        };
        gauge!(
            "ingestion_lag_ms",
            "topic" => topic_partition.topic.clone(),
            "partition" => topic_partition.partition.to_string(),
            "groupId" => group_id.to_string()
        )
        .set(max_lag as f64);
    }

    // Per-message lag histogram — matches Node.js `ingestion_lag_ms_histogram`.
    for (partition, lag_ms) in &stats.message_lags_ms {
        histogram!(
            "ingestion_lag_ms_histogram",
            "groupId" => group_id.to_string(),
            "partition" => partition.to_string()
        )
        .record(*lag_ms as f64);
    }
}

/// Per-partition max offset + observed lag for the debug UI's batch events.
fn debug_partition_offsets(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
) -> Vec<PartitionOffset> {
    partitions
        .iter()
        .map(|(topic_partition, partition)| PartitionOffset {
            topic: topic_partition.topic.clone(),
            partition: topic_partition.partition,
            offset: partition.span.last,
            lag_ms: partition.max_lag_ms.unwrap_or(0),
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
                        rdkafka::Offset::Offset(offset) => {
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

/// One delivered message's cost against the ledger: one event, and the bytes
/// the process holds for the message. The byte count is a memory bound, so it
/// is the payload plus the key plus every header key and value, not only the
/// payload.
fn message_charge(message: &impl Message) -> Charge {
    let payload_bytes = message.payload().map(|v| v.len()).unwrap_or(0);
    let key_bytes = message.key().map(|k| k.len()).unwrap_or(0);
    let mut header_bytes = 0;
    if let Some(headers) = message.headers() {
        for i in 0..headers.count() {
            let header = headers.get(i);
            header_bytes += header.key.len() + header.value.map(|v| v.len()).unwrap_or(0);
        }
    }
    Charge {
        events: 1,
        bytes: (payload_bytes + key_bytes + header_bytes) as u64,
    }
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

fn emit_latest_processed_timestamp_metrics(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    group_id: &str,
) {
    // Per-partition latest committed timestamp — matches Node.js
    // `latest_processed_timestamp_ms`.
    for (topic_partition, partition) in partitions {
        gauge!(
            "latest_processed_timestamp_ms",
            "topic" => topic_partition.topic.clone(),
            "partition" => topic_partition.partition.to_string(),
            "groupId" => group_id.to_string()
        )
        .set(partition.latest_kafka_ts as f64);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_kafka_consumer::Offset as MessageOffset;

    fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
        let mut partitions = HashMap::new();
        partitions.insert(
            TopicPartition::new("test", partition),
            PartitionDeliveries {
                span: OffsetSpan { first, last },
                generation: 0,
                generations_version_seen: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
            },
        );
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions,
            message_count: count,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64], accepted: u32) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            offsets: offsets.iter().map(|o| MessageOffset(*o)).collect(),
            accepted,
        }
    }

    #[test]
    fn apply_completion_credits_the_poll_holding_the_offsets() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        apply_completion(&mut in_flight, completion(1, 0, &[4, 6], 2));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 2);
        assert_eq!(in_flight[1].accepted, 2);
        assert!(!in_flight[1].is_complete());

        apply_completion(&mut in_flight, completion(1, 0, &[5, 7], 2));
        assert!(in_flight[1].is_complete());
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        // The same offsets exist in two polls when a partition was revoked,
        // reassigned, and replayed. The epoch keeps each incarnation's
        // completions in its own poll.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        apply_completion(&mut in_flight, completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 4);
    }

    #[test]
    fn apply_completion_discards_a_completion_matching_no_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);

        // Wrong partition, then wrong epoch: neither may be credited.
        apply_completion(&mut in_flight, completion(1, 2, &[1], 1));
        apply_completion(&mut in_flight, completion(9, 0, &[1], 1));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[0].accepted, 0);
    }

    #[test]
    fn frontier_span_submits_the_frontier_verbatim() {
        let span = OffsetSpan {
            first: 10,
            last: 11,
        };
        assert_eq!(
            frontier_span(&span, Some(Offset(12))),
            Some(OffsetSpan {
                first: 10,
                last: 11
            })
        );
        assert_eq!(
            frontier_span(&span, Some(Offset(11))),
            Some(OffsetSpan {
                first: 10,
                last: 10
            }),
            "a frontier trailing the span wins"
        );
    }

    #[test]
    fn a_partition_without_a_frontier_is_not_committed() {
        let span = OffsetSpan {
            first: 20,
            last: 21,
        };
        assert_eq!(frontier_span(&span, None), None);
    }
}
