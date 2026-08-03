//! The `cohort_stream_seed_events` follower consumer — the backfill day-tile input.
//!
//! Assignment arrives via the events group's rebalance mirror. Four admission gates share one
//! holdover + pause mechanism: the apply fence (a tile dispatches only once its partition's live
//! watermark clears `s_chunk + margin`), a full worker channel, live-priority (the partition's
//! live watermark age crossed the pause threshold — live traffic always wins), and pod-wide disk
//! pressure. An un-dispatched tile was never `mark_dispatched`ed, so its offset cannot commit.
//! Consume-side skips ride the worker channel so their offsets mark in order; they never close
//! the fence, but a live-lag/disk gate holds them too (nothing leapfrogs a gated partition).
//! The [`PauseLedger`] records why each partition is held and since when; the pause target and
//! the age/count gauges all derive from it.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, Instant};

use cohort_core::seed::{decode_seed, DecodedSeed, PersonSeed, ReconcileTile, SChunkMs, SeedTile};
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use tracing::{debug, info, warn};

use crate::consumers::events::{fsync_then_commit, run_pauser_loop, EventDispatcher};
use crate::consumers::merges::owned_committable_offsets;
use crate::observability::disk::{DiskUtilization, SharedDiskUtilization};
use crate::observability::metrics::{
    COHORT_STREAM_KAFKA_RECV_ERRORS, COHORT_STREAM_SEEDS_CONSUMED,
    COHORT_STREAM_SEEDS_CONSUME_BATCH_SIZE, COHORT_STREAM_SEED_DESERIALIZE_ERRORS,
    LIVE_WATERMARK_AGE_MS, SEED_FENCED_PARTITIONS, SEED_FENCE_DEFICIT_MS,
    SEED_IDLE_PROBE_DURATION_SECONDS, SEED_IDLE_PROBE_LAST_PASS_TIMESTAMP_SECONDS,
    SEED_NO_WATERMARK_PARTITIONS, SEED_OLDEST_HELD_AGE_MS, SEED_PAUSED_PARTITIONS,
    SEED_PAUSE_AGE_MS,
};
use crate::partitions::backpressure::PartitionHoldover;
use crate::partitions::pacing::{
    AgeMs, CauseSet, Hysteresis, PauseCause, PauseLedger, SeedPacing, SeedPacingConfig, UsedPct,
};
use crate::partitions::pause::PartitionPauser;
use crate::partitions::rebalance::CohortConsumerContext;
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::partitions::watermarks::WatermarkMs;

/// Back-off after a Kafka transport error, mirroring the sibling consume loops.
const RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// Timeout for the idle probe's blocking watermark/committed fetches.
const PROBE_FETCH_TIMEOUT: Duration = Duration::from_secs(5);

/// Why a consumed seed payload is skipped rather than applied.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SeedSkipReason {
    /// A kind the current worker path does not handle.
    UnknownKind,
    /// A newer schema version. The skip commits and never replays, so this consumer must be
    /// upgraded before any seeder emits a new schema.
    UnsupportedSchema,
    /// Empty or undecodable payload: deterministic bytes, so halting would wedge the partition.
    DecodeError,
}

impl SeedSkipReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UnknownKind => "unknown_kind",
            Self::UnsupportedSchema => "unsupported_schema",
            Self::DecodeError => "decode_error",
        }
    }
}

/// A decoded unit of seed work, routed to the owning partition worker.
#[derive(Debug)]
pub enum SeedWork {
    Tile(SeedTile),
    Person(PersonSeed),
    Reconcile(ReconcileTile),
    Skip(SeedSkipReason),
}

/// One message consumed from `cohort_stream_seed_events`, paired with its commit coordinates.
#[derive(Debug)]
pub struct ConsumedSeed {
    pub work: SeedWork,
    pub partition: i32,
    pub offset: i64,
    /// Broker timestamp of the consumed message — the oldest-held age gauge's input. `None`
    /// (`Timestamp::NotAvailable`) reads as age 0.
    pub broker_ts_ms: Option<i64>,
}

impl ConsumedSeed {
    pub(crate) fn into_message(self) -> ShuffleMessage {
        ShuffleMessage::Seed {
            work: Box::new(self.work),
            offset: self.offset,
            broker_ts_ms: self.broker_ts_ms,
        }
    }

    /// Inverse of [`into_message`](Self::into_message); `None` for a non-seed message.
    pub(crate) fn from_message(partition: i32, message: ShuffleMessage) -> Option<Self> {
        match message {
            ShuffleMessage::Seed {
                work,
                offset,
                broker_ts_ms,
            } => Some(Self {
                work: *work,
                partition,
                offset,
                broker_ts_ms,
            }),
            _ => None,
        }
    }

    /// The fence input. Control messages, person seeds, and skips are fence-open: none of them
    /// bounds the arrival of events over the live stream.
    fn s_chunk_ms(&self) -> Option<SChunkMs> {
        match &self.work {
            SeedWork::Tile(tile) => Some(tile.s_chunk_ms()),
            SeedWork::Person(_) | SeedWork::Reconcile(_) | SeedWork::Skip(_) => None,
        }
    }
}

/// The apply-fence verdict for one tile.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FenceDecision {
    Open,
    /// How far the watermark trails `s_chunk + margin`; `None` = no watermark at all.
    Closed {
        deficit_ms: Option<i64>,
    },
}

/// Open only when the watermark exceeds `s_chunk + margin`; an absent watermark is fail-closed.
pub(crate) fn fence_decision(
    watermark: Option<WatermarkMs>,
    s_chunk: SChunkMs,
    margin_ms: i64,
) -> FenceDecision {
    let Some(WatermarkMs(watermark_ms)) = watermark else {
        return FenceDecision::Closed { deficit_ms: None };
    };
    let bound = s_chunk.0.saturating_add(margin_ms);
    if watermark_ms > bound {
        FenceDecision::Open
    } else {
        FenceDecision::Closed {
            deficit_ms: Some(bound - watermark_ms),
        }
    }
}

/// The gates evaluated at admission, beyond the per-tile fence.
pub(crate) struct AdmissionPolicy<'a, F: Fn(i32) -> Option<WatermarkMs>> {
    pub fence_margin_ms: i64,
    pub watermark_of: F,
    /// Partitions gated by live-priority: hold everything, including leading skips.
    pub live_lagging: &'a HashSet<i32>,
    /// Pod-wide disk gate: hold everything for every partition.
    pub disk_pressure: bool,
}

/// A consumed batch split at the admission gates, preserving per-partition FIFO.
#[derive(Debug, Default)]
pub(crate) struct AdmissionSplit {
    pub admitted: Vec<ConsumedSeed>,
    pub held: HashMap<i32, Vec<ConsumedSeed>>,
    /// Why each partition that closed in this split is held.
    pub causes: HashMap<i32, CauseSet>,
    /// Deficit per partition whose fence closed in this split.
    pub deficits: HashMap<i32, Option<i64>>,
}

