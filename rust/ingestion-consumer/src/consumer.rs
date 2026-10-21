use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{
    AssignmentEpoch, GroupCompletion, Offset, TopicOffsetLedger, TopicPartition,
};
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::TopicPartitionList;
use tokio::sync::mpsc;
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
    self, debug_partition_offsets, debug_partition_spans, BatchStats, CollectedBatch, Collector,
    FetchingPartitions, InFlightPoll, LoopParts, PartitionDeliveries, PollLimits, PollingStrategy,
    RevokedPartition, Selected, Step,
};
use crate::rebalance::{partition_error, PartitionHook, RebalanceContext};
use crate::settlement::{self, Commit, Pause, Settlement};

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
    /// The capped strategy's admission cap, in polls.
    pub max_in_flight_batches: usize,
    pub polling: Polling,
    pub in_flight_limit: ChargeLimit,
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
    polling: Selected,
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
            polling = ?polling,
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
            polling,
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

        let mut polling = self.polling_strategy(completions, errors);
        self.run(&mut polling).await;
        if let Err(err) = self.commit_all() {
            warn!(error = %err, "Could not submit pending frontiers on exit");
        }
        info!("Consumer loop stopped");
    }

    fn polling_strategy(
        &self,
        completions: mpsc::UnboundedReceiver<GroupCompletion>,
        errors: mpsc::UnboundedReceiver<String>,
    ) -> PollingStrategy {
        let parts = LoopParts {
            collector: Collector::new(
                Arc::clone(&self.consumer),
                Arc::clone(&self.topic_offset_ledger),
                PollLimits {
                    batch_size: self.batch_size,
                    batch_size_bytes: self.batch_size_bytes,
                    batch_timeout: self.batch_timeout,
                },
                self.handle.clone(),
            ),
            completions,
            errors,
            settlement: Arc::clone(&self.settlement),
            fetching: Arc::clone(&self.fetching),
            revoked_partitions: Arc::clone(&self.revoked_partitions),
            handle: self.handle.clone(),
            commit_tick: self.commit_tick,
            group_id: self.group_id.clone(),
            debug_recorder: self.debug_recorder.clone(),
        };
        PollingStrategy::new(self.polling, parts)
    }

    async fn run(&self, polling: &mut PollingStrategy) {
        loop {
            match polling.next().await {
                Step::Submit(collected) => match self.submit_poll(collected) {
                    Ok(poll) => {
                        polling.submitted(poll);
                        self.handle.report_healthy();
                    }
                    Err(err) => {
                        self.fail_batch_processing(err);
                        return;
                    }
                },
                Step::Commit(commit) => {
                    if let Err(err) = self.commit(commit) {
                        self.fail_commit(err);
                        return;
                    }
                }
                Step::BeginShutdown => self.batcher.begin_shutdown(),
                Step::Stop => return,
                Step::Fail(err) => {
                    self.fail_batch_processing(err);
                    return;
                }
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

    /// Charges before it submits, so that no completion settles an uncharged
    /// offset.
    fn submit_poll(&self, collected: CollectedBatch) -> anyhow::Result<InFlightPoll> {
        let CollectedBatch {
            accumulator,
            partitions,
            stats,
        } = collected;
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

        Ok(InFlightPoll {
            poll_id,
            assignment_epoch,
            partitions,
            message_count: message_count as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        })
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::num::NonZeroU64;

    use common_kafka_consumer::{Charge, Offset as MessageOffset};

    use crate::settlement::GroupSettlement;

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
}
