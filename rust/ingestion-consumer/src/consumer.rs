use std::collections::{HashMap, VecDeque};
use std::future::Future;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{Charge, Offset, Partition, TopicOffsetLedger, TopicPartition};
use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::TopicPartitionList;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::config::Config;
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::discovery::DiscoveryMode;
use crate::dispatcher::{Dispatcher, KeyOffset, SubBatch};
use crate::grpc_transport::{GrpcTransport, PendingWorkerStreamSend};
use crate::ledger_shadow::LedgerShadow;
use crate::order_sentinel::{CommitSentinel, OffsetSpan, SentinelContext};
use crate::transport::SendError;
use crate::types::{Accumulator, Group, SerializedKafkaMessage};
use crate::worker_registry::WorkerId;

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
    groups: Vec<Group>,
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
    stats: BatchStats,
}

struct ProcessedBatch {
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
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

/// A sub-batch whose send order is already established on its worker's stream
/// (`GrpcTransport::begin_send`), plus the metadata the resolve protocol needs.
struct PendingSubBatch {
    worker: WorkerId,
    routing_keys: Vec<String>,
    key_offsets: Vec<KeyOffset>,
    message_count: usize,
    pending: PendingWorkerStreamSend,
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
    /// No-progress bound on flushing a batch's deferred groups: the deadline
    /// resets whenever any of the batch's messages land, and the batch fails
    /// only after a full window with zero progress. `new` takes it from
    /// `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS` (default 60s).
    pub deferred_flush_timeout: Duration,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    pub debug_recorder: Option<Arc<DebugRecorder>>,
}

/// The main consumer loop: reads from Kafka, routes messages by Kafka key
/// via the health-aware Dispatcher, dispatches sub-batches to workers over
/// ordered gRPC streams, and commits offsets only after all workers ACK.
pub struct IngestionConsumer {
    consumer: Arc<StreamConsumer<SentinelContext>>,
    dispatcher: Arc<Dispatcher>,
    transport: Arc<GrpcTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_size_bytes: usize,
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
    ledger_shadow: LedgerShadow,
}

impl IngestionConsumer {
    /// Constructs a consumer from pre-built parts. Useful in integration tests
    /// where the Kafka consumer is created and subscribed externally.
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
        // The shadow runs whenever the context carries a ledger: `new` reads
        // the kill switch, and a detached context always carries one.
        let commit_sentinel = consumer.context().commit_sentinel();
        let topic_offset_ledger = consumer.context().topic_offset_ledger();
        Self {
            commit_sentinel,
            debug_recorder: options.debug_recorder,
            consumer: Arc::new(consumer),
            dispatcher,
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_size_bytes: options.batch_size_bytes,
            batch_timeout: options.batch_timeout,
            max_in_flight_batches: options.max_in_flight_batches.max(1),
            deferred_flush_timeout: options.deferred_flush_timeout,
            handle,
            group_id: options.group_id,
            ledger_shadow: LedgerShadow::new(topic_offset_ledger),
        }
    }