/// Admit each partition's open prefix; from the first fence-closed tile hold everything for that
/// partition (skips included) so nothing leapfrogs a held offset. A gated partition
/// (live-lag/disk) holds everything from its first message, leading skips included.
/// `already_held` partitions queue entirely behind their holdover (their causes were attributed
/// when the holdover re-split this cycle).
pub(crate) fn split_for_admission<F: Fn(i32) -> Option<WatermarkMs>>(
    seeds: Vec<ConsumedSeed>,
    already_held: &HashSet<i32>,
    policy: &AdmissionPolicy<'_, F>,
) -> AdmissionSplit {
    let mut split = AdmissionSplit::default();
    let mut closed: HashSet<i32> = HashSet::new();
    // Gated partitions whose first tile has not been fence-probed yet: even when gated, the first
    // tile still evaluates the fence so the fence cause and deficit stay continuous through a
    // live-lag/disk episode.
    let mut fence_probe_pending: HashSet<i32> = HashSet::new();
    for seed in seeds {
        let partition = seed.partition;
        if already_held.contains(&partition) {
            split.held.entry(partition).or_default().push(seed);
            continue;
        }
        if !closed.contains(&partition) {
            let gate = gate_causes(policy, partition);
            if !gate.is_empty() {
                closed.insert(partition);
                fence_probe_pending.insert(partition);
                split.causes.insert(partition, gate);
            }
        }
        if closed.contains(&partition) {
            if fence_probe_pending.contains(&partition) {
                if let Some(s_chunk) = seed.s_chunk_ms() {
                    fence_probe_pending.remove(&partition);
                    if let FenceDecision::Closed { deficit_ms } = fence_decision(
                        (policy.watermark_of)(partition),
                        s_chunk,
                        policy.fence_margin_ms,
                    ) {
                        split
                            .causes
                            .entry(partition)
                            .or_default()
                            .insert(PauseCause::Fence);
                        split.deficits.insert(partition, deficit_ms);
                    }
                }
            }
            split.held.entry(partition).or_default().push(seed);
            continue;
        }
        let decision = match seed.s_chunk_ms() {
            None => FenceDecision::Open,
            Some(s_chunk) => fence_decision(
                (policy.watermark_of)(partition),
                s_chunk,
                policy.fence_margin_ms,
            ),
        };
        match decision {
            FenceDecision::Open => split.admitted.push(seed),
            FenceDecision::Closed { deficit_ms } => {
                closed.insert(partition);
                split
                    .causes
                    .entry(partition)
                    .or_default()
                    .insert(PauseCause::Fence);
                split.deficits.insert(partition, deficit_ms);
                split.held.entry(partition).or_default().push(seed);
            }
        }
    }
    split
}

/// The partition-level gate verdict under `policy`, independent of any tile.
fn gate_causes<F: Fn(i32) -> Option<WatermarkMs>>(
    policy: &AdmissionPolicy<'_, F>,
    partition: i32,
) -> CauseSet {
    let mut causes = CauseSet::default();
    if policy.live_lagging.contains(&partition) {
        causes.insert(PauseCause::LiveLag);
    }
    if policy.disk_pressure {
        causes.insert(PauseCause::DiskPressure);
    }
    causes
}

/// Holdover of fence-closed, backpressured, or pacing-gated seeds.
type SeedHoldover = PartitionHoldover<ConsumedSeed>;

/// The holdover flattened in per-partition FIFO order.
fn drain_held(holdover: &mut SeedHoldover) -> Vec<ConsumedSeed> {
    holdover
        .take_held()
        .into_iter()
        .flat_map(|(_, seeds)| seeds)
        .collect()
}

/// One pass over the owned partitions: watermark ages (for the age gauge), the live-lag verdicts,
/// and the no-watermark count.
#[derive(Debug, Default)]
struct LiveLagAssessment {
    /// Partitions whose seed applies must yield to live consumption this cycle.
    lagging: HashSet<i32>,
    /// Watermark age per partition that has one.
    ages_ms: HashMap<i32, i64>,
    /// Owned partitions with no watermark at all: fence-fail-closed with an unknown deficit, so
    /// otherwise invisible on the deficit gauge.
    no_watermark: usize,
}

/// An absent watermark is never a live-lag hold — tiles are already fence-fail-closed there, and
/// a redundant hold would poison the hysteresis memory on a new tenure — it is only counted.
fn assess_live_lag(
    owned: &HashSet<i32>,
    watermark_of: impl Fn(i32) -> Option<WatermarkMs>,
    ledger: &PauseLedger,
    hysteresis: Option<Hysteresis<AgeMs>>,
    now_ms: i64,
) -> LiveLagAssessment {
    let mut assessment = LiveLagAssessment::default();
    for &partition in owned {
        let Some(WatermarkMs(watermark_ms)) = watermark_of(partition) else {
            assessment.no_watermark += 1;
            continue;
        };
        let age_ms = now_ms.saturating_sub(watermark_ms);
        assessment.ages_ms.insert(partition, age_ms);
        let Some(hysteresis) = hysteresis else {
            continue;
        };
        let engaged = ledger.has_cause(partition, PauseCause::LiveLag);
        if hysteresis.decide(engaged, AgeMs(age_ms)) {
            assessment.lagging.insert(partition);
        }
    }
    assessment
}

/// This cycle's per-partition causes: the two splits' verdicts unioned, plus `ChannelFull` for
/// every partition whose dispatch bounced. Feeds [`PauseLedger::reconcile`], so a partition absent
/// here has drained and its episode ends.
fn merge_cycle_causes(
    refence: HashMap<i32, CauseSet>,
    fresh: HashMap<i32, CauseSet>,
    bounced: impl IntoIterator<Item = i32>,
) -> HashMap<i32, CauseSet> {
    let mut merged = refence;
    for (partition, causes) in fresh {
        let entry = merged.entry(partition).or_default();
        *entry = entry.union(causes);
    }
    for partition in bounced {
        merged
            .entry(partition)
            .or_default()
            .insert(PauseCause::ChannelFull);
    }
    merged
}

