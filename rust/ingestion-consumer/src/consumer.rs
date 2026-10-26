use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{
    AssignmentEpoch, GroupCompletion, Offset, Partition, TopicOffsetLedger, TopicPartition,
};
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::BorrowedMessage;
use rdkafka::TopicPartitionList;
use tokio::sync::mpsc;
use tokio::time::MissedTickBehavior;
use tracing::{error, info, warn};

use crate::batcher::{make_batch_id, Batcher, BatcherObserver, BatcherOutputs, Revoker};
use crate::charge_limit::ChargeLimit;
use crate::config::{CompletionGranularity, Config, Polling};
use crate::debug_recorder::{record_if, CommitOffset, DebugEventKind, DebugRecorder};
use crate::discovery::DiscoveryMode;
use crate::grpc_transport::GrpcTransport;
use crate::ledger_rejection::{report_rejection, RejectedSlice};
use crate::partition_budget::BudgetLimits;
use crate::polling::{
    self, debug_partition_offsets, debug_partition_spans, BatchStats, CappedPolling,
    CollectedBatch, ContinuousPolling, InFlightPoll, PartitionDeliveries, Parts, PollLimits,
    PollingStrategy, Selected, Step,
};
use crate::rebalance::{partition_error, PartitionHook, RebalanceContext};
use crate::settlement::{self, Commit, Settlement};

fn revoke_hook(
    revoker: Revoker,
    settlement: Arc<dyn Settlement>,
    revoked_partitions: Arc<Mutex<Vec<TopicPartition>>>,
) -> PartitionHook {
    Box::new(move |partitions| {
        settlement.forget_partitions(partitions);
        let pairs: Vec<(String, i32)> = partitions
            .iter()
            .map(|tp| (tp.topic.clone(), tp.partition))
            .collect();
        revoker.purge_revoked(&pairs);
        revoked_partitions
            .lock()
            .unwrap()
            .extend_from_slice(partitions);
    })
}

fn assign_hook(
    settlement: Arc<dyn Settlement>,
    assignment_epoch: AssignmentEpoch,
    revoked_partitions: Arc<Mutex<Vec<TopicPartition>>>,
) -> PartitionHook {
    Box::new(move |partitions| {
        // Also covers a loss with no revoke callback (an error rebalance, a fenced member).
        settlement.forget_partitions(partitions);
        assignment_epoch.bump();
        revoked_partitions
            .lock()
            .unwrap()
            .extend_from_slice(partitions);
    })
}

fn wire_rebalance_hooks(
    context: &RebalanceContext,
    revoker: Revoker,
    settlement: &Arc<dyn Settlement>,
    assignment_epoch: AssignmentEpoch,
) -> Arc<Mutex<Vec<TopicPartition>>> {
    let revoked_partitions = Arc::new(Mutex::new(Vec::new()));
    context.set_on_revoke(revoke_hook(
        revoker,
        Arc::clone(settlement),
        Arc::clone(&revoked_partitions),
    ));
    context.set_on_assign(assign_hook(
        Arc::clone(settlement),
        assignment_epoch,
        Arc::clone(&revoked_partitions),
    ));
    revoked_partitions
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
pub struct IngestionConsumerOptions {
    pub batch_size: usize,
    /// Payload-byte bound on a batch; `0` disables it (count-only collection).
    /// See `Config::consumer_batch_size_kb`.
    pub batch_size_bytes: usize,
    pub batch_timeout: Duration,
    /// The capped strategy's admission cap, in polls.
    pub max_in_flight_batches: usize,
    pub polling: Polling,
    pub in_flight_limit: ChargeLimit,
    pub group_id: String,
    pub debug_recorder: Option<Arc<DebugRecorder>>,
    pub completion_granularity: CompletionGranularity,
    pub commit_interval: Duration,
    pub ledger: Arc<TopicOffsetLedger>,
    pub partition_budget: BudgetLimits,
}

/// The main consumer loop: reads from Kafka, demuxes each poll into groups,
/// submits them to the [`Batcher`], and commits offsets once the batcher's
/// completions cover a poll or a group.
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
    polling: Selected,
    commit_tick: Duration,
    handle: Handle,
    group_id: String,
    debug_recorder: Option<Arc<DebugRecorder>>,
    topic_offset_ledger: Arc<TopicOffsetLedger>,
    /// Partitions revoked since the loop last looked, fed by the rebalance
    /// callback.
    revoked_partitions: Arc<Mutex<Vec<TopicPartition>>>,
    settlement: Arc<dyn Settlement>,
}