    pub fn new(
        config: &Config,
        dispatcher: Arc<Dispatcher>,
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
        let key_sentinel = dispatcher.key_order_sentinel();
        key_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        // Off, the consumer has no ledger at all: the rebalance callbacks
        // have nothing to forget and the shadow nothing to charge.
        let topic_offset_ledger = config
            .consumer_offset_ledger_shadow_enabled
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
            dispatcher,
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_size_bytes: config.consumer_batch_size_kb.saturating_mul(1024),
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            max_in_flight_batches: config.consumer_max_background_tasks.max(1),
            deferred_flush_timeout: Duration::from_millis(
                config.consumer_deferred_flush_timeout_ms,
            ),
            handle,
            group_id: config.ingestion_consumer_group_id.clone(),
            ledger_shadow: LedgerShadow::new(topic_offset_ledger),
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

                        if collected.groups.is_empty() {
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

    fn spawn_batch_processing(&self, mut collected: CollectedBatch) -> InFlightBatch {
        let batch_size: usize = collected.groups.iter().map(Group::len).sum();
        let batch_id = make_batch_id();
        // Register AND assign here, on the consumer loop, so both happen in
        // true batch order. Registration first, so the stash learns batch
        // order before failed-send deferrals (which land in gather order) can
        // reach it. Assignment too: on spawned tasks, batch N+1's assign could
        // beat batch N's to the pin table and send a key's newer messages
        // first — per-key send order must be fixed exactly once, in Kafka
        // order, at assignment.
        self.dispatcher.register_batch(&batch_id);
        record_if(&self.debug_recorder, || DebugEventKind::BatchDispatched {
            batch_id: batch_id.clone(),
            messages: batch_size,
            partitions: debug_partition_offsets(&collected.partitions),
        });
        let assign_start = Instant::now();
        let groups = std::mem::take(&mut collected.groups);
        // Send order is established here too, still on the consumer loop and
        // under the dispatcher's lock: `begin_send` is synchronous, so a key's
        // sub-batches enter its worker's stream in assignment order — spawned
        // tasks racing to send would scramble it.
        let pending = self
            .dispatcher
            .assign_and_send(&batch_id, groups, |sub_batch| {
                Self::begin_send(&self.transport, &batch_id, sub_batch, false)
            });
        // Assignment serializes on the consumer loop (it no longer overlaps
        // batch collection) — watch this stays a small fraction of the batch
        // collection interval.
        histogram!("ingestion_consumer_assign_duration_seconds")
            .record(assign_start.elapsed().as_secs_f64());

        let task_batch_id = batch_id.clone();
        let dispatcher = Arc::clone(&self.dispatcher);
        let group_id = self.group_id.clone();
        let max_batch_size = self.batch_size;
        let max_batch_bytes = self.batch_size_bytes;

        let handle = tokio::spawn(async move {
            Self::process_collected_batch(
                collected,
                pending,
                batch_size,
                task_batch_id,
                dispatcher,
                group_id,
                max_batch_size,
                max_batch_bytes,
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
        // oldest batch first — preserves per-key order across batches. The
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
        self.commit_offsets(&processed.partitions)?;
        self.dispatcher.release_batch(&batch_id);
        emit_latest_processed_timestamp_metrics(&processed.partitions, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::BatchCommitted {
            batch_id: batch_id.clone(),
            accepted: processed.total_accepted,
            duration_ms: processed.elapsed.as_millis() as u64,
            partitions: debug_partition_offsets(&processed.partitions),
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
        let processed = self.heartbeat_while(batch.handle).await??;
        info!(batch_id = %batch_id, "Kafka batch processing completed");
        Ok(processed)
    }

    async fn heartbeat_while<F: Future>(&self, fut: F) -> F::Output {
        tokio::pin!(fut);
        let mut heartbeat = tokio::time::interval(Duration::from_secs(1));

        loop {
            tokio::select! {
                output = &mut fut => return output,
                _ = heartbeat.tick() => self.handle.report_healthy(),
            }
        }
    }

    /// Flush a completed batch's deferred groups (keys whose worker was
    /// draining/dead), re-routing them to healthy workers and accumulating the
    /// accepted count. Retries with backoff while a flush can't route (no healthy
    /// worker yet). Called serialized, oldest-first, so a key's deferred
    /// messages flush in Kafka order.
    ///
    /// `deferred_flush_timeout` bounds **stalls, not total time**: the deadline
    /// resets whenever any of the batch's messages are accepted, so a large
    /// backlog draining slowly under saturation keeps
    /// going, and the batch only fails — exiting the process and replaying —
    /// when flushing is truly wedged: nothing landed for a full timeout
    /// (nothing routable, or a flapping worker re-deferring every send).
    /// Failing the whole process for a mere slow drain amplified today's
    /// saturation: each restart replayed all its partitions into an already
    /// overloaded pool.
    async fn flush_deferred(
        &self,
        batch_id: &str,
        processed: &mut ProcessedBatch,
    ) -> anyhow::Result<()> {
        if self.dispatcher.has_unfinished_flush(batch_id) {
            let mut stall_deadline = Instant::now() + self.deferred_flush_timeout;
            while self.dispatcher.has_unfinished_flush(batch_id) {
                if Instant::now() >= stall_deadline {
                    anyhow::bail!("deferred messages made no progress within the flush timeout");
                }
                let mut accepted_this_round = 0u32;
                // Serialized on the consumer loop, oldest batch first, so
                // begin_send order preserves the flush's key order.
                let pending = self
                    .dispatcher
                    .flush_deferred_and_send(batch_id, |sub_batch| {
                        Self::begin_send(&self.transport, batch_id, sub_batch, true)
                    });
                if pending.is_empty() {
                    // Nothing is routable right now (no healthy worker), so wait.
                    tokio::select! {
                        _ = self.handle.shutdown_recv() => {
                            anyhow::bail!("shutdown while flushing deferred messages");
                        }
                        _ = tokio::time::sleep(Duration::from_millis(200)) => {
                            self.handle.report_healthy();
                        }
                    }
                } else {
                    accepted_this_round += self
                        .heartbeat_while(Self::scatter(&self.dispatcher, batch_id, pending, true))
                        .await?;
                }
                processed.total_accepted += accepted_this_round;
                if accepted_this_round > 0 {
                    stall_deadline = Instant::now() + self.deferred_flush_timeout;
                }
            }
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

    /// Establish a sub-batch's send order. Synchronous and non-blocking on
    /// purpose: called under the dispatcher's lock on the consumer loop, where
    /// send order is decided, so a key's sub-batches enter its worker's stream
    /// in exactly that order.
    fn begin_send(
        transport: &GrpcTransport,
        batch_id: &str,
        sub_batch: SubBatch,
        replay: bool,
    ) -> PendingSubBatch {
        let SubBatch {
            worker,
            messages,
            routing_keys,
            key_offsets,
        } = sub_batch;
        let message_count = messages.len();
        let pending = transport.begin_send(&worker, batch_id, messages, replay);
        PendingSubBatch {
            worker,
            routing_keys,
            key_offsets,
            message_count,
            pending,
        }
    }

    /// Await a batch's pre-ordered sub-batch sends, gather results, and feed
    /// passive health signals. Assignment and send ordering already happened
    /// on the consumer loop (see `spawn_batch_processing`); offset commits
    /// happen later, in Kafka batch order, in `complete_oldest_batch`.
    #[allow(clippy::too_many_arguments)]
    async fn process_collected_batch(
        collected: CollectedBatch,
        pending: Vec<PendingSubBatch>,
        batch_size: usize,
        batch_id: String,
        dispatcher: Arc<Dispatcher>,
        group_id: String,
        max_batch_size: usize,
        max_batch_bytes: usize,
    ) -> anyhow::Result<ProcessedBatch> {
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

        // The same ratio against the byte bound. Reported separately because the
        // two disagree on lanes whose events are large: a count utilization can
        // sit far below 1.0 while batches are in fact full, simply because the
        // byte bound (or the prefetch queue behind it) ends collection first.
        // Reading only the count ratio there invites raising a cap that cannot
        // be reached. Absent when the byte bound is disabled.
        if max_batch_bytes > 0 {
            gauge!("consumer_batch_utilization_bytes", "groupId" => group_id.clone())
                .set(collected.stats.total_bytes as f64 / max_batch_bytes as f64);
        }

        // Batch size distribution — matches Node.js `consumer_batch_size` histogram.
        histogram!("consumer_batch_size").record(batch_size as f64);
        histogram!("consumer_batch_size_kb").record(collected.stats.total_bytes as f64 / 1024.0);

        // Per-partition ingestion lag gauge — matches Node.js `ingestion_lag_ms`.
        for (topic_partition, partition) in &collected.partitions {
            let Some(max_lag) = partition.max_lag_ms else {
                continue;
            };
            gauge!(
                "ingestion_lag_ms",
                "topic" => topic_partition.topic.clone(),
                "partition" => topic_partition.partition.to_string(),
                "groupId" => group_id.clone()
            )
            .set(max_lag as f64);
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

        // Nothing to send and no deferred groups means no usable workers.
        if pending.is_empty() && !dispatcher.batch_has_flush_activity(&batch_id) {
            counter!("ingestion_consumer_no_healthy_workers_total").increment(1);
            anyhow::bail!("No healthy workers available to route batch");
        }

        let total_accepted = Self::scatter(&dispatcher, &batch_id, pending, false).await?;

        Ok(ProcessedBatch {
            partitions: collected.partitions,
            total_accepted,
            batch_size: batch_size as u32,
            elapsed: start.elapsed(),
        })
    }

    /// Await sub-batch sends in parallel and resolve each in the dispatcher.
    /// On a send failure (the worker died mid-send, or its worker stream was fenced),
    /// the failed messages are deferred — before the resolve, so the pin
    /// isn't evicted — to be replayed in order. Returns the number of
    /// messages accepted.
    ///
    /// `from_flush` is true when awaiting sub-batches produced by `flush_deferred`:
    /// the resolve then clears one deferral per key, so a key stays deferring from
    /// when it was first held until its flushed messages actually land (preventing
    /// a newer batch from racing them).
    async fn scatter(
        dispatcher: &Arc<Dispatcher>,
        batch_id: &str,
        pending: Vec<PendingSubBatch>,
        from_flush: bool,
    ) -> anyhow::Result<u32> {
        let mut handles = Vec::with_capacity(pending.len());
        for sub_batch in pending {
            let dispatcher = Arc::clone(dispatcher);
            let PendingSubBatch {
                worker,
                routing_keys,
                key_offsets,
                message_count,
                pending,
            } = sub_batch;
            let bid = batch_id.to_string();

            handles.push(tokio::spawn(async move {
                match pending.wait().await {
                    Ok(accepted) => {
                        // Advance ACK high-water marks before the resolve, which
                        // may evict the keys' sentinel state.
                        dispatcher.on_sub_batch_acked(&key_offsets);
                        dispatcher.on_sub_batch_resolved(
                            &worker,
                            message_count,
                            &routing_keys,
                            from_flush,
                            false,
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
                        // Backpressure (a busy worker) is transient, not a fault:
                        // re-route the work but do not count it against the
                        // worker's health, so passive health tracks real faults.
                        let SendError {
                            error,
                            messages,
                            fence_guard,
                        } = send_err;
                        let is_fault = !error.is_backpressure();
                        dispatcher.defer_failed(&bid, messages);
                        // Stashed: let the worker stream stop fencing new arrivals.
                        drop(fence_guard);
                        dispatcher.on_sub_batch_resolved(
                            &worker,
                            message_count,
                            &routing_keys,
                            from_flush,
                            true,
                        );
                        dispatcher.record_send_outcome(&worker, is_fault);
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
            groups: accumulator.into_groups(),
            partitions,
            stats,
        })
    }

    /// Commit the max offset for each topic-partition.
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

        // Validate contiguity/monotonicity per partition before committing, so
        // a violation is attributed to the batch that caused it.
        self.commit_sentinel.check_commit(
            partitions
                .iter()
                .map(|(topic_partition, partition)| (topic_partition, &partition.span)),
        );

        let mut tpl = TopicPartitionList::new();
        for (topic_partition, partition) in partitions {
            // Commit offset + 1 (Kafka convention: committed offset = next to read)
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(partition.span.last + 1),
            )?;
        }

        self.consumer.commit(&tpl, CommitMode::Async)?;
        for (topic_partition, partition) in partitions {
            self.ledger_shadow.settle(
                topic_partition,
                partition.generation,
                partition.charges.iter().map(|(offset, _)| *offset),
                &partition.span,
            );
        }
        counter!("ingestion_consumer_offset_commits_total").increment(1);

        Ok(())
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
    use rdkafka::message::{Header, OwnedHeaders, OwnedMessage};
    use rdkafka::Timestamp;

    fn delivery(offset: i64) -> Delivery {
        Delivery {
            offset,
            charge: Charge {
                events: 1,
                bytes: 1,
            },
            kafka_ts: offset,
            lag_ms: Some(offset),
        }
    }

    fn charged_offsets(deliveries: &PartitionDeliveries) -> Vec<i64> {
        deliveries
            .charges
            .iter()
            .map(|(offset, _)| offset.0)
            .collect()
    }

    #[test]
    fn a_mid_batch_regain_restarts_the_ledger_slice_and_keeps_the_span() {
        let mut deliveries = PartitionDeliveries::new(3, 7, &delivery(10));
        deliveries.record(
            7,
            || unreachable!("unchanged version, no generation read"),
            &delivery(11),
        );

        // The partition is revoked and regained: Kafka redelivers from the
        // committed offset 5 under generation 4.
        deliveries.record(8, || 4, &delivery(5));
        deliveries.record(
            8,
            || unreachable!("stamped once per version change"),
            &delivery(6),
        );

        assert_eq!(charged_offsets(&deliveries), vec![5, 6]);
        assert_eq!(deliveries.generation, 4);
        assert_eq!(deliveries.span, OffsetSpan { first: 5, last: 11 });
    }

    #[test]
    fn another_partitions_generation_change_keeps_the_slice() {
        let mut deliveries = PartitionDeliveries::new(3, 7, &delivery(10));
        deliveries.record(8, || 3, &delivery(11));

        assert_eq!(charged_offsets(&deliveries), vec![10, 11]);
        assert_eq!(deliveries.generation, 3);
    }

    #[test]
    fn a_partition_keeps_its_max_timestamp_and_lag() {
        let mut deliveries = PartitionDeliveries::new(0, 0, &delivery(10));
        deliveries.record(
            0,
            || 0,
            &Delivery {
                offset: 11,
                charge: Charge::ZERO,
                kafka_ts: 5,
                lag_ms: None,
            },
        );

        assert_eq!(deliveries.latest_kafka_ts, 10);
        assert_eq!(deliveries.max_lag_ms, Some(10));
    }

    #[test]
    fn message_charge_counts_payload_key_and_headers() {
        let headers = OwnedHeaders::new()
            .insert(Header {
                key: "ab",
                value: Some("xyz".as_bytes()),
            })
            .insert(Header {
                key: "c",
                value: None::<&[u8]>,
            });
        let message = OwnedMessage::new(
            Some(vec![0; 10]),
            Some(vec![0; 3]),
            "events".to_string(),
            Timestamp::NotAvailable,
            0,
            0,
            Some(headers),
        );

        let charge = message_charge(&message);
        assert_eq!(charge.events, 1);
        assert_eq!(charge.bytes, 10 + 3 + (2 + 3) + 1);
    }

    #[test]
    fn message_charge_of_an_empty_message_is_one_event() {
        let message = OwnedMessage::new(
            None,
            None,
            "events".to_string(),
            Timestamp::NotAvailable,
            0,
            0,
            None,
        );

        let charge = message_charge(&message);
        assert_eq!(charge.events, 1);
        assert_eq!(charge.bytes, 0);
    }
}