/// The admission core of one consume cycle: prune revoked state, assess the gates, split and
/// dispatch held seeds before fresh ones, reconcile the ledger, and emit the pacing gauges.
/// Both clock readings are inputs, so tests can drive it without a consumer.
#[allow(clippy::too_many_arguments)]
fn run_admission_cycle(
    dispatcher: &EventDispatcher,
    pacing_config: &SeedPacingConfig,
    disk_sample: Option<DiskUtilization>,
    fence_margin_ms: i64,
    seeds: Vec<ConsumedSeed>,
    holdover: &mut SeedHoldover,
    pacing: &mut SeedPacing,
    prev_paused_target: &mut HashSet<i32>,
    pause_tx: &tokio::sync::mpsc::UnboundedSender<HashSet<i32>>,
    now_ms: i64,
    now: Instant,
) {
    let owned = dispatcher.owned_set();
    holdover.prune_revoked(&owned);
    pacing.ledger.drop_unowned(&owned);

    let watermarks = dispatcher.merge_deps().live_watermarks.clone();
    let watermark_of = |partition: i32| watermarks.get(partition);

    let live_lag = assess_live_lag(
        &owned,
        watermark_of,
        &pacing.ledger,
        pacing_config.live_lag,
        now_ms,
    );
    for (&partition, &age_ms) in &live_lag.ages_ms {
        gauge!(LIVE_WATERMARK_AGE_MS, "partition" => partition.to_string()).set(age_ms as f64);
    }
    gauge!(SEED_NO_WATERMARK_PARTITIONS).set(live_lag.no_watermark as f64);

    // Pod-wide disk verdict; an absent sample can never pause (fail-open).
    pacing.disk_engaged = match (pacing_config.disk, disk_sample) {
        (Some(hysteresis), Some(sample)) => {
            hysteresis.decide(pacing.disk_engaged, UsedPct(sample.used_pct()))
        }
        _ => false,
    };

    let policy = AdmissionPolicy {
        fence_margin_ms,
        watermark_of,
        live_lagging: &live_lag.lagging,
        disk_pressure: pacing.disk_engaged,
    };

    // Held before fresh; the channel-full remainder re-absorbs before the still-fenced
    // suffix so per-partition FIFO holds.
    let refence = split_for_admission(drain_held(holdover), &HashSet::new(), &policy);
    let still_full = dispatcher.dispatch_seeds(refence.admitted);
    let mut bounced: Vec<i32> = still_full.keys().copied().collect();
    holdover.absorb(still_full);
    holdover.absorb(refence.held);

    // Fresh seeds queue behind held partitions rather than leapfrogging older offsets.
    let fresh = split_for_admission(seeds, &holdover.held_partitions(), &policy);
    let fresh_full = dispatcher.dispatch_seeds(fresh.admitted);
    bounced.extend(fresh_full.keys().copied());
    holdover.absorb(fresh_full);
    holdover.absorb(fresh.held);

    for (partition, deficit) in refence.deficits.into_iter().chain(fresh.deficits) {
        if let Some(deficit_ms) = deficit {
            gauge!(SEED_FENCE_DEFICIT_MS, "partition" => partition.to_string())
                .set(deficit_ms as f64);
        }
    }

    let causes = merge_cycle_causes(refence.causes, fresh.causes, bounced);
    // Reconcile owned ∪ caused: owned partitions with no causes drain (episode ends), and a
    // just-revoked partition whose polled seeds were held this cycle still enters the ledger so
    // the target matches the holdover until both prune next cycle.
    let mut to_reconcile = owned;
    to_reconcile.extend(causes.keys().copied());
    for partition in to_reconcile {
        pacing.ledger.reconcile(
            partition,
            causes.get(&partition).copied().unwrap_or_default(),
            now,
        );
    }

    // A partition is paused iff its holdover is non-empty; the ledger is the causes-and-age view
    // of that same set.
    debug_assert_eq!(pacing.ledger.pause_target(), holdover.held_partitions());

    let target = pacing.ledger.pause_target();
    for partition in prev_paused_target.difference(&target) {
        // Zero the per-partition gauges for drained partitions so they clear.
        let label: Arc<str> = Arc::from(partition.to_string());
        gauge!(SEED_FENCE_DEFICIT_MS, "partition" => label.clone()).set(0.0);
        gauge!(SEED_PAUSE_AGE_MS, "partition" => label.clone()).set(0.0);
        gauge!(SEED_OLDEST_HELD_AGE_MS, "partition" => label).set(0.0);
    }
    // A partition can stay held (live-lag/disk/channel-full) after its fence opens; nothing
    // rewrites the deficit then, so clear it rather than pin the last fence-closed reading.
    for &partition in &target {
        if !pacing.ledger.has_cause(partition, PauseCause::Fence) {
            gauge!(SEED_FENCE_DEFICIT_MS, "partition" => partition.to_string()).set(0.0);
        }
    }
    if (!target.is_empty() || !prev_paused_target.is_empty())
        && pause_tx.send(target.clone()).is_err()
    {
        debug!("seed pauser task has exited; skipping a pause/resume update");
    }

    for &partition in &target {
        if let Some(age) = pacing.ledger.age(partition, now) {
            gauge!(SEED_PAUSE_AGE_MS, "partition" => partition.to_string())
                .set(age.as_millis() as f64);
        }
    }
    for (partition, head) in holdover.held_heads() {
        let age_ms = head.broker_ts_ms.map_or(0, |ts| (now_ms - ts).max(0));
        gauge!(SEED_OLDEST_HELD_AGE_MS, "partition" => partition.to_string()).set(age_ms as f64);
    }
    for cause in PauseCause::ALL {
        gauge!(SEED_PAUSED_PARTITIONS, "cause" => cause.as_str())
            .set(pacing.ledger.count_with(cause) as f64);
    }
    gauge!(SEED_FENCED_PARTITIONS).set(holdover.held_partition_count() as f64);

    *prev_paused_target = target;
}

/// The seed-topic follower consume loop. Commits go through the seed tracker +
/// `fsync_then_commit`, so a committed offset is a durably-applied tile.
pub struct SeedFollowerConsumer {
    consumer: Arc<StreamConsumer>,
    topic: String,
    /// The events group's consumer, shared for the idle probe's watermark + boot-committed reads.
    events_consumer: Arc<StreamConsumer<CohortConsumerContext>>,
    events_topic: String,
    dispatcher: Arc<EventDispatcher>,
    handle: Handle,
    pauser: Arc<dyn PartitionPauser>,
    recv_batch_size: usize,
    recv_batch_timeout: Duration,
    offset_commit_interval: Duration,
    fence_margin_ms: i64,
    idle_probe_interval: Duration,
    pacing_config: SeedPacingConfig,
    disk_state: Arc<SharedDiskUtilization>,
}

impl SeedFollowerConsumer {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        consumer: Arc<StreamConsumer>,
        topic: String,
        events_consumer: Arc<StreamConsumer<CohortConsumerContext>>,
        events_topic: String,
        dispatcher: Arc<EventDispatcher>,
        handle: Handle,
        pauser: Arc<dyn PartitionPauser>,
        recv_batch_size: usize,
        recv_batch_timeout: Duration,
        offset_commit_interval: Duration,
        fence_margin_ms: i64,
        idle_probe_interval: Duration,
        pacing_config: SeedPacingConfig,
        disk_state: Arc<SharedDiskUtilization>,
    ) -> Self {
        Self {
            consumer,
            topic,
            events_consumer,
            events_topic,
            dispatcher,
            handle,
            pauser,
            recv_batch_size,
            recv_batch_timeout,
            offset_commit_interval,
            fence_margin_ms,
            idle_probe_interval,
            pacing_config,
            disk_state,
        }
    }

    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!(topic = %self.topic, "seed follower consume loop starting");

        // Pause/resume off-loop: librdkafka's calls are synchronous FFI and must never delay
        // the heartbeat.
        let (pause_tx, pause_rx) = tokio::sync::mpsc::unbounded_channel::<HashSet<i32>>();
        let pauser_task = tokio::spawn(run_pauser_loop(self.pauser.clone(), pause_rx));

        let probe_task = tokio::spawn(run_idle_probe_loop(
            self.events_consumer.clone(),
            self.events_topic.clone(),
            self.dispatcher.clone(),
            self.idle_probe_interval,
            self.handle.clone(),
        ));

        let mut holdover = SeedHoldover::default();
        let mut pacing = SeedPacing::default();
        let mut prev_paused_target: HashSet<i32> = HashSet::new();
        let mut commit_deadline = tokio::time::Instant::now() + self.offset_commit_interval;

        loop {
            tokio::select! {
                biased;
                _ = self.handle.shutdown_recv() => {
                    info!(topic = %self.topic, "shutdown signal received, stopping seed consume loop");
                    break;
                }
                outcome = self.consume_batch() => {
                    self.cycle(outcome, &mut holdover, &mut pacing, &mut prev_paused_target, &pause_tx).await;
                    let now = tokio::time::Instant::now();
                    if now >= commit_deadline {
                        fsync_then_commit(
                            self.dispatcher.handle(),
                            &self.consumer,
                            &self.dispatcher.merge_deps().seed_tracker,
                            self.owned_committable_offsets(),
                            &self.topic,
                            CommitMode::Async,
                        )
                        .await;
                        commit_deadline = now + self.offset_commit_interval;
                    }
                }
            }
        }

        drop(pause_tx);
        if let Err(err) = pauser_task.await {
            warn!(error = %err, "seed pauser task did not exit cleanly");
        }
        if let Err(err) = probe_task.await {
            warn!(error = %err, "seed idle-probe task did not exit cleanly");
        }

        fsync_then_commit(
            self.dispatcher.handle(),
            &self.consumer,
            &self.dispatcher.merge_deps().seed_tracker,
            self.owned_committable_offsets(),
            &self.topic,
            CommitMode::Sync,
        )
        .await;
        info!(topic = %self.topic, "seed follower consume loop stopped");
    }

    /// One non-blocking cycle: prune revoked holdover, assess the pacing gates, re-admit and
    /// redispatch held seeds before fresh ones, dispatch the polled batch, reconcile the paused
    /// target and gauges.
    async fn cycle(
        &self,
        outcome: SeedConsumeOutcome,
        holdover: &mut SeedHoldover,
        pacing: &mut SeedPacing,
        prev_paused_target: &mut HashSet<i32>,
        pause_tx: &tokio::sync::mpsc::UnboundedSender<HashSet<i32>>,
    ) {
        histogram!(COHORT_STREAM_SEEDS_CONSUME_BATCH_SIZE).record(outcome.seeds.len() as f64);
        if !outcome.seeds.is_empty() {
            counter!(COHORT_STREAM_SEEDS_CONSUMED).increment(outcome.seeds.len() as u64);
        }
        if outcome.deserialize_errors > 0 {
            counter!(COHORT_STREAM_SEED_DESERIALIZE_ERRORS).increment(outcome.deserialize_errors);
        }

        run_admission_cycle(
            &self.dispatcher,
            &self.pacing_config,
            self.disk_state.latest(),
            self.fence_margin_ms,
            outcome.seeds,
            holdover,
            pacing,
            prev_paused_target,
            pause_tx,
            chrono::Utc::now().timestamp_millis(),
            Instant::now(),
        );

        if outcome.transport_error {
            tokio::time::sleep(RECV_ERROR_BACKOFF).await;
        } else {
            self.handle.report_healthy();
        }
    }

    async fn consume_batch(&self) -> SeedConsumeOutcome {
        let mut outcome = SeedConsumeOutcome {
            seeds: Vec::with_capacity(self.recv_batch_size),
            deserialize_errors: 0,
            transport_error: false,
        };

        tokio::select! {
            _ = tokio::time::sleep(self.recv_batch_timeout) => {}
            _ = async {
                while outcome.seeds.len() < self.recv_batch_size {
                    match self.consumer.recv().await {
                        Ok(message) => {
                            let partition = message.partition();
                            let offset = message.offset();
                            let work = decode_payload(message.payload(), partition, offset);
                            if matches!(work, SeedWork::Skip(SeedSkipReason::DecodeError)) {
                                outcome.deserialize_errors += 1;
                            }
                            outcome.seeds.push(ConsumedSeed {
                                work,
                                partition,
                                offset,
                                broker_ts_ms: message.timestamp().to_millis(),
                            });
                        }
                        Err(err) => {
                            outcome.transport_error = true;
                            counter!(COHORT_STREAM_KAFKA_RECV_ERRORS).increment(1);
                            warn!(topic = %self.topic, error = %err, "kafka recv error while consuming seed topic");
                            break;
                        }
                    }
                }
            } => {}
        }

        outcome
    }

    fn owned_committable_offsets(&self) -> HashMap<i32, i64> {
        owned_committable_offsets(&self.dispatcher.merge_deps().seed_tracker, &self.dispatcher)
    }
}

