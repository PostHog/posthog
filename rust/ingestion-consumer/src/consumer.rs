use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{
    AssignmentEpoch, Charge, GroupCompletion, Offset, Partition, TopicOffsetLedger, TopicPartition,
};
use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::{Headers, Message};
use rdkafka::TopicPartitionList;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::batcher::{make_batch_id, Batcher, BatcherObserver, BatcherOutputs, Revoker};
use crate::config::{CompletionGranularity, Config};
use crate::debug_recorder::{
    record_if, CommitOffset, DebugEventKind, DebugRecorder, PartitionOffset, PartitionOffsets,
};
use crate::discovery::DiscoveryMode;
use crate::grpc_transport::GrpcTransport;
use crate::ledger_rejection::{report_rejection, RejectedSlice};
use crate::order_sentinel::OffsetSpan;
use crate::partition_budget::BudgetLimits;
use crate::rebalance::{partition_error, PartitionHook, RebalanceContext};
use crate::settlement::{self, ChargedSlice, Commit, Pause, Settlement};
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
    /// Messages the poll delivered, covered, and accepted from this
    /// partition, so a revoked partition can leave the poll exactly.
    delivered: u32,
    covered: u32,
    accepted: u32,
    /// The offsets a completion covered. Keyed by offset rather than by
    /// position in `span`, because a poll can span an offset gap.
    credited: HashSet<i64, ahash::RandomState>,
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
            delivered: 1,
            covered: 0,
            accepted: 0,
            credited: HashSet::default(),
        }
    }

    /// Credit a completion's run and return the offsets to settle: those
    /// charged under this generation that no earlier completion credited.
    fn credit_run(&mut self, run: &[Offset]) -> Vec<Offset> {
        let Self {
            credited, charges, ..
        } = self;
        run.iter()
            .copied()
            .filter(|offset| {
                credited.insert(offset.0)
                    && charges
                        .binary_search_by_key(&offset.0, |(charged, _)| charged.0)
                        .is_ok()
            })
            .collect()
    }

    fn uncredited_charge(&self) -> Option<Offset> {
        self.charges
            .iter()
            .map(|(offset, _)| *offset)
            .find(|offset| !self.credited.contains(&offset.0))
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
        self.delivered += 1;
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
/// the poll retires only once completions cover every message.
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
    /// Worker-accepted messages so far. The poll retires only when this
    /// reaches `message_count`.
    accepted: u32,
    dispatched_at: Instant,
}

impl InFlightPoll {
    fn is_complete(&self) -> bool {
        self.covered >= self.message_count
    }

    /// A charged offset that no completion covered. A complete poll can still
    /// have one, because one offset credited twice fills `covered` as well.
    fn uncredited_charge(&self) -> Option<(&TopicPartition, Offset)> {
        self.partitions
            .iter()
            .find_map(|(topic_partition, deliveries)| {
                deliveries
                    .uncredited_charge()
                    .map(|offset| (topic_partition, offset))
            })
    }

    fn charged_slices(&self) -> Vec<ChargedSlice<'_>> {
        self.partitions
            .iter()
            .map(|(topic_partition, deliveries)| ChargedSlice {
                topic_partition,
                generation: deliveries.generation,
                span: deliveries.span,
                charges: &deliveries.charges,
            })
            .collect()
    }
}

/// A partition revocation stamped with the ledger generation started by the
/// revoke. Poll slices from earlier generations are stale; slices collected
/// after a later reassignment must survive a delayed notification.
#[derive(Clone, Debug)]
struct RevokedPartition {
    topic_partition: TopicPartition,
    generation: u64,
}

#[derive(Default)]
struct Partitions {
    fetching: HashSet<TopicPartition>,
    paused: HashSet<TopicPartition>,
}

#[derive(Default)]
struct FetchingPartitions {
    partitions: Mutex<Partitions>,
    all_paused: AtomicBool,
}

impl FetchingPartitions {
    fn assigned(&self, topic_partitions: &[TopicPartition]) {
        self.update(|partitions| {
            for topic_partition in topic_partitions {
                partitions.paused.remove(topic_partition);
                partitions.fetching.insert(topic_partition.clone());
            }
        });
    }

    fn revoked(&self, topic_partitions: &[TopicPartition]) {
        self.update(|partitions| {
            for topic_partition in topic_partitions {
                partitions.paused.remove(topic_partition);
                partitions.fetching.remove(topic_partition);
            }
        });
    }

    fn paused(&self, topic_partition: &TopicPartition) {
        self.update(|partitions| {
            if partitions.fetching.remove(topic_partition) {
                partitions.paused.insert(topic_partition.clone());
            }
        });
    }

    fn resumed(&self, topic_partition: &TopicPartition) {
        self.update(|partitions| {
            if partitions.paused.remove(topic_partition) {
                partitions.fetching.insert(topic_partition.clone());
            }
        });
    }

    fn all_paused(&self) -> bool {
        self.all_paused.load(Ordering::Relaxed)
    }

    fn update(&self, change: impl FnOnce(&mut Partitions)) {
        let mut partitions = self.partitions.lock().unwrap();
        change(&mut partitions);
        self.all_paused.store(
            !partitions.paused.is_empty() && partitions.fetching.is_empty(),
            Ordering::Relaxed,
        );
    }
}