impl IngestionConsumer {
    /// Constructs a consumer from parts the caller builds. The caller must
    /// subscribe `consumer` to its topic.
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
        let polling = polling::select(
            options.polling,
            options.completion_granularity,
            &options.partition_budget,
            options.in_flight_limit,
            options.max_in_flight_batches,
        );
        let settlement = settlement::for_granularity(
            options.completion_granularity,
            Arc::clone(&topic_offset_ledger),
            options.commit_interval,
            options.partition_budget,
        );
        let revoked_partitions = wire_rebalance_hooks(
            consumer.context(),
            batcher.revoker(),
            &settlement,
            transport.assignment_epoch(),
        );
        let consumer = Arc::new(consumer);
        Self {
            debug_recorder: options.debug_recorder,
            topic_offset_ledger,
            revoked_partitions,
            settlement,
            consumer,
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: options.batch_size,
            batch_size_bytes: options.batch_size_bytes,
            batch_timeout: options.batch_timeout,
            polling,
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
        // Endpointslice mode discovers workers at runtime, so it has no static
        // readiness list.
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
        let partition_budget = config
            .partition_budget()
            .map_err(|err| anyhow::anyhow!("invalid partition budget: {err}"))?;
        let polling = polling::select(
            config.consumer_polling_strategy,
            config.consumer_completion_granularity,
            &partition_budget,
            config.in_flight_limit(),
            config.consumer_max_background_tasks,
        );
        let settlement = settlement::for_granularity(
            config.consumer_completion_granularity,
            Arc::clone(&topic_offset_ledger),
            Duration::from_millis(config.consumer_commit_interval_ms),
            partition_budget,
        );
        let context = RebalanceContext::new();
        let revoked_partitions = wire_rebalance_hooks(
            &context,
            batcher.revoker(),
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
            polling = ?polling,
            "Kafka consumer subscribed"
        );

        Ok(Self {
            consumer,
            debug_recorder,
            topic_offset_ledger,
            revoked_partitions,
            settlement,
            batcher,
            outputs: Some(outputs),
            transport,
            worker_urls,
            batch_size: config.consumer_batch_size,
            batch_size_bytes: config.consumer_batch_size_kb.saturating_mul(1024),
            batch_timeout: Duration::from_millis(config.consumer_batch_timeout_ms),
            polling,
            commit_tick: commit_tick(
                config.consumer_completion_granularity,
                Duration::from_millis(config.consumer_commit_interval_ms),
            ),
            handle,
            group_id: config.ingestion_consumer_group_id.clone(),
        })
    }

    pub fn batcher_observer(&self) -> BatcherObserver {
        self.batcher.observer()
    }

    /// Runs the consumer loop until the lifecycle handle signals shutdown.
    /// First waits until the statically configured workers are ready.
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

