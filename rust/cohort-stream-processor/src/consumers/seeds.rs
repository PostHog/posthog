//! The `cohort_stream_seed_events` follower consumer — the backfill day-tile input.
//!
//! Assignment arrives via the events group's rebalance mirror. The apply fence is enforced at
//! admission: a tile dispatches only once its partition's live watermark clears
//! `s_chunk + margin`; fence-closed and channel-full tiles share one holdover + pause mechanism,
//! and an un-dispatched tile was never `mark_dispatched`ed, so its offset cannot commit.
//! Consume-side skips ride the worker channel so their offsets mark in order; they never close
//! the fence.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use cohort_core::seed::{decode_seed, DecodedSeed, SChunkMs, SeedTile};
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use tracing::{debug, info, warn};

use crate::consumers::events::{fsync_then_commit, run_pauser_loop, EventDispatcher};
use crate::consumers::merges::owned_committable_offsets;
use crate::observability::metrics::{
    COHORT_STREAM_KAFKA_RECV_ERRORS, COHORT_STREAM_SEEDS_CONSUMED,
    COHORT_STREAM_SEEDS_CONSUME_BATCH_SIZE, COHORT_STREAM_SEED_DESERIALIZE_ERRORS,
    LIVE_WATERMARK_AGE_MS, SEED_FENCED_PARTITIONS, SEED_FENCE_DEFICIT_MS,
};
use crate::partitions::backpressure::PartitionHoldover;
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
    /// A kind this consumer does not handle (e.g. a `reconcile` control tile).
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
    Skip(SeedSkipReason),
}

/// One message consumed from `cohort_stream_seed_events`, paired with its commit coordinates.
#[derive(Debug)]
pub struct ConsumedSeed {
    pub work: SeedWork,
    pub partition: i32,
    pub offset: i64,
}

impl ConsumedSeed {
    pub(crate) fn into_message(self) -> ShuffleMessage {
        ShuffleMessage::Seed {
            work: Box::new(self.work),
            offset: self.offset,
        }
    }

    /// Inverse of [`into_message`](Self::into_message); `None` for a non-seed message.
    pub(crate) fn from_message(partition: i32, message: ShuffleMessage) -> Option<Self> {
        match message {
            ShuffleMessage::Seed { work, offset } => Some(Self {
                work: *work,
                partition,
                offset,
            }),
            _ => None,
        }
    }