/// The consumer's revocation hook: purge the batcher, and record the revoked
/// partitions, because the purge means their polls never complete.
fn revoke_hook(
    revoker: Revoker,
    ledger: Arc<TopicOffsetLedger>,
    settlement: Arc<dyn Settlement>,
    revoked_partitions: Arc<Mutex<Vec<RevokedPartition>>>,
    fetching: Arc<FetchingPartitions>,
) -> PartitionHook {
    Box::new(move |partitions| {
        settlement.forget_partitions(partitions);
        fetching.revoked(partitions);
        let pairs: Vec<(String, i32)> = partitions
            .iter()
            .map(|tp| (tp.topic.clone(), tp.partition))
            .collect();
        revoker.purge_revoked(&pairs);
        revoked_partitions
            .lock()
            .unwrap()
            .extend(partitions.iter().map(|topic_partition| RevokedPartition {
                topic_partition: topic_partition.clone(),
                generation: ledger.generation(topic_partition),
            }));
    })
}

fn assign_hook(
    settlement: Arc<dyn Settlement>,
    fetching: Arc<FetchingPartitions>,
    assignment_epoch: AssignmentEpoch,
) -> PartitionHook {
    Box::new(move |partitions| {
        // Also covers a loss with no revoke callback (an error rebalance, a fenced member).
        settlement.forget_partitions(partitions);
        fetching.assigned(partitions);
        assignment_epoch.bump();
    })
}

fn wire_rebalance_hooks(
    context: &RebalanceContext,
    revoker: Revoker,
    ledger: &Arc<TopicOffsetLedger>,
    settlement: &Arc<dyn Settlement>,
    assignment_epoch: AssignmentEpoch,
) -> (Arc<Mutex<Vec<RevokedPartition>>>, Arc<FetchingPartitions>) {
    let revoked_partitions = Arc::new(Mutex::new(Vec::new()));
    let fetching = Arc::new(FetchingPartitions::default());
    context.set_on_revoke(revoke_hook(
        revoker,
        Arc::clone(ledger),
        Arc::clone(settlement),
        Arc::clone(&revoked_partitions),
        Arc::clone(&fetching),
    ));
    context.set_on_assign(assign_hook(
        Arc::clone(settlement),
        Arc::clone(&fetching),
        assignment_epoch,
    ));
    (revoked_partitions, fetching)
}

/// Remove revoked partitions from in-flight polls, and remove polls left
/// empty. Only slices from before that partition's revoke generation go: a
/// poll's kept or newly reassigned slices retain their counts and settle their
/// ledger charges at commit, so the frontier never crosses a hole.
fn strip_revoked_partitions(
    in_flight_polls: &mut VecDeque<InFlightPoll>,
    revoked: &[RevokedPartition],
) -> u64 {
    let mut stripped: u64 = 0;
    for poll in in_flight_polls.iter_mut() {
        let mut removed_delivered = 0u32;
        let mut removed_covered = 0u32;
        let mut removed_accepted = 0u32;
        poll.partitions.retain(|topic_partition, deliveries| {
            if revoked.iter().any(|revoked| {
                revoked.topic_partition == *topic_partition
                    && deliveries.generation < revoked.generation
            }) {
                removed_delivered += deliveries.delivered;
                removed_covered += deliveries.covered;
                removed_accepted += deliveries.accepted;
                false
            } else {
                true
            }
        });
        if removed_delivered > 0 {
            stripped += u64::from(removed_delivered);
            poll.message_count = poll.message_count.saturating_sub(removed_delivered);
            poll.covered = poll.covered.saturating_sub(removed_covered);
            poll.accepted = poll.accepted.saturating_sub(removed_accepted);
        }
    }
    in_flight_polls.retain(|poll| poll.message_count > 0);
    stripped
}