        let parts = Parts {
            limits: PollLimits {
                batch_size: self.batch_size,
                batch_size_bytes: self.batch_size_bytes,
                batch_timeout: self.batch_timeout,
            },
            settlement: Arc::clone(&self.settlement),
            group_id: self.group_id.clone(),
            debug_recorder: self.debug_recorder.clone(),
        };
        match self.polling {
            Selected::Capped {
                max_in_flight_polls,
            } => {
                let poller = CappedPolling::new(parts, max_in_flight_polls);
                self.run(poller, completions, errors).await;
            }
            Selected::Continuous { in_flight } => {
                let poller = ContinuousPolling::new(parts, in_flight);
                self.run(poller, completions, errors).await;
            }
        }
        if let Err(err) = self.commit_all() {
            warn!(error = %err, "Could not submit pending frontiers on exit");
        }
        info!("Consumer loop stopped");
    }

    async fn run<P: PollingStrategy>(
        &self,
        mut poller: P,
        mut completions: mpsc::UnboundedReceiver<GroupCompletion>,
        mut errors: mpsc::UnboundedReceiver<String>,
    ) {
        let mut tick = tokio::time::interval(self.commit_tick);
        tick.set_missed_tick_behavior(MissedTickBehavior::Delay);
        let poll_deadline = tokio::time::sleep(Duration::ZERO);
        tokio::pin!(poll_deadline);
        let mut accepting_new_batches = true;
        loop {
            let mut submitted = false;
            while let Some(step) = poller.next_step(tokio::time::Instant::now()) {
                submitted |= matches!(step, Step::Submit(_));
                if let Err(failure) = self.carry_out(step, &mut poller) {
                    match failure {
                        Stopped::Drained => {}
                        Stopped::Commit(err) => self.fail_commit(err),
                        Stopped::Batch(err) => self.fail_batch_processing(err),
                    }
                    return;
                }
            }
            // rdkafka's stream spends none of tokio's budget, so a ready
            // backlog keeps `recv` ready on every turn and this loop would
            // never yield. The batcher runs on this runtime.
            if submitted {
                tokio::task::yield_now().await;
            }

            let deadline = poller.deadline();
            if let Some(deadline) = deadline {
                if poll_deadline.deadline() != deadline {
                    poll_deadline.as_mut().reset(deadline);
                }
            }
            let reading = poller.reading();
            let woke = tokio::select! {
                _ = self.handle.shutdown_recv(), if accepting_new_batches => Woke::Shutdown,
                completion = completions.recv() => Woke::Completion(completion),
                failure = errors.recv() => Woke::Error(failure),
                _ = tick.tick() => Woke::Tick,
                _ = &mut poll_deadline, if deadline.is_some() => Woke::Deadline,
                received = self.consumer.recv(), if reading => Woke::Received(received),
            };
            // The rebalance callbacks run inside `recv`, also inside one the
            // select dropped, so the poller sees each revoke before it acts
            // on anything that woke the loop.
            self.hand_over_revokes(&mut poller);

            let failure = match woke {
                Woke::Shutdown => {
                    info!("Shutdown signal received, draining in-flight batches");
                    accepting_new_batches = false;
                    self.batcher.begin_shutdown();
                    poller.shutdown();
                    None
                }
                Woke::Completion(Some(completion)) => poller.completed(&completion).err(),
                Woke::Completion(None) => {
                    Some(anyhow::anyhow!("batcher completion channel closed"))
                }
                Woke::Error(Some(message)) => Some(anyhow::anyhow!(message)),
                Woke::Error(None) => Some(anyhow::anyhow!("batcher error channel closed")),
                Woke::Tick => {
                    self.handle.report_healthy();
                    poller.ticked();
                    None
                }
                Woke::Deadline => None,
                Woke::Received(Ok(message)) => {
                    poller.received(&message, tokio::time::Instant::now());
                    None
                }
                Woke::Received(Err(err)) => self.recv_failed(err).err(),
            };
            if let Some(err) = failure {
                self.fail_batch_processing(err);
                return;
            }
        }
    }

    fn carry_out<P: PollingStrategy>(&self, step: Step, poller: &mut P) -> Result<(), Stopped> {
        match step {
            Step::Submit(collected) => {
                let poll = self.submit_poll(collected).map_err(Stopped::Batch)?;
                poller.submitted(poll);
                self.handle.report_healthy();
                Ok(())
            }
            Step::Commit(commit) => self.commit(commit).map_err(Stopped::Commit),
            Step::Stop => Err(Stopped::Drained),
            Step::Fail(err) => Err(Stopped::Batch(err)),
        }
    }

    fn hand_over_revokes<P: PollingStrategy>(&self, poller: &mut P) {
        let revoked = std::mem::take(&mut *self.revoked_partitions.lock().unwrap());
        if !revoked.is_empty() {
            poller.revoked(&revoked);
        }
    }

    fn recv_failed(&self, err: KafkaError) -> anyhow::Result<()> {
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
        Ok(())
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

    fn submit_poll(&self, collected: CollectedBatch) -> anyhow::Result<InFlightPoll> {
        let CollectedBatch {
            accumulator,
            mut partitions,
            stats,
        } = collected;
        let mut uncommitted = HashMap::with_capacity(partitions.len());
        let mut generations = HashMap::with_capacity(partitions.len());
        // One ledger call per partition keeps the lock and the gauge labels
        // off the per-message path.
        for (topic_partition, partition) in &mut partitions {
            partition.generation = self.topic_offset_ledger.generation(topic_partition);
            generations.insert(Partition(topic_partition.partition), partition.generation);
            match self
                .settlement
                .charge(topic_partition, partition.generation, &partition.charges)
            {
                Ok(charged) => {
                    if charged.pause.is_some() {
                        self.pause_partition(topic_partition);
                    }
                    uncommitted.insert(topic_partition.clone(), charged.uncommitted);
                }
                Err(rejection) => report_rejection(
                    "charge",
                    topic_partition,
                    rejection,
                    RejectedSlice::charged(&partition.charges),
                )?,
            }
        }

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

        let assignment_epoch = self.batcher.submit(accumulator, &generations);
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

        Ok(InFlightPoll {
            poll_id,
            assignment_epoch,
            partitions,
            uncommitted,
            message_count: message_count as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        })
    }

    fn pause_partition(&self, topic_partition: &TopicPartition) {
        let tpl = partition_list(topic_partition);
        if let Err(err) = self
            .consumer
            .pause(&tpl)
            .and_then(|()| partition_error(&tpl))
        {
            error!(
                topic = %topic_partition.topic,
                partition = topic_partition.partition,
                error = %err,
                "Could not pause a partition at its budget"
            );
        }
    }

    fn resume_partition(&self, topic_partition: &TopicPartition) {
        let tpl = partition_list(topic_partition);
        if let Err(err) = self
            .consumer
            .resume(&tpl)
            .and_then(|()| partition_error(&tpl))
        {
            error!(
                topic = %topic_partition.topic,
                partition = topic_partition.partition,
                error = %err,
                "Could not resume a partition under its budget"
            );
        }
    }

    fn commit_all(&self) -> anyhow::Result<()> {
        match self.settlement.take_all() {
            Some(commit) => self.commit(commit),
            None => Ok(()),
        }
    }

    fn commit(&self, commit: Commit) -> anyhow::Result<()> {
        self.commit_offsets(&commit.offsets)?;
        for topic_partition in &commit.resume {
            self.resume_partition(topic_partition);
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
}

enum Woke<'a> {
    Shutdown,
    Completion(Option<GroupCompletion>),
    Error(Option<String>),
    Tick,
    Deadline,
    Received(Result<BorrowedMessage<'a>, KafkaError>),
}

enum Stopped {
    Drained,
    Commit(anyhow::Error),
    Batch(anyhow::Error),
}

fn partition_list(topic_partition: &TopicPartition) -> TopicPartitionList {
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition(&topic_partition.topic, topic_partition.partition);
    tpl
}

/// Per-poll metrics, most with the same names as the Node.js consumer's.
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

    // Matches Node.js `consumer_batch_utilization`.
    if max_batch_size > 0 {
        gauge!("consumer_batch_utilization", "groupId" => group_id.to_string())
            .set(batch_size as f64 / max_batch_size as f64);
    }

    // The same ratio against the byte bound. On lanes with large events the
    // byte bound ends collection first, so the count ratio stays low while
    // batches are full. Absent when the byte bound is disabled.
    if max_batch_bytes > 0 {
        gauge!("consumer_batch_utilization_bytes", "groupId" => group_id.to_string())
            .set(stats.total_bytes as f64 / max_batch_bytes as f64);
    }

    // Matches Node.js.
    histogram!("consumer_batch_size").record(batch_size as f64);
    histogram!("consumer_batch_size_kb").record(stats.total_bytes as f64 / 1024.0);

    // Matches Node.js.
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

    // Matches Node.js.
    for (partition, lag_ms) in &stats.message_lags_ms {
        histogram!(
            "ingestion_lag_ms_histogram",
            "groupId" => group_id.to_string(),
            "partition" => partition.to_string()
        )
        .record(*lag_ms as f64);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::num::NonZeroU64;

    use common_kafka_consumer::{Charge, Offset as MessageOffset};

    use crate::settlement::{GroupSettlement, Pause};

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
    fn an_assignment_without_a_revoke_drops_the_partitions_pending_frontier() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement: Arc<dyn Settlement> = Arc::new(GroupSettlement::new(
            Arc::clone(&ledger),
            Duration::from_secs(3600),
            BudgetLimits::new(NonZeroU64::new(1), None, 0.5).expect("valid limits"),
        ));
        let epoch = AssignmentEpoch::new();
        let revoked_partitions = Arc::new(Mutex::new(Vec::new()));
        let on_assign = assign_hook(
            Arc::clone(&settlement),
            epoch.clone(),
            Arc::clone(&revoked_partitions),
        );
        let p0 = TopicPartition::new("events", 0);
        let one_event = [(
            MessageOffset(10),
            Charge {
                events: 1,
                bytes: 0,
            },
        )];
        assert_eq!(
            settlement
                .charge(&p0, 0, &one_event)
                .map(|charged| charged.pause),
            Ok(Some(Pause))
        );
        settlement.settle_run(&p0, 0, &[MessageOffset(10)]).unwrap();

        on_assign(std::slice::from_ref(&p0));

        assert!(settlement.take_all().is_none());
        assert_eq!(ledger.generation(&p0), 1);
        assert_eq!(epoch.current(), 2);
        assert_eq!(
            *revoked_partitions.lock().unwrap(),
            vec![p0.clone()],
            "the poller drops what it buffered from the lost assignment"
        );
        assert_eq!(
            settlement
                .charge(&p0, 1, &one_event)
                .map(|charged| charged.pause),
            Ok(Some(Pause)),
            "the regained partition starts unpaused"
        );
    }
}