/// Decode one payload into channel-riding work so every outcome retains its in-order offset.
fn decode_payload(payload: Option<&[u8]>, partition: i32, offset: i64) -> SeedWork {
    let Some(payload) = payload else {
        debug!(
            partition,
            offset, "skipping seed message with empty payload"
        );
        return SeedWork::Skip(SeedSkipReason::DecodeError);
    };
    match decode_seed(payload) {
        Ok(DecodedSeed::Tile(tile)) => SeedWork::Tile(tile),
        Ok(DecodedSeed::Person(seed)) => SeedWork::Person(seed),
        Ok(DecodedSeed::Reconcile(tile)) => SeedWork::Reconcile(tile),
        Ok(DecodedSeed::UnknownKind { kind, .. }) => {
            debug!(partition, offset, kind, "skipping seed of unknown kind");
            SeedWork::Skip(SeedSkipReason::UnknownKind)
        }
        Ok(DecodedSeed::UnsupportedSchema {
            kind,
            schema_version,
        }) => {
            debug!(
                partition,
                offset, kind, schema_version, "skipping seed at unsupported schema version",
            );
            SeedWork::Skip(SeedSkipReason::UnsupportedSchema)
        }
        Err(err) => {
            debug!(partition, offset, error = %err, "skipping undeserializable seed message");
            SeedWork::Skip(SeedSkipReason::DecodeError)
        }
    }
}

struct SeedConsumeOutcome {
    seeds: Vec<ConsumedSeed>,
    deserialize_errors: u64,
    transport_error: bool,
}

/// Advance idle partitions' watermarks: once everything retained is folded, "now" is a valid
/// arrival bound. Accepted residual: a silent shuffler stall longer than the margin opens the
/// fence early, surfaced via the watermark-age gauge + shuffler-lag alerting.
async fn run_idle_probe_loop(
    events_consumer: Arc<StreamConsumer<CohortConsumerContext>>,
    events_topic: String,
    dispatcher: Arc<EventDispatcher>,
    interval: Duration,
    handle: Handle,
) {
    let mut ticker = tokio::time::interval(interval);
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    // Skip the immediate first tick so the probe never races boot recovery.
    ticker.tick().await;
    loop {
        tokio::select! {
            biased;
            _ = handle.shutdown_recv() => break,
            _ = ticker.tick() => {
                let owned = dispatcher.owned_partitions();
                if owned.is_empty() {
                    continue;
                }
                let folded = dispatcher.events_tracker().committable_offsets();
                let consumer = events_consumer.clone();
                let topic = events_topic.clone();
                let pass_started = Instant::now();
                let probe = tokio::task::spawn_blocking(move || {
                    probe_idle_partitions(consumer.as_ref(), &topic, &owned, &folded)
                });
                // Race against shutdown: the blocking fetch can spend ~5 s per partition against
                // an unresponsive broker.
                let probed = tokio::select! {
                    biased;
                    _ = handle.shutdown_recv() => break,
                    probed = probe => probed,
                };
                match probed {
                    Ok(idle_partitions) => {
                        histogram!(SEED_IDLE_PROBE_DURATION_SECONDS)
                            .record(pass_started.elapsed().as_secs_f64());
                        let now_ms = chrono::Utc::now().timestamp_millis();
                        gauge!(SEED_IDLE_PROBE_LAST_PASS_TIMESTAMP_SECONDS)
                            .set(now_ms as f64 / 1_000.0);
                        advance_probed_idle(
                            &dispatcher.merge_deps().live_watermarks,
                            &dispatcher.owned_set(),
                            idle_partitions,
                            now_ms,
                        );
                    }
                    Err(err) => warn!(error = %err, "seed idle probe task failed"),
                }
            }
        }
    }
}

/// Advance probed-idle watermarks, re-checking ownership at advance time: the probe's snapshot is
/// stale by up to the blocking fetch, and re-creating an entry a mid-probe revoke forgot would
/// open the fence for a later tenure before its replayed events fold. The assign path forgets
/// independently, covering the residual race.
fn advance_probed_idle(
    watermarks: &crate::partitions::watermarks::LiveWatermarks,
    owned_now: &HashSet<i32>,
    idle_partitions: Vec<i32>,
    now_ms: i64,
) {
    for partition in idle_partitions {
        if owned_now.contains(&partition) {
            watermarks.advance_idle(partition, now_ms);
        }
    }
}