    /// The fence input; `None` for skips.
    fn s_chunk_ms(&self) -> Option<SChunkMs> {
        match &self.work {
            SeedWork::Tile(tile) => Some(tile.s_chunk_ms()),
            SeedWork::Skip(_) => None,
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

/// A consumed batch split at the fence, preserving per-partition FIFO.
#[derive(Debug, Default)]
pub(crate) struct FenceSplit {
    pub admitted: Vec<ConsumedSeed>,
    pub held: HashMap<i32, Vec<ConsumedSeed>>,
    /// Deficit per partition whose fence closed in this split.
    pub deficits: HashMap<i32, Option<i64>>,
}

/// Admit each partition's open prefix; from the first fence-closed tile hold everything for that
/// partition (skips included) so nothing leapfrogs a held offset. `already_held` partitions queue
/// entirely behind their holdover.
pub(crate) fn split_at_fence(
    seeds: Vec<ConsumedSeed>,
    already_held: &HashSet<i32>,
    margin_ms: i64,
    watermark_of: impl Fn(i32) -> Option<WatermarkMs>,
) -> FenceSplit {
    let mut split = FenceSplit::default();
    let mut closed: HashSet<i32> = HashSet::new();
    for seed in seeds {
        let partition = seed.partition;
        if already_held.contains(&partition) || closed.contains(&partition) {
            split.held.entry(partition).or_default().push(seed);
            continue;
        }
        let decision = match seed.s_chunk_ms() {
            None => FenceDecision::Open,
            Some(s_chunk) => fence_decision(watermark_of(partition), s_chunk, margin_ms),
        };
        match decision {
            FenceDecision::Open => split.admitted.push(seed),
            FenceDecision::Closed { deficit_ms } => {
                closed.insert(partition);
                split.deficits.insert(partition, deficit_ms);
                split.held.entry(partition).or_default().push(seed);
            }
        }
    }
    split
}

/// Holdover of fence-closed or backpressured seeds.
type SeedHoldover = PartitionHoldover<ConsumedSeed>;

/// The holdover flattened in per-partition FIFO order.
fn drain_held(holdover: &mut SeedHoldover) -> Vec<ConsumedSeed> {
    holdover
        .take_held()
        .into_iter()
        .flat_map(|(_, seeds)| seeds)
        .collect()
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
                    self.cycle(outcome, &mut holdover, &mut prev_paused_target, &pause_tx).await;
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

    /// One non-blocking cycle: prune revoked holdover, re-fence and redispatch held seeds before
    /// fresh ones, dispatch the polled batch, reconcile the paused target and gauges.
    async fn cycle(
        &self,
        outcome: SeedConsumeOutcome,
        holdover: &mut SeedHoldover,
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

        let owned = self.dispatcher.owned_set();
        holdover.prune_revoked(&owned);
        let watermarks = self.dispatcher.merge_deps().live_watermarks.clone();
        let watermark_of = |partition: i32| watermarks.get(partition);

        // Held before fresh; the channel-full remainder re-absorbs before the still-fenced
        // suffix so per-partition FIFO holds.
        let refence = split_at_fence(
            drain_held(holdover),
            &HashSet::new(),
            self.fence_margin_ms,
            watermark_of,
        );
        let still_full = self.dispatcher.dispatch_seeds(refence.admitted);
        holdover.absorb(still_full);
        holdover.absorb(refence.held);

        // Fresh seeds queue behind held partitions rather than leapfrogging older offsets.
        let fresh = split_at_fence(
            outcome.seeds,
            &holdover.held_partitions(),
            self.fence_margin_ms,
            watermark_of,
        );
        let fresh_full = self.dispatcher.dispatch_seeds(fresh.admitted);
        holdover.absorb(fresh_full);
        holdover.absorb(fresh.held);

        for (partition, deficit) in refence.deficits.into_iter().chain(fresh.deficits) {
            if let Some(deficit_ms) = deficit {
                gauge!(SEED_FENCE_DEFICIT_MS, "partition" => partition.to_string())
                    .set(deficit_ms as f64);
            }
        }
        let now_ms = chrono::Utc::now().timestamp_millis();
        for &partition in &owned {
            if let Some(WatermarkMs(watermark_ms)) = watermarks.get(partition) {
                gauge!(LIVE_WATERMARK_AGE_MS, "partition" => partition.to_string())
                    .set(now_ms.saturating_sub(watermark_ms) as f64);
            }
        }

        let target = holdover.held_partitions();
        if !target.is_empty() || !prev_paused_target.is_empty() {
            for partition in prev_paused_target.difference(&target) {
                // Zero the deficit for drained partitions so the gauge clears.
                gauge!(SEED_FENCE_DEFICIT_MS, "partition" => partition.to_string()).set(0.0);
            }
            if pause_tx.send(target.clone()).is_err() {
                debug!("seed pauser task has exited; skipping a pause/resume update");
            }
            *prev_paused_target = target;
        }
        gauge!(SEED_FENCED_PARTITIONS).set(holdover.held_partition_count() as f64);

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
                            outcome.seeds.push(ConsumedSeed { work, partition, offset });
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

/// Decode one payload; every non-tile outcome is a channel-riding skip so its offset marks in
/// order.
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
                        let now_ms = chrono::Utc::now().timestamp_millis();
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

    use cohort_core::seed::{ClaimEpoch, ConditionHash, RunId, SChunkMs};
    use uuid::Uuid;

    use crate::filters::TeamId;
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
        }
    }

    fn skip(partition: i32, offset: i64) -> ConsumedSeed {
        ConsumedSeed {
            work: SeedWork::Skip(SeedSkipReason::UnknownKind),
            partition,
            offset,
        }
    }

    fn offsets(seeds: &[ConsumedSeed]) -> Vec<i64> {
        seeds.iter().map(|seed| seed.offset).collect()
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

        let split = split_at_fence(batch, &HashSet::new(), MARGIN_MS, |p| watermarks.get(p));

        assert_eq!(offsets(&split.admitted), vec![10, 11]);
        assert_eq!(offsets(&split.held[&1]), vec![12, 13, 14]);
        assert_eq!(
            split.deficits[&1],
            Some(10_000_000 + MARGIN_MS - (100 + MARGIN_MS + 1))
        );
    }

    #[test]
    fn split_holds_everything_for_an_absent_watermark_except_leading_skips() {
        let batch = vec![skip(3, 1), seed(3, 2, 0), skip(3, 3)];

        let split = split_at_fence(batch, &HashSet::new(), MARGIN_MS, |_| None);

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

        let split = split_at_fence(batch, &HashSet::from([5]), MARGIN_MS, |p| watermarks.get(p));

        assert!(split.admitted.is_empty(), "nothing leapfrogs a held offset");
        assert_eq!(offsets(&split.held[&5]), vec![20, 21]);
    }

    #[test]
    fn split_isolates_partitions_from_each_other() {
        let watermarks = LiveWatermarks::new();
        watermarks.observe(1, i64::MAX);
        // Partition 2 has no watermark: closed.
        let batch = vec![seed(1, 1, 0), seed(2, 1, 0), seed(1, 2, 0)];

        let split = split_at_fence(batch, &HashSet::new(), MARGIN_MS, |p| watermarks.get(p));

        assert_eq!(offsets(&split.admitted), vec![1, 2]);
        assert!(split.admitted.iter().all(|seed| seed.partition == 1));
        assert_eq!(offsets(&split.held[&2]), vec![1]);
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

        let mut reconcile = serde_json::to_value(&tile).unwrap();
        reconcile["kind"] = serde_json::json!("reconcile");
        let bytes = serde_json::to_vec(&reconcile).unwrap();
        assert!(matches!(
            decode_payload(Some(&bytes), 0, 0),
            SeedWork::Skip(SeedSkipReason::UnknownKind),
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

    #[test]
    fn consumed_seed_round_trips_through_its_shuffle_message() {
        let consumed = seed(9, 42, 123);
        let message = consumed.into_message();
        assert_eq!(message.seed_offset(), Some(42));
        let back = ConsumedSeed::from_message(9, message).unwrap();
        assert_eq!(back.partition, 9);
        assert_eq!(back.offset, 42);
        assert!(matches!(back.work, SeedWork::Tile(tile) if tile.s_chunk_ms() == SChunkMs(123)));

        let not_seed = ShuffleMessage::RedrivePendingTransfers;
        assert!(ConsumedSeed::from_message(9, not_seed).is_none());
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
}