/// Credit each of a completion's offsets to the poll that contains it: the
/// one collected under the same assignment epoch whose span holds the offset.
/// Within one epoch, poll spans are disjoint per partition, so at most one
/// poll matches per offset. A key-table run merges messages from several
/// polls into one send, so one completion can span polls; crediting per
/// offset keeps every poll's count exact. Acceptance credits the leading
/// offsets, so a worker that under-reports shorts the tail poll's accepted
/// check, matching [`send_group_completions`]'s split across groups. An
/// offset that matches no poll (its partition was revoked and reassigned
/// while the group was out, or its poll is gone) is discarded; a completion
/// with any discarded offset counts as stale once.
///
/// [`send_group_completions`]: crate::batcher
fn apply_completion(
    in_flight: &mut VecDeque<InFlightPoll>,
    completion: &GroupCompletion,
    mut settle: impl FnMut(&TopicPartition, u64, &[Offset]) -> anyhow::Result<()>,
) -> anyhow::Result<()> {
    let fully_accepted = completion.accepted as usize == completion.offsets.len();
    let mut accepted = completion.accepted;
    let mut unmatched: u64 = 0;
    let mut remaining = completion.offsets.as_slice();
    'runs: while let Some(first) = remaining.first() {
        for poll in in_flight
            .iter_mut()
            .filter(|poll| poll.assignment_epoch == completion.assignment_epoch)
        {
            for (topic_partition, deliveries) in poll.partitions.iter_mut() {
                let span = deliveries.span;
                if topic_partition.partition != completion.partition.0
                    || first.0 < span.first
                    || span.last < first.0
                {
                    continue;
                }
                let run_len = remaining
                    .iter()
                    .take_while(|offset| span.first <= offset.0 && offset.0 <= span.last)
                    .count();
                let (run, rest) = remaining.split_at(run_len);
                let run_accepted = accepted.min(run_len as u32);
                accepted -= run_accepted;
                poll.covered += run_len as u32;
                poll.accepted += run_accepted;
                deliveries.covered += run_len as u32;
                deliveries.accepted += run_accepted;
                let settleable = deliveries.credit_run(run);
                if fully_accepted && !settleable.is_empty() {
                    settle(topic_partition, deliveries.generation, &settleable)?;
                }
                remaining = rest;
                continue 'runs;
            }
        }
        unmatched += 1;
        remaining = &remaining[1..];
    }
    if unmatched > 0 {
        counter!("ingestion_consumer_stale_group_completions_total").increment(1);
        warn!(
            partition = %completion.partition,
            unmatched,
            epoch = completion.assignment_epoch,
            "Discarding completion offsets that match no in-flight poll"
        );
    }
    Ok(())
}

/// Pops the front poll for its commit. A complete poll commits only when
/// workers accepted all of it and a completion covered every charged offset.
fn pop_committable(in_flight: &mut VecDeque<InFlightPoll>) -> anyhow::Result<InFlightPoll> {
    let poll = in_flight.pop_front().expect("front is present");
    if poll.accepted < poll.message_count {
        anyhow::bail!(
            "accepted {}/{} messages — not committing offsets",
            poll.accepted,
            poll.message_count
        );
    }
    if let Some((topic_partition, offset)) = poll.uncredited_charge() {
        counter!("ingestion_consumer_commit_violations_total", "kind" => "uncredited").increment(1);
        anyhow::bail!(
            "offset {} of {}/{} has no completion — not committing offsets",
            offset.0,
            topic_partition.topic,
            topic_partition.partition
        );
    }
    Ok(poll)
}