/// Blocking half of the idle probe: compare each owned partition's high watermark to the folded
/// frontier, falling back to the events group's committed offset before any fold this tenure.
/// Errors skip the partition (fence stays closed).
fn probe_idle_partitions<C: rdkafka::consumer::ConsumerContext + 'static>(
    consumer: &StreamConsumer<C>,
    topic: &str,
    owned: &[i32],
    folded: &HashMap<i32, i64>,
) -> Vec<i32> {
    let unfolded: Vec<i32> = owned
        .iter()
        .copied()
        .filter(|partition| !folded.contains_key(partition))
        .collect();
    let committed: HashMap<i32, i64> = if unfolded.is_empty() {
        HashMap::new()
    } else {
        let mut tpl = TopicPartitionList::new();
        for &partition in &unfolded {
            tpl.add_partition(topic, partition);
        }
        match consumer.committed_offsets(tpl, PROBE_FETCH_TIMEOUT) {
            Ok(tpl) => tpl
                .elements_for_topic(topic)
                .iter()
                .filter_map(|elem| match elem.offset() {
                    Offset::Offset(next) => Some((elem.partition(), next)),
                    _ => None,
                })
                .collect(),
            Err(err) => {
                warn!(topic, error = %err, "idle probe: committed-offset fetch failed; boot-edge partitions stay fenced");
                HashMap::new()
            }
        }
    };

    let mut idle = Vec::new();
    for &partition in owned {
        let (low, high) = match consumer.fetch_watermarks(topic, partition, PROBE_FETCH_TIMEOUT) {
            Ok(bounds) => bounds,
            Err(err) => {
                debug!(topic, partition, error = %err, "idle probe: watermark fetch failed; partition stays fenced");
                continue;
            }
        };
        let frontier = folded
            .get(&partition)
            .copied()
            .or_else(|| committed.get(&partition).copied());
        if frontier_is_caught_up(frontier, low, high) {
            idle.push(partition);
        }
    }
    idle
}

