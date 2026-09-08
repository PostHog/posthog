use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{
    Charge, GroupCompletion, Offset, Partition, Rejection, TopicOffsetLedger, TopicPartition,
};
use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::TopicPartitionList;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::batcher::{make_batch_id, Batcher, BatcherOutputs};
use crate::commit_monitor::spawn_commit_monitor;
use crate::commit_pacer::CommitPacer;
use crate::commit_sentinel::{CommitSentinel, CommitViolation};
use crate::config::{CompletionGranularity, Config};
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::discovery::DiscoveryMode;
use crate::dispatcher::Dispatcher;
use crate::grpc_transport::GrpcTransport;
use crate::ledger_rejection::{warn_rejection, RejectedSlice};
use crate::order_sentinel::{OffsetSpan, SentinelContext};
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
/// per message. The span bounds what the batch delivered; the stamped
/// charges feed the ledger.
struct PartitionDeliveries {
    /// The offsets the batch delivered, first to last.
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
    /// redelivers them, so the ledger slice restarts. The span keeps them,
    /// so the commit sentinel still sees the whole delivered range.
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

/// Why the consumer loop stops. The two are reported on separate channels
/// so a dashboard can tell a pipeline failure from a client that can no
/// longer commit.
enum Failure {
    /// A poll could not be collected, dispatched, or completed.
    Batch(anyhow::Error),
    /// An offset commit could not be submitted to the Kafka client.
    Commit(anyhow::Error),
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

    /// Credit the completion to this poll if it was collected under the same
    /// assignment epoch and its span for the partition holds `first`, and
    /// return the slice the offsets were charged as. A completion carries no
    /// topic and no ledger stamp; the poll supplies both.
    fn credit(&mut self, completion: &GroupCompletion, first: i64) -> Option<ChargedSlice<'_>> {
        if self.assignment_epoch != completion.assignment_epoch {
            return None;
        }
        let Self {
            partitions,
            covered,
            accepted,
            ..
        } = self;
        let (topic_partition, deliveries) =
            partitions.iter().find(|(topic_partition, deliveries)| {
                topic_partition.partition == completion.partition.0
                    && deliveries.span.first <= first
                    && first <= deliveries.span.last
            })?;
        *covered += completion.offsets.len() as u32;
        *accepted += completion.accepted;
        Some(ChargedSlice {
            topic_partition,
            generation: deliveries.generation,
        })
    }
}

/// The partition a completion's offsets were charged to, and the ledger
/// generation they were charged under.
struct ChargedSlice<'a> {
    topic_partition: &'a TopicPartition,
    generation: u64,
}

/// Credit a completion to the poll it belongs to: the one collected under the
/// same assignment epoch whose offset span holds the completion's offsets.
/// Within one epoch, poll spans are disjoint per partition, so at most one
/// poll matches. A completion that matches no in-flight poll (its partition
/// was revoked and reassigned while the group was out, or its poll is gone)
/// is discarded and counted.
fn apply_completion<'a>(
    in_flight: &'a mut VecDeque<InFlightPoll>,
    completion: &GroupCompletion,
) -> Option<ChargedSlice<'a>> {
    let first = completion.offsets.first().map(|offset| offset.0)?;
    let charged = in_flight
        .iter_mut()
        .find_map(|poll| poll.credit(completion, first));
    if charged.is_none() {
        counter!("ingestion_consumer_stale_group_completions_total").increment(1);
        warn!(
            partition = %completion.partition,
            offset = first,
            epoch = completion.assignment_epoch,
            "Discarding group completion that matches no in-flight poll"
        );
    }
    charged
}