fn commit_tick(granularity: CompletionGranularity, commit_interval: Duration) -> Duration {
    const HEALTH_TICK: Duration = Duration::from_secs(1);
    // A commit can resume a partition, so a tick longer than the commit
    // interval delays the resume.
    match granularity {
        CompletionGranularity::Group if !commit_interval.is_zero() => {
            commit_interval.min(HEALTH_TICK)
        }
        _ => HEALTH_TICK,
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
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    pub debug_recorder: Option<Arc<DebugRecorder>>,
    pub completion_granularity: CompletionGranularity,
    pub commit_interval: Duration,
    pub ledger: Arc<TopicOffsetLedger>,
    pub partition_budget: BudgetLimits,
}

/// The main consumer loop: reads from Kafka, demuxes each poll into groups,
/// submits them to the [`Batcher`] (which routes, dispatches, and flushes),
/// and commits offsets once the batcher's completions cover a poll or a group.
pub struct IngestionConsumer {
    consumer: Arc<StreamConsumer<RebalanceContext>>,
    batcher: Batcher,
    /// Taken once by `process`.
    outputs: Option<BatcherOutputs>,
    transport: Arc<GrpcTransport>,
    worker_urls: Vec<String>,
    batch_size: usize,
    batch_size_bytes: usize,
    batch_timeout: Duration,
    max_in_flight_batches: usize,
    commit_tick: Duration,
    handle: Handle,
    group_id: String,
    /// Debug event recorder; `None` unless `DEBUG_API_ENABLED`.
    debug_recorder: Option<Arc<DebugRecorder>>,
    topic_offset_ledger: Arc<TopicOffsetLedger>,
    /// Partitions revoked since the loop last looked, fed by the rebalance
    /// callback.
    revoked_partitions: Arc<Mutex<Vec<RevokedPartition>>>,
    fetching: Arc<FetchingPartitions>,
    settlement: Arc<dyn Settlement>,
}

impl IngestionConsumer {
    /// Constructs a consumer from pre-built parts. Useful in integration tests
    /// where the Kafka consumer is created and subscribed externally.
    pub fn from_parts(
        consumer: StreamConsumer<RebalanceContext>,
        batcher: Batcher,
        outputs: BatcherOutputs,
        transport: Arc<GrpcTransport>,
        worker_urls: Vec<String>,
        options: IngestionConsumerOptions,
        handle: Handle,
    ) -> Self {
        let topic_offset_ledger = options.ledger;
        let settlement = settlement::for_granularity(
            options.completion_granularity,
            Arc::clone(&topic_offset_ledger),
            options.commit_interval,
            options.partition_budget,
        );
        let (revoked_partitions, fetching) = wire_rebalance_hooks(
            consumer.context(),
            batcher.revoker(),
            &topic_offset_ledger,
            &settlement,
            transport.assignment_epoch(),
        );
        let consumer = Arc::new(consumer);
        Self {
            debug_recorder: options.debug_recorder,
            topic_offset_ledger,
            revoked_partitions,
            fetching,
            settlement,
            consumer,
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_size_bytes: options.batch_size_bytes,
            batch_timeout: options.batch_timeout,
            max_in_flight_batches: options.max_in_flight_batches.max(1),
            commit_tick: commit_tick(options.completion_granularity, options.commit_interval),
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
        batcher
            .key_order_sentinel()
            .set_enabled(config.consumer_order_sentinel_enabled);
        let topic_offset_ledger = Arc::new(TopicOffsetLedger::new());
        let settlement = settlement::for_granularity(
            config.consumer_completion_granularity,
            Arc::clone(&topic_offset_ledger),
            Duration::from_millis(config.consumer_commit_interval_ms),
            config
                .partition_budget()
                .map_err(|err| anyhow::anyhow!("invalid partition budget: {err}"))?,
        );
        let context = RebalanceContext::new();
        let (revoked_partitions, fetching) = wire_rebalance_hooks(
            &context,
            batcher.revoker(),
            &topic_offset_ledger,
            &settlement,
            transport.assignment_epoch(),
        );
        let consumer: StreamConsumer<RebalanceContext> =
            client_config.create_with_context(context)?;
        consumer.subscribe(&[&config.ingestion_consumer_consume_topic])?;
        let consumer = Arc::new(consumer);

        info!(
            topic = %config.ingestion_consumer_consume_topic,
            group = %config.ingestion_consumer_group_id,
            workers = worker_urls.len(),
            batch_size = config.consumer_batch_size,
            batch_size_kb = config.consumer_batch_size_kb,
            completion_granularity = ?config.consumer_completion_granularity,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer,
            debug_recorder,
            topic_offset_ledger,
            revoked_partitions,
            fetching,
            settlement,
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_size_bytes: config.consumer_batch_size_kb.saturating_mul(1024),
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            max_in_flight_batches: config.consumer_max_background_tasks.max(1),
            commit_tick: commit_tick(
                config.consumer_completion_granularity,
                Duration::from_millis(config.consumer_commit_interval_ms),
            ),
            handle,
            group_id: config.ingestion_consumer_group_id.clone(),
        })
    }

    /// A read-only view of the batcher's load.
    pub fn batcher_observer(&self) -> BatcherObserver {
        self.batcher.observer()
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

        info!("Consumer loop starting");
        record_if(&self.debug_recorder, || DebugEventKind::ConsumerStarted {
            group_id: self.group_id.clone(),
            workers: self.worker_urls.clone(),
        });

        self.run(completions, errors).await;
        if let Err(err) = self.commit_all() {
            warn!(error = %err, "Could not submit pending frontiers on exit");
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
            self.drop_revoked_polls(&mut in_flight_polls);
            // Consumer-level concurrency: how many Kafka batches are being
            // processed in parallel, bounded by `max_in_flight_batches`.
            gauge!("ingestion_consumer_in_flight_batches").set(in_flight_polls.len() as f64);

            // Not beside `collect_batch`: a tick there would drop a collection
            // in progress.
            if let Err(err) = self.commit_due() {
                self.fail_commit(err);
                return;
            }

            let collect = accepting_new_batches
                && in_flight_polls.len() < self.max_in_flight_batches
                && (in_flight_polls.is_empty() || !self.every_partition_paused());
            if collect {
                tokio::select! {
                    _ = self.handle.shutdown_recv() => {
                        info!(
                            in_flight = in_flight_polls.len(),
                            "Shutdown signal received, draining in-flight batches"
                        );
                        accepting_new_batches = false;
                        self.batcher.begin_shutdown();
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
            let topic: Arc<str> = Arc::from(topic_partition.topic.as_str());
            let partition: Arc<str> = Arc::from(topic_partition.partition.to_string());
            gauge!(
                "ingestion_consumer_committed_offset",
                "topic" => topic,
                "partition" => partition,
            )
            .set(next_to_read.0 as f64);
        }
        self.consumer.commit(&tpl, CommitMode::Async)?;
        counter!("ingestion_consumer_offset_commits_total").increment(1);
        record_if(&self.debug_recorder, || DebugEventKind::CommitSubmitted {
            offsets: offsets
                .iter()
                .map(|(topic_partition, offset)| CommitOffset {
                    topic: topic_partition.topic.clone(),
                    partition: topic_partition.partition,
                    offset: offset.0,
                })
                .collect(),
        });
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
        emit_poll_stats(
            &stats,
            &partitions,
            message_count,
            &self.group_id,
            self.batch_size,
            self.batch_size_bytes,
        );

        let assignment_epoch = self.batcher.submit(accumulator);
        record_if(&self.debug_recorder, || DebugEventKind::BatchDispatched {
            batch_id: poll_id.clone(),
            messages: message_count,
            partitions: debug_partition_offsets(&partitions),
            assignment_epoch,
            spans: debug_partition_spans(&partitions),
        });

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

    /// Wait for completions to cover the oldest in-flight poll, then retire
    /// it. Completions for newer polls are credited while waiting.
    async fn complete_oldest_poll(
        &self,
        in_flight_polls: &mut VecDeque<InFlightPoll>,
        completions: &mut mpsc::UnboundedReceiver<GroupCompletion>,
        errors: &mut mpsc::UnboundedReceiver<String>,
    ) -> Result<(), Failure> {
        let mut heartbeat = tokio::time::interval_at(
            tokio::time::Instant::now() + self.commit_tick,
            self.commit_tick,
        );
        loop {
            // A rebalance can drop the front poll (its partitions were
            // revoked and its purged messages will never complete), so
            // re-resolve it every pass instead of waiting on it forever.
            self.drop_revoked_polls(in_flight_polls);
            let Some(front) = in_flight_polls.front() else {
                return Ok(());
            };
            if front.is_complete() {
                break;
            }
            tokio::select! {
                completion = completions.recv() => match completion {
                    Some(completion) => {
                        apply_completion(in_flight_polls, &completion, |tp, generation, run| {
                            self.settlement.settle_run(tp, generation, run)
                        })
                        .map_err(Failure::Batch)?;
                        // A resumed partition can fill a poll, so collect instead of waiting here.
                        if self.commit_due().map_err(Failure::Commit)? {
                            return Ok(());
                        }
                    }
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
                    if self.commit_due().map_err(Failure::Commit)?
                        || (in_flight_polls.len() < self.max_in_flight_batches
                            && !self.every_partition_paused())
                    {
                        return Ok(());
                    }
                }
            }
        }

        let poll = pop_committable(in_flight_polls).map_err(Failure::Batch)?;

        self.settlement
            .settle_poll(&poll.charged_slices())
            .map_err(Failure::Batch)?;
        self.commit_due().map_err(Failure::Commit)?;
        emit_latest_processed_timestamp_metrics(&poll.partitions, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::PollCompleted {
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

    /// Drop in-flight polls holding a revoked partition. The key table
    /// purges those partitions' queued messages, so such a poll can never be
    /// covered; its offsets stay uncommitted and replay under the new
    /// assignment, and its late completions are discarded as stale.
    fn drop_revoked_polls(&self, in_flight_polls: &mut VecDeque<InFlightPoll>) {
        let revoked: Vec<RevokedPartition> =
            std::mem::take(&mut *self.revoked_partitions.lock().unwrap());
        if revoked.is_empty() {
            return;
        }
        let stripped = strip_revoked_partitions(in_flight_polls, &revoked);
        if stripped > 0 {
            counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
            info!(
                stripped,
                "Removed revoked partitions' messages from in-flight polls"
            );
        }
    }

    /// Paused partitions fill no poll, so a collection would wait out the batch
    /// timeout before the completions whose commits resume them.
    fn every_partition_paused(&self) -> bool {
        self.fetching.all_paused()
    }

    fn pause_partition(&self, topic_partition: &TopicPartition) {
        let tpl = partition_list(topic_partition);
        match self
            .consumer
            .pause(&tpl)
            .and_then(|()| partition_error(&tpl))
        {
            Ok(()) => self.fetching.paused(topic_partition),
            Err(err) => error!(
                topic = %topic_partition.topic,
                partition = topic_partition.partition,
                error = %err,
                "Could not pause a partition at its budget"
            ),
        }
    }

    fn resume_partition(&self, topic_partition: &TopicPartition) {
        let tpl = partition_list(topic_partition);
        match self
            .consumer
            .resume(&tpl)
            .and_then(|()| partition_error(&tpl))
        {
            Ok(()) => self.fetching.resumed(topic_partition),
            Err(err) => error!(
                topic = %topic_partition.topic,
                partition = topic_partition.partition,
                error = %err,
                "Could not resume a partition under its budget"
            ),
        }
    }

    /// Returns whether the commit resumed a partition.
    fn commit_due(&self) -> anyhow::Result<bool> {
        match self.settlement.take_due(Instant::now()) {
            Some(commit) => self.commit(commit),
            None => Ok(false),
        }
    }

    fn commit_all(&self) -> anyhow::Result<bool> {
        match self.settlement.take_all() {
            Some(commit) => self.commit(commit),
            None => Ok(false),
        }
    }

    fn commit(&self, commit: Commit) -> anyhow::Result<bool> {
        self.commit_offsets(&commit.offsets)?;
        for topic_partition in &commit.resume {
            self.resume_partition(topic_partition);
        }
        Ok(!commit.resume.is_empty())
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
        let mut current_topic: Option<Arc<str>> = None;

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
                    if current_topic.as_deref() != Some(borrowed_message.topic()) {
                        current_topic = Some(Arc::from(borrowed_message.topic()));
                    }
                    let topic = Arc::clone(current_topic.as_ref().expect("set above"));
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
                    let key = TopicPartition::new(topic.to_string(), partition);
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
            // The ledger counts a rejection; it is logged here, where the
            // slice is still known.
            match self
                .settlement
                .charge(topic_partition, partition.generation, &partition.charges)
            {
                Ok(Some(Pause)) => self.pause_partition(topic_partition),
                Ok(None) => {}
                Err(rejection) => report_rejection(
                    "charge",
                    topic_partition,
                    rejection,
                    RejectedSlice::charged(&partition.charges),
                )?,
            }
        }

        Ok(CollectedBatch {
            accumulator,
            partitions,
            stats,
        })
    }
}

fn partition_list(topic_partition: &TopicPartition) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(&topic_partition.topic, topic_partition.partition);
    tpl
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

/// Per-partition offset ranges, so the debug UI can match requests to polls.
fn debug_partition_spans(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
) -> Vec<PartitionOffsets> {
    partitions
        .iter()
        .map(|(topic_partition, partition)| PartitionOffsets {
            topic: topic_partition.topic.clone(),
            partition: topic_partition.partition,
            ranges: vec![(partition.span.first, partition.span.last)],
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
    // Same name as the Node.js consumer's gauge, so one dashboard reads both.
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
    use std::num::NonZeroU64;

    use crate::settlement::{charge_offsets, GroupSettlement};
    use common_kafka_consumer::Offset as MessageOffset;

    fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
        let mut partitions = HashMap::new();
        partitions.insert(
            TopicPartition::new("test", partition),
            PartitionDeliveries {
                span: OffsetSpan { first, last },
                generation: 0,
                generations_version_seen: 0,
                charges: (first..=last)
                    .map(|offset| (MessageOffset(offset), Charge::ZERO))
                    .collect(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: count,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
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

    fn credit(in_flight: &mut VecDeque<InFlightPoll>, completion: GroupCompletion) {
        apply_completion(in_flight, &completion, |_, _, _| Ok(())).unwrap();
    }

    fn partitions(numbers: &[i32]) -> Vec<TopicPartition> {
        numbers
            .iter()
            .map(|&number| TopicPartition::new("events", number))
            .collect()
    }

    #[rstest::rstest]
    #[case::group_below_a_second(CompletionGranularity::Group, 200, 200)]
    #[case::group_above_a_second(CompletionGranularity::Group, 5_000, 1_000)]
    #[case::group_immediate(CompletionGranularity::Group, 0, 1_000)]
    #[case::poll(CompletionGranularity::Poll, 200, 1_000)]
    fn the_commit_tick_follows_the_commit_interval(
        #[case] granularity: CompletionGranularity,
        #[case] commit_interval_ms: u64,
        #[case] expected_ms: u64,
    ) {
        assert_eq!(
            commit_tick(granularity, Duration::from_millis(commit_interval_ms)),
            Duration::from_millis(expected_ms)
        );
    }

    #[test]
    fn every_partition_is_paused_only_while_none_is_fetching() {
        let fetching = FetchingPartitions::default();
        assert!(!fetching.all_paused(), "nothing is assigned");

        fetching.assigned(&partitions(&[0, 1]));
        fetching.paused(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused(), "partition 1 still fetches");

        fetching.paused(&TopicPartition::new("events", 1));
        assert!(fetching.all_paused());

        fetching.resumed(&TopicPartition::new("events", 1));
        assert!(!fetching.all_paused());
    }

    #[test]
    fn a_rebalance_changes_which_partitions_must_be_paused() {
        let fetching = FetchingPartitions::default();
        fetching.assigned(&partitions(&[0, 1]));
        fetching.paused(&TopicPartition::new("events", 0));

        fetching.revoked(&partitions(&[1]));
        assert!(fetching.all_paused(), "only the paused partition is left");

        fetching.assigned(&partitions(&[0]));
        assert!(
            !fetching.all_paused(),
            "a reassigned partition starts fetching"
        );
    }

    #[test]
    fn a_partition_that_is_not_assigned_neither_pauses_nor_resumes() {
        let fetching = FetchingPartitions::default();

        fetching.paused(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused());

        fetching.resumed(&TopicPartition::new("events", 0));
        assert!(!fetching.all_paused());
    }

    #[test]
    fn an_assignment_without_a_revoke_drops_the_partitions_pending_frontier() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement: Arc<dyn Settlement> = Arc::new(GroupSettlement::new(
            Arc::clone(&ledger),
            Duration::from_secs(3600),
            BudgetLimits::new(NonZeroU64::new(1), None, 0.5).expect("valid limits"),
        ));
        let epoch = AssignmentEpoch::new();
        let on_assign = assign_hook(
            Arc::clone(&settlement),
            Arc::new(FetchingPartitions::default()),
            epoch.clone(),
        );
        let p0 = TopicPartition::new("events", 0);
        let one_event = [(
            MessageOffset(10),
            Charge {
                events: 1,
                bytes: 0,
            },
        )];
        assert_eq!(settlement.charge(&p0, 0, &one_event), Ok(Some(Pause)));
        settlement.settle_run(&p0, 0, &[MessageOffset(10)]).unwrap();

        on_assign(std::slice::from_ref(&p0));

        assert!(settlement.take_all().is_none());
        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(epoch.current(), 2);
        assert_eq!(
            settlement.charge(&p0, 1, &one_event),
            Ok(Some(Pause)),
            "the regained partition starts unpaused"
        );
    }

    fn regained_poll(charged: i64, span_last: i64, delivered: u32) -> InFlightPoll {
        let mut poll = poll(1, 0, charged, charged, delivered);
        let deliveries = poll
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap();
        deliveries.span.last = span_last;
        deliveries.generation = 2;
        poll
    }

    #[test]
    fn an_accepted_completion_settles_one_run_per_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        in_flight[1]
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .generation = 1;
        let mut runs = Vec::new();

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            |topic_partition, generation, offsets| {
                runs.push((topic_partition.partition, generation, offsets.to_vec()));
                Ok(())
            },
        )
        .unwrap();

        assert_eq!(
            runs,
            vec![
                (0, 0, vec![MessageOffset(2), MessageOffset(3)]),
                (0, 1, vec![MessageOffset(4), MessageOffset(5)]),
            ],
            "each run carries its own poll's generation"
        );
    }

    #[test]
    fn a_completion_spanning_two_polls_commits_once_the_prefix_is_whole() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        let partition = TopicPartition::new("test", 0);
        charge_offsets(&ledger, &partition, 0, &[0, 1, 2, 3, 4, 5, 6, 7]);
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        let mut settle = |topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]| {
            settlement.settle_run(topic_partition, generation, offsets)
        };

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            &mut settle,
        )
        .unwrap();
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "offsets 0 and 1 are still in flight"
        );

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[0, 1, 6, 7], 4),
            &mut settle,
        )
        .unwrap();
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(partition, MessageOffset(8))]))
        );
    }

    #[test]
    fn a_short_accepted_completion_settles_nothing() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);
        let mut runs = 0;

        apply_completion(&mut in_flight, &completion(1, 0, &[0, 1], 1), |_, _, _| {
            runs += 1;
            Ok(())
        })
        .unwrap();

        assert_eq!(runs, 0, "the ledger must not commit past a dropped message");
        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 1);
    }

    #[test]
    fn a_regained_poll_settles_each_charged_offset_once() {
        // Offsets 8..10, a regain, then offset 8 again: four deliveries, one charge.
        let mut in_flight = VecDeque::from([regained_poll(8, 10, 4)]);
        let mut runs = Vec::new();
        let mut settle = |_: &TopicPartition, generation: u64, offsets: &[Offset]| {
            runs.push((generation, offsets.to_vec()));
            Ok(())
        };

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[8, 9, 10], 3),
            &mut settle,
        )
        .unwrap();
        apply_completion(&mut in_flight, &completion(1, 0, &[8], 1), &mut settle).unwrap();

        assert_eq!(
            runs,
            vec![(2, vec![MessageOffset(8)])],
            "neither the uncharged old offsets nor the redelivered one reach the ledger"
        );
        assert!(in_flight[0].is_complete());
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn apply_completion_spanning_two_polls_credits_each() {
        // A key-table run merges messages from consecutive polls into one
        // send, so its completion spans both spans.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 4));

        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 2);
        assert_eq!(in_flight[1].covered, 2);
        assert_eq!(in_flight[1].accepted, 2);
    }

    #[test]
    fn apply_completion_under_report_shorts_the_tail_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 3));

        assert_eq!(in_flight[0].accepted, 2, "leading offsets are accepted");
        assert_eq!(
            in_flight[1].accepted, 1,
            "the tail poll fails its accepted check"
        );
        assert_eq!(in_flight[1].covered, 2);
    }

    #[test]
    fn a_complete_poll_with_a_charged_offset_no_completion_covered_is_not_committable() {
        let mut in_flight = VecDeque::from([poll(1, 0, 10, 12, 3)]);

        credit(&mut in_flight, completion(1, 0, &[10, 12, 12], 3));

        assert!(in_flight[0].is_complete());
        let error = pop_committable(&mut in_flight)
            .err()
            .expect("offset 11 has no completion");
        assert!(error.to_string().contains("offset 11 "), "{error}");
    }

    #[test]
    fn a_poll_whose_deliveries_span_an_offset_gap_commits() {
        // A compacted or transactional topic skips offsets, so a span can far
        // exceed the poll's message count.
        let mut gapped = poll(1, 0, 0, 0, 2);
        let deliveries = gapped
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap();
        deliveries.span.last = i64::MAX;
        deliveries
            .charges
            .push((MessageOffset(i64::MAX), Charge::ZERO));
        let mut in_flight = VecDeque::from([gapped]);

        credit(&mut in_flight, completion(1, 0, &[0, i64::MAX], 2));

        assert!(in_flight[0].is_complete());
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_keeps_the_other_partitions_slices() {
        // A cooperative rebalance revokes one partition of a two-partition
        // poll. The kept partition's slice must stay accounted, or its
        // ledger charges never settle and its commits freeze at the hole.
        let mut two = poll(1, 0, 0, 1, 4);
        two.partitions.insert(
            TopicPartition::new("test", 1),
            PartitionDeliveries {
                span: OffsetSpan {
                    first: 10,
                    last: 11,
                },
                generation: 0,
                generations_version_seen: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: 2,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
            },
        );
        two.partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .delivered = 2;
        let mut in_flight = VecDeque::from([two]);
        // Partition 1 already had one message covered before the revoke.
        credit(&mut in_flight, completion(1, 1, &[10], 1));

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: TopicPartition::new("test", 1),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 2);
        assert_eq!(in_flight[0].message_count, 2);
        assert_eq!(in_flight[0].covered, 0, "the revoked slice's credit goes");
        assert!(!in_flight[0].is_complete());

        // The kept partition completes the poll; a late completion for the
        // revoked partition is discarded, not credited.
        credit(&mut in_flight, completion(1, 1, &[11], 1));
        assert_eq!(in_flight[0].covered, 0);
        credit(&mut in_flight, completion(1, 0, &[0, 1], 2));
        assert!(in_flight[0].is_complete());
        assert_eq!(in_flight[0].accepted, 2);
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_removes_an_emptied_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 2, 0, 3, 4)]);

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: TopicPartition::new("test", 0),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 4);
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight[0].message_count, 4);
    }

    #[test]
    fn historical_revoke_keeps_a_reassigned_poll_and_its_ledger_slice() {
        let topic_partition = TopicPartition::new("test", 0);
        let ledger = TopicOffsetLedger::new();
        let delivery = Delivery {
            offset: 10,
            charge: Charge {
                events: 1,
                bytes: 1,
            },
            kafka_ts: 0,
            lag_ms: None,
        };

        // This collection saw offset 10 immediately before a revoke, then
        // saw its replay after the partition was assigned again. Only the
        // current generation is charged, while the poll still covers both
        // deliveries that the batcher will complete.
        let mut reassigned_deliveries = PartitionDeliveries::new(
            ledger.generation(&topic_partition),
            ledger.generations_version(),
            &delivery,
        );
        ledger.forget_partitions([("test", 0)]);
        ledger.forget_partitions([("test", 0)]);
        reassigned_deliveries.record(
            ledger.generations_version(),
            || ledger.generation(&topic_partition),
            &delivery,
        );
        assert_eq!(reassigned_deliveries.generation, 2);
        assert_eq!(reassigned_deliveries.delivered, 2);
        assert_eq!(reassigned_deliveries.charges.len(), 1);
        ledger
            .charge(
                &topic_partition,
                reassigned_deliveries.generation,
                reassigned_deliveries.charges.iter().copied(),
            )
            .unwrap();

        // The queued revoke notification belongs to generation 0. It must
        // remove genuine old in-flight work, but not this poll collected and
        // charged under the later reassignment.
        let old_poll = poll(0, 0, 1, 1, 1);
        let reassigned_poll = InFlightPoll {
            poll_id: "reassigned".to_string(),
            assignment_epoch: 1,
            partitions: HashMap::from([(topic_partition.clone(), reassigned_deliveries)]),
            message_count: 2,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        };
        let mut in_flight = VecDeque::from([old_poll, reassigned_poll]);

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: topic_partition.clone(),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 1, "only the old assignment is stripped");
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight[0].poll_id, "reassigned");

        credit(&mut in_flight, completion(1, 0, &[10, 10], 2));
        assert!(in_flight[0].is_complete());
        let reassigned = pop_committable(&mut in_flight)
            .expect("an offset credited twice still counts as credited");
        let retained = reassigned.partitions.get(&topic_partition).unwrap();
        ledger
            .settle(
                &topic_partition,
                retained.generation,
                retained.charges.iter().map(|(offset, _)| *offset),
            )
            .unwrap();
        assert_eq!(
            ledger
                .take_frontier(&topic_partition)
                .map(|taken| taken.offset),
            Some(Offset(11))
        );

        // With the retained replay slice settled, the next accepted offset
        // advances normally instead of remaining stuck behind offset 10.
        ledger
            .charge(
                &topic_partition,
                retained.generation,
                [(Offset(11), delivery.charge)],
            )
            .unwrap();
        ledger
            .settle(&topic_partition, retained.generation, [Offset(11)])
            .unwrap();
        assert_eq!(
            ledger
                .take_frontier(&topic_partition)
                .map(|taken| taken.offset),
            Some(Offset(12))
        );
        assert_eq!(ledger.held(&topic_partition).offsets, 0);
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        // The same offsets exist in two polls when a partition was revoked,
        // reassigned, and replayed. The epoch keeps each incarnation's
        // completions in its own poll.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        credit(&mut in_flight, completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 4);
    }

    #[test]
    fn a_covered_head_is_popped_before_a_redelivered_offset_is_matched() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        let partition = TopicPartition::new("test", 0);
        ledger.forget_partitions([("test", 0)]);
        charge_offsets(&ledger, &partition, 1, &[0, 1]);
        let mut settle = |topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]| {
            settlement.settle_run(topic_partition, generation, offsets)
        };

        // Both polls carry the same offsets: a regain during collection.
        let mut old = poll(3, 0, 0, 1, 2);
        old.poll_id = "old".into();
        let mut replay = poll(3, 0, 0, 1, 2);
        replay.poll_id = "replay".into();
        replay.partitions.get_mut(&partition).unwrap().generation = 1;
        let mut in_flight = VecDeque::from([old, replay]);
        let event = completion(3, 0, &[0, 1], 2);

        apply_completion(&mut in_flight, &event, &mut settle).unwrap();
        assert_eq!(in_flight[0].poll_id, "old");
        assert!(in_flight[0].is_complete());
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "the old generation's settle is stale"
        );
        in_flight.pop_front();

        apply_completion(&mut in_flight, &event, &mut settle).unwrap();
        assert_eq!(in_flight[0].poll_id, "replay");
        assert!(in_flight[0].is_complete());
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(partition, MessageOffset(2))]))
        );
    }
}