/// Whether every retained live message is behind the folded frontier (a next-to-consume offset).
/// No frontier is idle only with nothing retained. A wrong `true` opens the fence over unfolded
/// live events.
fn frontier_is_caught_up(frontier: Option<i64>, low: i64, high: i64) -> bool {
    match frontier {
        Some(next) => next >= high,
        None => high == low,
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use cohort_core::seed::{
        BehavioralShapeHash, ClaimEpoch, ConditionHash, PersonSeed, ReconcileTile, RunId, SChunkMs,
        ScannedAtMs,
    };
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamId};
    use crate::partitions::watermarks::LiveWatermarks;

    use super::*;

    const MARGIN_MS: i64 = 600_000;

    fn tile_at(s_chunk_ms: i64) -> SeedTile {
        SeedTile::new(
            TeamId(2),
            Uuid::from_u128(7),
            ConditionHash::parse("0123456789abcdef").unwrap(),
            NonZeroU32::new(1).unwrap(),
            20_614,
            SChunkMs(s_chunk_ms),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn seed(partition: i32, offset: i64, s_chunk_ms: i64) -> ConsumedSeed {
        ConsumedSeed {
            work: SeedWork::Tile(tile_at(s_chunk_ms)),
            partition,
            offset,
            broker_ts_ms: None,
        }
    }

    fn skip(partition: i32, offset: i64) -> ConsumedSeed {
        ConsumedSeed {
            work: SeedWork::Skip(SeedSkipReason::UnknownKind),
            partition,
            offset,
            broker_ts_ms: None,
        }
    }

    fn person_seed() -> PersonSeed {
        PersonSeed::new(
            TeamId(2),
            Uuid::from_u128(7),
            vec![ConditionHash::parse("0123456789abcdef").unwrap()],
            vec![ConditionHash::parse("0123456789abcdef").unwrap()],
            ScannedAtMs(1_700_000_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
        .unwrap()
    }

    fn person(partition: i32, offset: i64) -> ConsumedSeed {
        ConsumedSeed {
            work: SeedWork::Person(person_seed()),
            partition,
            offset,
            broker_ts_ms: None,
        }
    }

    fn offsets(seeds: &[ConsumedSeed]) -> Vec<i64> {
        seeds.iter().map(|seed| seed.offset).collect()
    }

    /// A policy with only the fence gate active: no live-lag set, no disk pressure.
    fn fence_only<F: Fn(i32) -> Option<WatermarkMs>>(
        live_lagging: &HashSet<i32>,
        watermark_of: F,
    ) -> AdmissionPolicy<'_, F> {
        AdmissionPolicy {
            fence_margin_ms: MARGIN_MS,
            watermark_of,
            live_lagging,
            disk_pressure: false,
        }
    }

    fn causes_of(list: &[PauseCause]) -> CauseSet {
        let mut set = CauseSet::default();
        for &cause in list {
            set.insert(cause);
        }
        set
    }

    #[test]
    fn fence_decision_table_pins_the_boundary_arithmetic() {
        let s_chunk = SChunkMs(1_000_000);
        // No watermark at all: fail-closed with an unknown deficit.
        assert_eq!(
            fence_decision(None, s_chunk, MARGIN_MS),
            FenceDecision::Closed { deficit_ms: None },
        );
        // Exactly at the bound is still closed — the watermark must *exceed* s_chunk + margin.
        assert_eq!(
            fence_decision(Some(WatermarkMs(1_000_000 + MARGIN_MS)), s_chunk, MARGIN_MS),
            FenceDecision::Closed {
                deficit_ms: Some(0)
            },
        );
        assert_eq!(
            fence_decision(
                Some(WatermarkMs(1_000_000 + MARGIN_MS + 1)),
                s_chunk,
                MARGIN_MS
            ),
            FenceDecision::Open,
        );
        assert_eq!(
            fence_decision(Some(WatermarkMs(900_000)), s_chunk, MARGIN_MS),
            FenceDecision::Closed {
                deficit_ms: Some(100_000 + MARGIN_MS)
            },
        );
        // A far-future s_chunk must not overflow the bound arithmetic.
        assert_eq!(
            fence_decision(Some(WatermarkMs(i64::MAX)), SChunkMs(i64::MAX), MARGIN_MS),
            FenceDecision::Closed {
                deficit_ms: Some(0)
            },
        );
    }

    #[test]
    fn split_admits_the_open_prefix_and_holds_everything_from_the_first_closed_tile() {
        let watermarks = LiveWatermarks::new();
        // Partition 1's watermark clears s_chunk 100 but not 10_000_000.
        watermarks.observe(1, 100 + MARGIN_MS + 1);
        let batch = vec![
            seed(1, 10, 100),        // open
            skip(1, 11),             // skip in the open prefix: admitted
            seed(1, 12, 10_000_000), // closed → holds from here
            skip(1, 13),             // skip AFTER the closed tile: held, FIFO preserved
            seed(1, 14, 100),        // would be open, but queues behind the held offset
        ];

        let none = HashSet::new();
        let split = split_for_admission(
            batch,
            &HashSet::new(),
            &fence_only(&none, |p| watermarks.get(p)),
        );

        assert_eq!(offsets(&split.admitted), vec![10, 11]);
        assert_eq!(offsets(&split.held[&1]), vec![12, 13, 14]);
        assert_eq!(
            split.deficits[&1],
            Some(10_000_000 + MARGIN_MS - (100 + MARGIN_MS + 1))
        );
        assert_eq!(split.causes[&1], causes_of(&[PauseCause::Fence]));
    }

    #[test]
    fn split_holds_everything_for_an_absent_watermark_except_leading_skips() {
        let batch = vec![skip(3, 1), seed(3, 2, 0), skip(3, 3)];

        let none = HashSet::new();
        let split = split_for_admission(batch, &HashSet::new(), &fence_only(&none, |_| None));

        assert_eq!(
            offsets(&split.admitted),
            vec![1],
            "a leading skip is always admitted; it cannot double-count anything",
        );
        assert_eq!(offsets(&split.held[&3]), vec![2, 3]);
        assert_eq!(split.deficits[&3], None, "no watermark → unknown deficit");
    }

    #[test]
    fn split_queues_an_already_held_partition_entirely_behind_its_holdover() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(5, i64::MAX); // fence wide open
        let batch = vec![seed(5, 20, 0), skip(5, 21)];

        let none = HashSet::new();
        let split = split_for_admission(
            batch,
            &HashSet::from([5]),
            &fence_only(&none, |p| watermarks.get(p)),
        );

        assert!(split.admitted.is_empty(), "nothing leapfrogs a held offset");
        assert_eq!(offsets(&split.held[&5]), vec![20, 21]);
    }

    #[test]
    fn split_isolates_partitions_from_each_other() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(1, i64::MAX);
        // Partition 2 has no watermark: closed.
        let batch = vec![seed(1, 1, 0), seed(2, 1, 0), seed(1, 2, 0)];

        let none = HashSet::new();
        let split = split_for_admission(
            batch,
            &HashSet::new(),
            &fence_only(&none, |p| watermarks.get(p)),
        );

        assert_eq!(offsets(&split.admitted), vec![1, 2]);
        assert!(split.admitted.iter().all(|seed| seed.partition == 1));
        assert_eq!(offsets(&split.held[&2]), vec![1]);
    }

    /// Live-priority violated by leaking fence-open tiles: a lagging partition must hold its
    /// whole batch — leading skips included — while other partitions stay unaffected.
    #[test]
    fn live_lag_gate_holds_everything_including_leading_skips() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(3, i64::MAX); // fence wide open — the gate must hold regardless
        watermarks.observe(4, i64::MAX);
        let batch = vec![skip(3, 1), seed(3, 2, 0), skip(3, 3), seed(4, 7, 0)];

        let lagging = HashSet::from([3]);
        let split = split_for_admission(
            batch,
            &HashSet::new(),
            &fence_only(&lagging, |p| watermarks.get(p)),
        );

        assert_eq!(
            offsets(&split.admitted),
            vec![7],
            "only the un-gated partition flows"
        );
        assert_eq!(offsets(&split.held[&3]), vec![1, 2, 3]);
        assert_eq!(split.causes[&3], causes_of(&[PauseCause::LiveLag]));
        assert!(
            !split.deficits.contains_key(&3),
            "an open fence adds neither a fence cause nor a deficit while gated",
        );
    }

    /// The pod-wide disk gate must hold every partition, fence state notwithstanding.
    #[test]
    fn disk_gate_holds_all_partitions() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(1, i64::MAX);
        watermarks.observe(2, i64::MAX);
        let batch = vec![seed(1, 10, 0), skip(1, 11), seed(2, 20, 0)];

        let none = HashSet::new();
        let policy = AdmissionPolicy {
            disk_pressure: true,
            ..fence_only(&none, |p| watermarks.get(p))
        };
        let split = split_for_admission(batch, &HashSet::new(), &policy);

        assert!(split.admitted.is_empty());
        assert_eq!(offsets(&split.held[&1]), vec![10, 11]);
        assert_eq!(offsets(&split.held[&2]), vec![20]);
        assert_eq!(split.causes[&1], causes_of(&[PauseCause::DiskPressure]));
        assert_eq!(split.causes[&2], causes_of(&[PauseCause::DiskPressure]));
    }

    /// The fence gauges must stay continuous through a live-lag/disk episode: a gated partition
    /// still probes its first tile's fence and attributes the cause + deficit.
    #[test]
    fn gated_partition_still_attributes_fence_and_deficit() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(1, 100 + MARGIN_MS + 1); // clears s_chunk 100, not 10_000_000
        let batch = vec![skip(1, 9), seed(1, 10, 10_000_000), seed(1, 11, 100)];

        let lagging = HashSet::from([1]);
        let split = split_for_admission(
            batch,
            &HashSet::new(),
            &fence_only(&lagging, |p| watermarks.get(p)),
        );

        assert!(split.admitted.is_empty());
        assert_eq!(offsets(&split.held[&1]), vec![9, 10, 11]);
        assert_eq!(
            split.causes[&1],
            causes_of(&[PauseCause::LiveLag, PauseCause::Fence]),
        );
        assert_eq!(
            split.deficits[&1],
            Some(10_000_000 + MARGIN_MS - (100 + MARGIN_MS + 1)),
            "the first tile's deficit is attributed even while gated",
        );
    }

    /// An absent watermark is fence-fail-closed already; a redundant live-lag hold would poison
    /// the hysteresis memory on a new tenure. It must be counted, never gated.
    #[test]
    fn absent_watermark_counts_no_watermark_but_never_live_lags() {
        let watermarks = LiveWatermarks::new();
        let now_ms = 1_000_000;
        watermarks.observe(1, now_ms - 500_000); // deep lag: gated
                                                 // Partition 2 has no watermark at all.
        let owned = HashSet::from([1, 2]);
        let hysteresis = Hysteresis::new(AgeMs(120_000), AgeMs(60_000)).unwrap();

        let assessment = assess_live_lag(
            &owned,
            |p| watermarks.get(p),
            &PauseLedger::default(),
            Some(hysteresis),
            now_ms,
        );

        assert_eq!(assessment.lagging, HashSet::from([1]));
        assert_eq!(assessment.no_watermark, 1);
        assert_eq!(assessment.ages_ms, HashMap::from([(1, 500_000)]));
    }

    /// The release threshold must apply only to partitions the ledger remembers as live-lagging;
    /// an age between the thresholds engages nothing new.
    #[test]
    fn live_lag_hysteresis_uses_ledger_memory() {
        let watermarks = LiveWatermarks::new();
        let now_ms = 1_000_000;
        // Both partitions sit between release (60s) and engage (120s).
        watermarks.observe(1, now_ms - 90_000);
        watermarks.observe(2, now_ms - 90_000);
        let owned = HashSet::from([1, 2]);
        let hysteresis = Hysteresis::new(AgeMs(120_000), AgeMs(60_000)).unwrap();

        let mut ledger = PauseLedger::default();
        ledger.reconcile(1, causes_of(&[PauseCause::LiveLag]), Instant::now());

        let assessment = assess_live_lag(
            &owned,
            |p| watermarks.get(p),
            &ledger,
            Some(hysteresis),
            now_ms,
        );

        assert_eq!(
            assessment.lagging,
            HashSet::from([1]),
            "only the remembered partition stays engaged between the thresholds",
        );
    }

    /// A partition whose ledger causes cleared but whose dispatch bounced must re-enter the
    /// causes map as channel-full, or the ledger would resume a partition that still holds work.
    #[test]
    fn merge_cycle_causes_adds_channel_full_for_bounced_partitions() {
        let refence = HashMap::from([(1, causes_of(&[PauseCause::Fence]))]);
        let fresh = HashMap::from([
            (1, causes_of(&[PauseCause::LiveLag])),
            (2, causes_of(&[PauseCause::DiskPressure])),
        ]);

        let merged = merge_cycle_causes(refence, fresh, [1, 3]);

        assert_eq!(
            merged[&1],
            causes_of(&[
                PauseCause::Fence,
                PauseCause::LiveLag,
                PauseCause::ChannelFull
            ]),
        );
        assert_eq!(merged[&2], causes_of(&[PauseCause::DiskPressure]));
        assert_eq!(merged[&3], causes_of(&[PauseCause::ChannelFull]));
    }

    #[test]
    fn holdover_absorb_take_preserves_per_partition_fifo_and_prunes_revoked() {
        let mut holdover = SeedHoldover::default();
        holdover.absorb(HashMap::from([(1, vec![seed(1, 10, 0), seed(1, 11, 0)])]));
        holdover.absorb(HashMap::from([
            (1, vec![seed(1, 12, 0)]),
            (2, vec![seed(2, 5, 0)]),
        ]));

        assert_eq!(holdover.held_partitions(), HashSet::from([1, 2]));
        assert_eq!(holdover.held_partition_count(), 2);

        holdover.prune_revoked(&HashSet::from([1]));
        assert_eq!(holdover.held_partitions(), HashSet::from([1]));

        let taken = drain_held(&mut holdover);
        assert_eq!(
            offsets(&taken),
            vec![10, 11, 12],
            "FIFO within the partition"
        );
        assert!(holdover.held_partitions().is_empty());
    }

    #[test]
    fn decode_payload_classifies_tiles_skips_and_garbage() {
        let tile = tile_at(1_700_000_000_000);
        let bytes = serde_json::to_vec(&tile).unwrap();
        assert!(matches!(
            decode_payload(Some(&bytes), 0, 0),
            SeedWork::Tile(decoded) if decoded == tile,
        ));

        let reconcile = ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            BehavioralShapeHash::parse(
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            )
            .unwrap(),
            RunId(Uuid::nil()),
        );
        let bytes = serde_json::to_vec(&reconcile).unwrap();
        assert!(matches!(
            decode_payload(Some(&bytes), 0, 0),
            SeedWork::Reconcile(decoded) if decoded == reconcile,
        ));

        // An undecodable person seed would skip-and-commit and never replay, so the decode arm has
        // to land before any seeder emits the kind.
        let person = person_seed();
        let bytes = serde_json::to_vec(&person).unwrap();
        assert!(matches!(
            decode_payload(Some(&bytes), 0, 0),
            SeedWork::Person(decoded) if decoded == person,
        ));

        let mut newer = serde_json::to_value(&tile).unwrap();
        newer["schema_version"] = serde_json::json!(2);
        let bytes = serde_json::to_vec(&newer).unwrap();
        assert!(matches!(
            decode_payload(Some(&bytes), 0, 0),
            SeedWork::Skip(SeedSkipReason::UnsupportedSchema),
        ));

        assert!(matches!(
            decode_payload(Some(b"not json"), 0, 0),
            SeedWork::Skip(SeedSkipReason::DecodeError),
        ));
        assert!(matches!(
            decode_payload(None, 0, 0),
            SeedWork::Skip(SeedSkipReason::DecodeError),
        ));
    }

    /// A channel-full bounce round-trips through the shuffle message; losing `broker_ts_ms` there
    /// would zero the oldest-held age gauge exactly when the partition is stuck.
    #[test]
    fn consumed_seed_round_trips_through_its_shuffle_message() {
        let consumed = ConsumedSeed {
            broker_ts_ms: Some(1_700_000_000_000),
            ..seed(9, 42, 123)
        };
        let message = consumed.into_message();
        assert_eq!(message.seed_offset(), Some(42));
        let back = ConsumedSeed::from_message(9, message).unwrap();
        assert_eq!(back.partition, 9);
        assert_eq!(back.offset, 42);
        assert_eq!(back.broker_ts_ms, Some(1_700_000_000_000));
        assert!(matches!(back.work, SeedWork::Tile(tile) if tile.s_chunk_ms() == SChunkMs(123)));

        let reconcile = ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            BehavioralShapeHash::parse("0123456789abcdef").unwrap(),
            RunId(Uuid::nil()),
        );
        let consumed = ConsumedSeed {
            work: SeedWork::Reconcile(reconcile.clone()),
            partition: 9,
            offset: 43,
            broker_ts_ms: None,
        };
        let back = ConsumedSeed::from_message(9, consumed.into_message()).unwrap();
        assert_eq!(back.offset, 43);
        assert_eq!(back.broker_ts_ms, None);
        assert!(matches!(back.work, SeedWork::Reconcile(tile) if tile == reconcile));

        let not_seed = ShuffleMessage::RedrivePendingTransfers;
        assert!(ConsumedSeed::from_message(9, not_seed).is_none());
    }

    #[test]
    fn reconcile_is_fence_open_but_never_leapfrogs_a_closed_tile() {
        let reconcile = ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            BehavioralShapeHash::parse("0123456789abcdef").unwrap(),
            RunId(Uuid::nil()),
        );
        let reconcile_seed = |offset| ConsumedSeed {
            work: SeedWork::Reconcile(reconcile.clone()),
            partition: 3,
            offset,
            broker_ts_ms: None,
        };

        let none = HashSet::new();
        let open_prefix = split_for_admission(
            vec![reconcile_seed(1), seed(3, 2, 0)],
            &HashSet::new(),
            &fence_only(&none, |_| None),
        );
        assert_eq!(offsets(&open_prefix.admitted), vec![1]);
        assert_eq!(offsets(&open_prefix.held[&3]), vec![2]);

        let closed_prefix = split_for_admission(
            vec![seed(3, 3, 0), reconcile_seed(4)],
            &HashSet::new(),
            &fence_only(&none, |_| None),
        );
        assert!(closed_prefix.admitted.is_empty());
        assert_eq!(offsets(&closed_prefix.held[&3]), vec![3, 4]);
    }

    #[test]
    fn person_seeds_are_fence_open_but_never_leapfrog_a_held_partition() {
        let none = HashSet::new();
        let open_prefix = split_for_admission(
            vec![person(3, 1), seed(3, 2, 0)],
            &HashSet::new(),
            &fence_only(&none, |_| None),
        );
        assert_eq!(offsets(&open_prefix.admitted), vec![1]);
        assert_eq!(offsets(&open_prefix.held[&3]), vec![2]);

        let closed_prefix = split_for_admission(
            vec![seed(3, 3, 0), person(3, 4)],
            &HashSet::new(),
            &fence_only(&none, |_| None),
        );
        assert!(closed_prefix.admitted.is_empty());
        assert_eq!(offsets(&closed_prefix.held[&3]), vec![3, 4]);

        let watermarks = LiveWatermarks::new();
        watermarks.observe(3, i64::MAX); // fence wide open — live-priority must hold regardless
        let lagging = HashSet::from([3]);
        let gated = split_for_admission(
            vec![person(3, 5), person(3, 6)],
            &HashSet::new(),
            &fence_only(&lagging, |p| watermarks.get(p)),
        );
        assert!(gated.admitted.is_empty());
        assert_eq!(offsets(&gated.held[&3]), vec![5, 6]);
        assert_eq!(gated.causes[&3], causes_of(&[PauseCause::LiveLag]));
    }

    /// A wrong `true` declares a partition with unfolded live events idle — the fence's
    /// fail-open direction.
    #[test]
    fn frontier_is_caught_up_table() {
        let cases = [
            (
                Some(10),
                0,
                10,
                true,
                "folded frontier at the high watermark",
            ),
            (Some(9), 0, 10, false, "one retained message unfolded"),
            (
                Some(11),
                0,
                10,
                true,
                "frontier past the watermark (post-truncation)",
            ),
            (Some(0), 0, 0, true, "empty partition with a zero frontier"),
            (
                None,
                5,
                5,
                true,
                "boot edge: nothing retained, nothing committed",
            ),
            (None, 0, 0, true, "boot edge: never-produced partition"),
            (
                None,
                4,
                10,
                false,
                "no frontier with retained messages stays fenced",
            ),
        ];
        for (frontier, low, high, expected, why) in cases {
            assert_eq!(
                frontier_is_caught_up(frontier, low, high),
                expected,
                "{why}"
            );
        }
    }

    /// A revoke mid-probe forgot the watermark; the advance-time re-check must not re-create it.
    #[test]
    fn probe_advance_never_recreates_a_watermark_revoked_mid_probe() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(5, 1_000);
        watermarks.observe(6, 1_000);

        // Mid-probe: partition 5 is revoked and forgotten; the probe's stale snapshot still
        // reports both partitions idle.
        watermarks.forget_partition(5);
        let owned_now = HashSet::from([6]);
        advance_probed_idle(&watermarks, &owned_now, vec![5, 6], 2_000);

        assert_eq!(
            watermarks.get(5),
            None,
            "the revoked partition stays fail-closed",
        );
        assert_eq!(
            watermarks.get(6),
            Some(WatermarkMs(2_000)),
            "the still-owned partition advances",
        );
    }

    mod admission_cycle {
        //! Behavioral checks of [`run_admission_cycle`] against a real dispatcher and store;
        //! the pause channel and the seed tracker's ceiling are the observables.

        use tempfile::TempDir;

        use crate::observability::disk::DiskUtilization;
        use crate::partitions::{OffsetTracker, PartitionRouter};
        use crate::producer::CaptureSink;
        use crate::store::{CohortStore, OffloadConfig, OffloadMode, StoreConfig, StoreHandle};
        use crate::workers::MergeWorkerDeps;

        use super::*;

        fn pacing_dispatcher(dir: &TempDir) -> Arc<EventDispatcher> {
            let store = CohortStore::open(&StoreConfig {
                path: dir.path().join("db"),
                ..StoreConfig::default()
            })
            .expect("open store");
            let handle = StoreHandle::new(
                store,
                OffloadConfig {
                    mode: OffloadMode::All,
                    event_read_permits: 16,
                    maintenance_permits: 6,
                },
            );
            Arc::new(EventDispatcher::new(
                PartitionRouter::new(64),
                Arc::new(OffsetTracker::new()),
                handle,
                Arc::new(crate::filters::CatalogHandle::new()),
                Arc::new(CaptureSink::new()),
                MergeWorkerDeps::capture(),
            ))
        }

        /// The spawned worker marks a dispatched skip processed; a held skip never advances.
        async fn wait_for_committable(dispatcher: &EventDispatcher, partition: i32, expected: i64) {
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                let committable = dispatcher
                    .merge_deps()
                    .seed_tracker
                    .committable_offsets()
                    .get(&partition)
                    .copied();
                if committable == Some(expected) {
                    return;
                }
                assert!(
                    Instant::now() < deadline,
                    "timed out waiting for partition {partition} committable {expected}, at {committable:?}",
                );
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }

        /// A lagging live watermark holds the polled seeds and pauses the partition within one
        /// cycle; recovery past the release threshold redispatches the held offset before the
        /// fresh one.
        #[tokio::test]
        async fn live_lag_pauses_within_a_cycle_and_resumes_held_before_fresh() {
            let dir = TempDir::new().unwrap();
            let dispatcher = pacing_dispatcher(&dir);
            dispatcher.assign_partition(0);
            let watermarks = dispatcher.merge_deps().live_watermarks.clone();

            let pacing_config = SeedPacingConfig {
                live_lag: Some(Hysteresis::new(AgeMs(120_000), AgeMs(60_000)).unwrap()),
                disk: None,
            };
            let mut holdover = SeedHoldover::default();
            let mut pacing = SeedPacing::default();
            let mut prev = HashSet::new();
            let (pause_tx, mut pause_rx) = tokio::sync::mpsc::unbounded_channel();

            let now_ms = chrono::Utc::now().timestamp_millis();
            watermarks.observe(0, now_ms - 300_000);
            run_admission_cycle(
                &dispatcher,
                &pacing_config,
                None,
                MARGIN_MS,
                vec![skip(0, 5)],
                &mut holdover,
                &mut pacing,
                &mut prev,
                &pause_tx,
                now_ms,
                Instant::now(),
            );
            assert_eq!(holdover.held_partitions(), HashSet::from([0]));
            assert_eq!(pause_rx.try_recv().unwrap(), HashSet::from([0]));
            assert!(
                dispatcher
                    .merge_deps()
                    .seed_tracker
                    .committable_offsets()
                    .is_empty(),
                "a gated skip never dispatches, so its offset cannot commit",
            );

            let now_ms = chrono::Utc::now().timestamp_millis();
            watermarks.observe(0, now_ms);
            run_admission_cycle(
                &dispatcher,
                &pacing_config,
                None,
                MARGIN_MS,
                vec![skip(0, 6)],
                &mut holdover,
                &mut pacing,
                &mut prev,
                &pause_tx,
                now_ms,
                Instant::now(),
            );
            assert!(holdover.held_partitions().is_empty());
            assert_eq!(pause_rx.try_recv().unwrap(), HashSet::new());
            // Committable 7 requires both offsets marked: held 5 redispatched before fresh 6.
            wait_for_committable(&dispatcher, 0, 7).await;
        }

        /// A sample at or above the pause threshold holds every partition, a between-thresholds
        /// sample stays engaged (hysteresis), and an absent sample releases — a broken probe
        /// must never wedge seeding.
        #[tokio::test]
        async fn disk_pressure_pauses_all_partitions_and_an_absent_sample_never_pauses() {
            let dir = TempDir::new().unwrap();
            let dispatcher = pacing_dispatcher(&dir);
            dispatcher.assign_partition(1);
            dispatcher.assign_partition(2);
            let watermarks = dispatcher.merge_deps().live_watermarks.clone();
            let now_ms = chrono::Utc::now().timestamp_millis();
            watermarks.observe(1, now_ms);
            watermarks.observe(2, now_ms);

            let pacing_config = SeedPacingConfig {
                live_lag: None,
                disk: Some(Hysteresis::new(UsedPct(60.0), UsedPct(55.0)).unwrap()),
            };
            let mut holdover = SeedHoldover::default();
            let mut pacing = SeedPacing::default();
            let mut prev = HashSet::new();
            let (pause_tx, mut pause_rx) = tokio::sync::mpsc::unbounded_channel();

            let over = DiskUtilization {
                total_bytes: 100,
                available_bytes: 30, // 70% used
            };
            run_admission_cycle(
                &dispatcher,
                &pacing_config,
                Some(over),
                MARGIN_MS,
                vec![skip(1, 0), skip(2, 0)],
                &mut holdover,
                &mut pacing,
                &mut prev,
                &pause_tx,
                now_ms,
                Instant::now(),
            );
            assert!(pacing.disk_engaged);
            assert_eq!(holdover.held_partitions(), HashSet::from([1, 2]));
            assert_eq!(pause_rx.try_recv().unwrap(), HashSet::from([1, 2]));

            // Between the thresholds: sticky, still held.
            let between = DiskUtilization {
                total_bytes: 100,
                available_bytes: 43, // 57% used
            };
            run_admission_cycle(
                &dispatcher,
                &pacing_config,
                Some(between),
                MARGIN_MS,
                vec![],
                &mut holdover,
                &mut pacing,
                &mut prev,
                &pause_tx,
                now_ms,
                Instant::now(),
            );
            assert!(
                pacing.disk_engaged,
                "57% is above the 55% release threshold"
            );
            assert_eq!(holdover.held_partitions(), HashSet::from([1, 2]));
            assert_eq!(pause_rx.try_recv().unwrap(), HashSet::from([1, 2]));

            // The probe breaks: fail-open, everything drains.
            run_admission_cycle(
                &dispatcher,
                &pacing_config,
                None,
                MARGIN_MS,
                vec![],
                &mut holdover,
                &mut pacing,
                &mut prev,
                &pause_tx,
                now_ms,
                Instant::now(),
            );
            assert!(!pacing.disk_engaged);
            assert!(holdover.held_partitions().is_empty());
            assert_eq!(pause_rx.try_recv().unwrap(), HashSet::new());
            wait_for_committable(&dispatcher, 1, 1).await;
            wait_for_committable(&dispatcher, 2, 1).await;
        }
    }
}