/// Settle an accepted completion's offsets on the ledger and hand the
/// frontier it advanced, if any, to the sentinel. A completion the workers
/// accepted short of its offsets settles nothing: its poll fails the accepted
/// check, and the frontier stays behind the messages the worker dropped.
fn settle_completion(
    ledger: &TopicOffsetLedger,
    sentinel: &CommitSentinel,
    charged: ChargedSlice<'_>,
    completion: &GroupCompletion,
) {
    if completion.accepted as usize != completion.offsets.len() {
        return;
    }
    let topic_partition = charged.topic_partition;
    let settled = ledger.settle(
        topic_partition,
        charged.generation,
        completion.offsets.iter().copied(),
    );
    match settled {
        Ok(Some(_)) => {
            if let Some(taken) = ledger.take_frontier(topic_partition) {
                sentinel.advance_frontier_unchecked(topic_partition, taken);
            }
        }
        // An earlier group on the partition is still out.
        Ok(None) => {}
        Err(rejection) => warn_rejection(
            "settle",
            topic_partition,
            rejection,
            RejectedSlice::settled(&OffsetSpan {
                first: completion.offsets[0].0,
                last: completion.offsets[completion.offsets.len() - 1].0,
            }),
        ),
    }
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
    /// The unit that settles against the ledger and commits.
    pub completion_granularity: CompletionGranularity,
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
    /// Where settled frontiers go: the sentinel checks each one and passes
    /// it to the pacer, which says when to commit. Shared with the
    /// consumer's [`SentinelContext`], which tells it which partitions leave
    /// the assignment.
    commit_sentinel: Arc<CommitSentinel>,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
    /// The per-partition offset ledger the commit path reads its frontiers
    /// from. Shared with the consumer's [`SentinelContext`], which forgets
    /// partitions on rebalance.
    topic_offset_ledger: Arc<TopicOffsetLedger>,
    /// The unit that settles against the ledger and commits.
    completion_granularity: CompletionGranularity,
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
        // Share the context's ledger and sentinel so rebalance callbacks
        // forget partitions on the same ones the commit path uses.
        let topic_offset_ledger = consumer.context().topic_offset_ledger();
        let commit_sentinel = consumer.context().commit_sentinel();
        let consumer = Arc::new(consumer);
        let (batcher, outputs) = Batcher::new(
            dispatcher,
            Arc::clone(&transport),
            handle.clone(),
            options.deferred_flush_timeout,
        );
        Self {
            commit_sentinel,
            debug_recorder: options.debug_recorder,
            topic_offset_ledger,
            completion_granularity: options.completion_granularity,
            consumer,
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
        let commit_pacer = CommitPacer::for_granularity(
            config.consumer_completion_granularity,
            Duration::from_millis(config.consumer_commit_interval_ms),
        );
        let commit_sentinel = Arc::new(CommitSentinel::new(commit_pacer));
        commit_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        let key_sentinel = batcher.key_order_sentinel();
        key_sentinel.set_enabled(config.consumer_order_sentinel_enabled);
        let topic_offset_ledger = Arc::new(TopicOffsetLedger::new());
        let mut context = SentinelContext::new(
            Arc::clone(&commit_sentinel),
            key_sentinel,
            Arc::clone(&topic_offset_ledger),
        );
        context.set_assignment_epoch(transport.assignment_epoch());
        let consumer: StreamConsumer<SentinelContext> =
            client_config.create_with_context(context)?;
        consumer.subscribe(&[&config.ingestion_consumer_consume_topic])?;
        let consumer = Arc::new(consumer);

        info!(
            topic = %config.ingestion_consumer_consume_topic,
            group = %config.ingestion_consumer_group_id,
            workers = worker_urls.len(),
            batch_size = config.consumer_batch_size,
            batch_size_kb = config.consumer_batch_size_kb,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            commit_sentinel,
            consumer,
            debug_recorder,
            topic_offset_ledger,
            completion_granularity: config.consumer_completion_granularity,
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
            completions,
            errors,
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

        info!(
            completion_granularity = ?self.completion_granularity,
            "Consumer loop starting"
        );
        record_if(&self.debug_recorder, || DebugEventKind::ConsumerStarted {
            group_id: self.group_id.clone(),
            workers: self.worker_urls.clone(),
        });

        let _commit_monitor = spawn_commit_monitor(
            Arc::clone(&self.consumer),
            Arc::clone(&self.commit_sentinel),
            self.handle.clone(),
        );

        self.run(completions, errors).await;
        // Accepted work the pacer still holds would replay after the restart.
        if let Err(err) = self.commit_all() {
            warn!(error = %err, "Could not commit the pending frontiers on exit");
        }
        info!("Consumer loop stopped");
    }

    /// Poll, dispatch, and complete until shutdown drains the in-flight polls
    /// or the loop fails.
    async fn run(
        &self,
        mut completions: mpsc::UnboundedReceiver<GroupCompletion>,
        mut errors: mpsc::UnboundedReceiver<String>,
    ) {
        let mut in_flight_polls: VecDeque<InFlightPoll> = VecDeque::new();
        let mut accepting_new_batches = true;

        while accepting_new_batches || !in_flight_polls.is_empty() {
            // Consumer-level concurrency: how many Kafka batches are being
            // processed in parallel, bounded by `max_in_flight_batches`.
            gauge!("ingestion_consumer_in_flight_batches").set(in_flight_polls.len() as f64);

            // Frontiers the pacer held back while the loop was collecting.
            // Asked here and not beside `collect_batch`, where a due tick
            // would drop a collection in progress.
            if let Err(err) = self.commit_due() {
                self.fail_commit(err);
                return;
            }

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

            if let Err(failure) = self
                .complete_oldest_poll(&mut in_flight_polls, &mut completions, &mut errors)
                .await
            {
                match failure {
                    Failure::Batch(err) => self.fail_batch_processing(err),
                    Failure::Commit(err) => self.fail_commit(err),
                }
                return;
            }
        }
    }

    /// Submit each partition's next-to-read offset to Kafka, asynchronously.
    fn commit_offsets(&self, offsets: &HashMap<TopicPartition, Offset>) -> anyhow::Result<()> {
        let mut tpl = TopicPartitionList::new();
        for (topic_partition, next_to_read) in offsets {
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(next_to_read.0),
            )?;
        }
        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);
        Ok(())
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
    ) -> Result<(), Failure> {
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
                    Some(completion) => self
                        .apply_completions(in_flight_polls, completions, completion)
                        .map_err(Failure::Commit)?,
                    None => return Err(Failure::Batch(anyhow::anyhow!(
                        "batcher completion channel closed"
                    ))),
                },
                failure = errors.recv() => match failure {
                    Some(message) => return Err(Failure::Batch(anyhow::anyhow!(message))),
                    None => return Err(Failure::Batch(anyhow::anyhow!(
                        "batcher error channel closed"
                    ))),
                },
                _ = heartbeat.tick() => {
                    self.handle.report_healthy();
                    self.commit_due().map_err(Failure::Commit)?;
                }
            }
        }

        let poll = in_flight_polls.pop_front().expect("front is present");
        if poll.accepted < poll.message_count {
            return Err(Failure::Batch(anyhow::anyhow!(
                "accepted {}/{} messages — not committing offsets",
                poll.accepted,
                poll.message_count
            )));
        }

        match self.completion_granularity {
            CompletionGranularity::Poll => {
                self.settle_poll(&poll.partitions);
                self.commit_due().map_err(Failure::Commit)?;
            }
            // Each completion settled as it arrived; the pacer commits on
            // its interval.
            CompletionGranularity::Group => {}
        }
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

    /// Apply one wake's completions. At `poll` granularity a completion only
    /// credits its poll. At `group` granularity it also settles on the
    /// ledger; the wake drains what else is queued, then asks the pacer,
    /// which coalesces the frontiers on its interval.
    ///
    /// The drain stops as soon as the oldest poll is covered. The caller pops
    /// that poll before the next completion is matched, and a later poll may
    /// hold the same offsets again: a partition regained inside a batch is
    /// redelivered from its committed offset, and a completion for those
    /// offsets must credit the poll that carried the redelivery, not the one
    /// already covered ahead of it.
    fn apply_completions(
        &self,
        in_flight_polls: &mut VecDeque<InFlightPoll>,
        completions: &mut mpsc::UnboundedReceiver<GroupCompletion>,
        first: GroupCompletion,
    ) -> anyhow::Result<()> {
        if self.completion_granularity == CompletionGranularity::Poll {
            apply_completion(in_flight_polls, &first);
            return Ok(());
        }

        let mut completion = first;
        loop {
            if let Some(charged) = apply_completion(in_flight_polls, &completion) {
                settle_completion(
                    &self.topic_offset_ledger,
                    &self.commit_sentinel,
                    charged,
                    &completion,
                );
            }
            if in_flight_polls
                .front()
                .is_some_and(InFlightPoll::is_complete)
            {
                break;
            }
            let Ok(next) = completions.try_recv() else {
                break;
            };
            completion = next;
        }
        self.commit_due()
    }

    /// Commit what the pacer holds due, if anything.
    fn commit_due(&self) -> anyhow::Result<()> {
        match self.commit_sentinel.take_due(Instant::now()) {
            Some(offsets) => self.commit_offsets(&offsets),
            None => Ok(()),
        }
    }

    /// Commit everything the pacer holds, whatever its interval.
    fn commit_all(&self) -> anyhow::Result<()> {
        match self.commit_sentinel.take_all() {
            Some(offsets) => self.commit_offsets(&offsets),
            None => Ok(()),
        }
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

    /// The Kafka client refused a commit. The commit is asynchronous, so this
    /// is a client that cannot commit at all, not a broker verdict. Consuming
    /// on would freeze the committed position while reporting healthy, so the
    /// process exits and restarts.
    fn fail_commit(&self, err: anyhow::Error) {
        error!(error = %err, "Offset commit failed");
        counter!("ingestion_consumer_commit_errors_total").increment(1);
        record_if(&self.debug_recorder, || DebugEventKind::CommitFailed {
            error: format!("{err:#}"),
        });
        self.handle
            .signal_failure(format!("Offset commit failed: {err:#}"));
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
                    let generations_version = self.topic_offset_ledger.generations_version();
                    match partitions.get_mut(&key) {
                        Some(deliveries) => deliveries.record(
                            generations_version,
                            || self.topic_offset_ledger.generation(&key),
                            &delivery,
                        ),
                        None => {
                            let generation = self.topic_offset_ledger.generation(&key);
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
            // The ledger counts both outcomes and publishes what the window
            // holds; a rejection is logged here, where the slice is still
            // known.
            if let Err(rejection) = self.topic_offset_ledger.charge(
                topic_partition,
                partition.generation,
                partition.charges.iter().copied(),
            ) {
                warn_rejection(
                    "charge",
                    topic_partition,
                    rejection,
                    RejectedSlice::charged(&partition.charges),
                );
            }
        }

        Ok(CollectedBatch {
            accumulator,
            partitions,
            stats,
        })
    }

    /// Settle the poll against the ledger and hand each partition's frontier
    /// over for commit. A partition without a frontier stays on its last
    /// commit.
    fn settle_poll(&self, partitions: &HashMap<TopicPartition, PartitionDeliveries>) {
        if partitions.is_empty() {
            // Unreachable while batches require messages to be spawned; counted
            // so "no empty commits" is a measurable guarantee, not an assumption.
            counter!("ingestion_consumer_commit_violations_total", "kind" => "empty").increment(1);
            warn!("Poll settled with no partitions");
            return;
        }

        let settlement =
            settle_partitions(&self.topic_offset_ledger, &self.commit_sentinel, partitions);

        if settlement.advanced == 0 {
            // `rejected`: the ledger dropped every slice, expected around a
            // rebalance. `no_frontier`: a slice landed, but an earlier batch
            // is still incomplete at the front of every window it settled.
            let reason = if settlement.settled == 0 {
                "rejected"
            } else {
                "no_frontier"
            };
            counter!("ingestion_consumer_commits_skipped_total", "reason" => reason).increment(1);
            warn!(
                reason,
                "No ledger frontier available for completed offsets; skipping commit"
            );
        }
    }
}

/// How a poll settled: how many partitions the ledger accepted, how many of
/// those reached a frontier that was handed over for commit, and what the
/// sentinel found on the way. The sentinel has already counted and logged
/// the violations; they are returned for tests.
struct PollSettlement {
    settled: usize,
    advanced: usize,
    violations: Vec<CommitViolation>,
}

/// Settle each partition's slice against the ledger and hand every frontier
/// reached to the sentinel, with the span the poll delivered for it.
fn settle_partitions(
    ledger: &TopicOffsetLedger,
    sentinel: &CommitSentinel,
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
) -> PollSettlement {
    let mut settlement = PollSettlement {
        settled: 0,
        advanced: 0,
        violations: Vec::new(),
    };
    for (topic_partition, partition) in partitions {
        // A rejected slice is not committed, and the commit sentinel
        // keeps its baseline. A stale slice belongs to an assignment the
        // revoke callback already forgot on the sentinel, so the
        // partition's next commit rebaselines. A violation reset the
        // ledger and dropped what it held, so the partition's next commit
        // can pass work still in flight; the sentinel reports that as the
        // gap it is.
        let Ok(frontier) = settle(ledger, topic_partition, partition) else {
            continue;
        };
        settlement.settled += 1;
        let Some(span) = frontier_span(&partition.span, frontier) else {
            continue;
        };
        let Some(taken) = ledger.take_frontier(topic_partition) else {
            continue;
        };
        settlement
            .violations
            .extend(sentinel.advance_frontier(topic_partition, span, taken));
        settlement.advanced += 1;
    }
    settlement
}

/// Settle one partition's slice of a batch against the ledger and report
/// the frontier it reached. `Err` when the ledger rejected the slice,
/// which it has already counted and this logs.
fn settle(
    ledger: &TopicOffsetLedger,
    topic_partition: &TopicPartition,
    partition: &PartitionDeliveries,
) -> Result<Option<Offset>, Rejection> {
    ledger
        .settle(
            topic_partition,
            partition.generation,
            partition.charges.iter().map(|(offset, _)| *offset),
        )
        .inspect_err(|rejection| {
            warn_rejection(
                "settle",
                topic_partition,
                *rejection,
                RejectedSlice::settled(&partition.span),
            )
        })
}

/// Map a settled frontier back to the span the sentinel checks: the
/// frontier is next-to-read and the span is last-processed, so the span
/// starts at the poll's first delivered offset and ends one before the
/// frontier. `None` for a partition that settled without a frontier; it
/// stays on its last commit.
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
    use crate::commit_sentinel::CommitViolationKind;
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

        let charged = apply_completion(&mut in_flight, &completion(1, 0, &[4, 6], 2))
            .expect("the second poll holds the offsets");
        assert_eq!(charged.topic_partition, &TopicPartition::new("test", 0));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 2);
        assert_eq!(in_flight[1].accepted, 2);
        assert!(!in_flight[1].is_complete());

        apply_completion(&mut in_flight, &completion(1, 0, &[5, 7], 2));
        assert!(in_flight[1].is_complete());
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        // The same offsets exist in two polls when a partition was revoked,
        // reassigned, and replayed. The epoch keeps each incarnation's
        // completions in its own poll.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        apply_completion(&mut in_flight, &completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 4);
    }

    #[test]
    fn apply_completion_discards_a_completion_matching_no_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);

        // Wrong partition, then wrong epoch: neither may be credited.
        assert!(apply_completion(&mut in_flight, &completion(1, 2, &[1], 1)).is_none());
        assert!(apply_completion(&mut in_flight, &completion(9, 0, &[1], 1)).is_none());

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[0].accepted, 0);
    }

    #[test]
    fn apply_completion_reports_the_generation_the_offsets_were_charged_under() {
        // The batcher stamps the completion with the assignment epoch; the
        // ledger settles with the generation the slice was charged under.
        let mut in_flight = VecDeque::from([poll(3, 0, 0, 3, 4)]);
        in_flight[0]
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .expect("the poll charged the partition")
            .generation = 2;

        let charged = apply_completion(&mut in_flight, &completion(3, 0, &[0, 1, 2, 3], 4))
            .expect("the poll holds the offsets");

        assert_eq!(charged.generation, 2);
    }

    /// A poll's slice of one partition, charged to the ledger under the
    /// partition's current generation.
    fn charged(
        ledger: &TopicOffsetLedger,
        topic_partition: &TopicPartition,
        first: i64,
        last: i64,
    ) -> PartitionDeliveries {
        let generation = ledger.generation(topic_partition);
        let partition = PartitionDeliveries {
            span: OffsetSpan { first, last },
            generation,
            generations_version_seen: 0,
            charges: (first..=last)
                .map(|offset| (MessageOffset(offset), Charge::ZERO))
                .collect(),
            latest_kafka_ts: 0,
            max_lag_ms: None,
        };
        ledger
            .charge(
                topic_partition,
                generation,
                partition.charges.iter().copied(),
            )
            .expect("charge");
        partition
    }

    #[test]
    fn a_settled_poll_hands_its_frontier_to_the_pacer() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = CommitSentinel::new(CommitPacer::immediate());
        let tp = TopicPartition::new("test", 0);
        let partitions = HashMap::from([(tp.clone(), charged(&ledger, &tp, 10, 11))]);

        let settlement = settle_partitions(&ledger, &sentinel, &partitions);

        assert_eq!((settlement.settled, settlement.advanced), (1, 1));
        assert_eq!(
            sentinel.take_due(Instant::now()),
            Some(HashMap::from([(tp, MessageOffset(12))]))
        );
    }

    #[test]
    fn a_gap_in_what_kafka_delivered_fires_the_sentinel_and_still_commits() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = CommitSentinel::new(CommitPacer::immediate());
        let tp = TopicPartition::new("test", 0);
        let first = HashMap::from([(tp.clone(), charged(&ledger, &tp, 10, 11))]);
        assert!(settle_partitions(&ledger, &sentinel, &first)
            .violations
            .is_empty());
        assert_eq!(
            sentinel.take_due(Instant::now()),
            Some(HashMap::from([(tp.clone(), MessageOffset(12))]))
        );

        // Offsets 12 and 13 never arrived. The ledger walks the gap, so its
        // take chains from 12; the sentinel must see what was delivered.
        let second = HashMap::from([(tp.clone(), charged(&ledger, &tp, 14, 15))]);
        let settlement = settle_partitions(&ledger, &sentinel, &second);

        assert_eq!(settlement.violations.len(), 1);
        assert_eq!(settlement.violations[0].kind, CommitViolationKind::Gap);
        assert_eq!(settlement.violations[0].prev_committed, 12);
        assert_eq!(settlement.violations[0].span.first, 14);
        assert_eq!(
            sentinel.take_due(Instant::now()),
            Some(HashMap::from([(tp, MessageOffset(16))]))
        );
    }

    #[test]
    fn a_rejected_slice_hands_nothing_to_the_pacer() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = CommitSentinel::new(CommitPacer::immediate());
        let tp = TopicPartition::new("test", 0);
        let partitions = HashMap::from([(tp.clone(), charged(&ledger, &tp, 10, 11))]);
        // The partition left and came back while the poll was in flight.
        ledger.forget_partitions([("test", 0)]);

        let settlement = settle_partitions(&ledger, &sentinel, &partitions);

        assert_eq!((settlement.settled, settlement.advanced), (0, 0));
        assert!(sentinel.take_due(Instant::now()).is_none());
    }

    #[test]
    fn a_poll_behind_an_incomplete_one_hands_nothing_to_the_pacer() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = CommitSentinel::new(CommitPacer::immediate());
        let tp = TopicPartition::new("test", 0);
        let _older = charged(&ledger, &tp, 10, 11);
        let newer = HashMap::from([(tp.clone(), charged(&ledger, &tp, 12, 13))]);

        let settlement = settle_partitions(&ledger, &sentinel, &newer);

        assert_eq!((settlement.settled, settlement.advanced), (1, 0));
        assert!(sentinel.take_due(Instant::now()).is_none());
    }

    #[test]
    fn frontier_span_submits_the_frontier_verbatim() {
        let span = OffsetSpan {
            first: 10,
            last: 11,
        };
        assert_eq!(
            frontier_span(&span, Some(MessageOffset(12))),
            Some(OffsetSpan {
                first: 10,
                last: 11
            })
        );
        assert_eq!(
            frontier_span(&span, Some(MessageOffset(11))),
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

    fn charge_offsets(
        ledger: &TopicOffsetLedger,
        topic_partition: &TopicPartition,
        generation: u64,
        offsets: &[i64],
    ) {
        ledger
            .charge(
                topic_partition,
                generation,
                offsets.iter().map(|&o| (MessageOffset(o), Charge::ZERO)),
            )
            .expect("the test ledger accepts the charge");
    }

    fn charged_slice<'a>(topic_partition: &'a TopicPartition, generation: u64) -> ChargedSlice<'a> {
        ChargedSlice {
            topic_partition,
            generation,
        }
    }

    fn sentinel() -> CommitSentinel {
        CommitSentinel::new(CommitPacer::immediate())
    }

    #[test]
    fn a_partition_commits_only_once_its_completed_prefix_is_contiguous() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = sentinel();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11, 12]);

        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p0, 0),
            &completion(0, 0, &[12], 1),
        );
        assert!(
            sentinel.take_due(Instant::now()).is_none(),
            "the window base is still incomplete"
        );

        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p0, 0),
            &completion(0, 0, &[10, 11], 2),
        );
        assert_eq!(
            sentinel.take_due(Instant::now()),
            Some(HashMap::from([(p0, MessageOffset(13))])),
            "the late completion releases the whole prefix"
        );
    }

    #[test]
    fn a_partition_with_a_held_prefix_does_not_hold_back_another() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = sentinel();
        let p0 = TopicPartition::new("events", 0);
        let p1 = TopicPartition::new("events", 1);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);
        charge_offsets(&ledger, &p1, 0, &[20, 21]);

        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p0, 0),
            &completion(0, 0, &[10, 11], 2),
        );
        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p1, 0),
            &completion(0, 1, &[21], 1),
        );

        assert_eq!(
            sentinel.take_due(Instant::now()),
            Some(HashMap::from([(p0, MessageOffset(12))])),
            "partition 1 waits for offset 20"
        );
    }

    #[test]
    fn a_stale_stamp_completion_commits_nothing() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = sentinel();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10]);

        // The partition is revoked and reassigned while the group is out, so
        // Kafka redelivers the offset under a new ledger generation.
        ledger.forget_partitions([("events", 0)]);
        charge_offsets(&ledger, &p0, 1, &[10]);

        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p0, 0),
            &completion(0, 0, &[10], 1),
        );

        assert!(sentinel.take_due(Instant::now()).is_none());
        assert_eq!(
            ledger.held(&p0).offsets,
            1,
            "the redelivered offset stays uncompleted"
        );
    }

    #[test]
    fn a_short_accepted_completion_never_reaches_the_ledger() {
        let ledger = TopicOffsetLedger::new();
        let sentinel = sentinel();
        let p0 = TopicPartition::new("events", 0);
        charge_offsets(&ledger, &p0, 0, &[10, 11]);

        // The worker under-reports: the ledger must not commit past the
        // messages the worker dropped.
        settle_completion(
            &ledger,
            &sentinel,
            charged_slice(&p0, 0),
            &completion(0, 0, &[10, 11], 1),
        );

        assert!(sentinel.take_due(Instant::now()).is_none());
        assert_eq!(ledger.held(&p0).offsets, 2);
    }
}
