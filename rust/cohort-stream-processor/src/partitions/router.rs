//! Partition-affined routing. Maps a `cohort_stream_events` partition to its owning worker's two
//! bounded lanes and dispatches per-partition sub-batches, so every state mutation for a given
//! `(team_id, person_id)` serializes through exactly one worker.
//!
//! Live messages and backfill seeds ride separate lanes with separate budgets, so an admitted seed
//! backlog can never queue in front of a live sub-batch. One worker task drains both, live first.
//!
//! A slow partition cannot stall the rest: the `DashMap` guard is cloned (dropped) before any
//! `.await`, and per-partition sends fan out concurrently via `join_all`.

use std::collections::HashMap;
use std::num::NonZeroUsize;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use futures::future::join_all;
use metrics::{counter, gauge};
use thiserror::Error;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::TrySendError;
use tracing::warn;

use super::intake::{count_intake, Admission, MeteredReceiver, PartitionIntake};
use super::shuffle_message::ShuffleMessage;
use crate::consumers::seeds::ConsumedSeed;
use crate::observability::metrics::{
    PARTITIONS_ACTIVE, PARTITION_CHANNEL_DEPTH, PARTITION_CHANNEL_FULL_TOTAL,
    PARTITION_ROUTE_DROPPED_TOTAL, PARTITION_SEED_CHANNEL_DEPTH, PARTITION_SEED_CHANNEL_FULL_TOTAL,
};

/// Seed-lane capacity for [`PartitionRouter::new`], the test constructor. Production sizes it from
/// `PARTITION_INTAKE_MAX_SEEDS` via [`PartitionRouter::with_intake_cap`].
const DEFAULT_SEED_CAP: NonZeroUsize = NonZeroUsize::new(1024).unwrap();

const REASON_NO_WORKER: &str = "no_worker";
const REASON_CHANNEL_CLOSED: &str = "channel_closed";

/// A per-partition routing failure. The target worker is gone (usually revoked mid-rebalance);
/// dropped messages are recovered when Kafka replays the uncommitted offsets.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum RouteError {
    /// No worker channel registered for the partition (never assigned, or already revoked).
    #[error("no worker for partition {partition}: not assigned or revoked ({dropped} message(s) dropped)")]
    NoWorker { partition: i32, dropped: usize },

    /// The channel exists but its receiver was dropped, so the worker has stopped.
    #[error("worker channel for partition {partition} is closed ({dropped} message(s) dropped)")]
    ChannelClosed { partition: i32, dropped: usize },
}

/// Per-partition result of [`try_route_batch`](PartitionRouter::try_route_batch). `Full` is
/// backpressure — the events are returned to be held and retried — not a drop.
#[derive(Debug)]
pub enum SendOutcome {
    /// Delivered. `max_offset` is the highest event offset (raises the dispatch ceiling), or `None` if
    /// the batch carries no events; `count` is the number delivered.
    Sent {
        max_offset: Option<i64>,
        count: usize,
    },
    /// Channel full: carries the un-sent sub-batch to hold, pause, and redispatch. No drop recorded.
    Full(Vec<ShuffleMessage>),
    /// No worker registered (never assigned, or revoked). The caller may hold the returned batch;
    /// otherwise Kafka replays it.
    NoWorker(Vec<ShuffleMessage>),
    /// Worker channel closed (worker exited). The caller may hold the returned batch; otherwise Kafka
    /// replays it.
    ChannelClosed(Vec<ShuffleMessage>),
}

/// Per-partition result of [`try_route_seeds`](PartitionRouter::try_route_seeds). Seeds land as a
/// prefix in offset order: the first refused seed ends the attempt, and nothing after it is tried.
///
/// Stopping at the first refusal is what keeps the ceiling exact. The worker drains the lane
/// concurrently, so a `try_send` that returns `Full` can be followed by one that succeeds; carrying
/// on would raise the ceiling past the refused seed, let the worker mark the later one processed,
/// and commit the refused offset away while it still sits in the holdover.
#[derive(Debug)]
pub enum SeedSendOutcome {
    /// Every seed landed; the dispatch ceiling is `max_offset + 1`.
    Sent { max_offset: i64 },
    /// `landed_max` is the highest offset that reached the lane (`None`: nothing did); `rest` is
    /// the non-empty FIFO suffix for the caller to hold. Non-empty by construction, so a fully
    /// landed partition can never be paused for nothing.
    Refused {
        landed_max: Option<i64>,
        reason: SeedRefusal,
        rest: Vec<ConsumedSeed>,
    },
}

/// Why a seed sub-batch stopped short. `Full` is backpressure; the other two mean the worker is
/// gone and Kafka replays whatever the caller does not hold.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SeedRefusal {
    Full,
    NoWorker,
    ChannelClosed,
}

/// The seed lane's sender and the resident-seed meter it shares with the worker's
/// [`SeedReceiver`].
#[derive(Clone)]
struct SeedLane {
    /// One item per seed: the channel's capacity is the seed intake cap. The meter admits and
    /// refuses nothing.
    sender: mpsc::Sender<ConsumedSeed>,
    meter: Arc<SeedLaneMeter>,
}

/// Seeds resident in one partition's seed lane, for [`PARTITION_SEED_CHANNEL_DEPTH`] only: the
/// channel's capacity is the cap, so this count gates nothing. The router adds what it lands, the
/// worker releases a quantum once its last run has applied, and dropping the [`SeedReceiver`]
/// zeroes the series. A gauge read off the sender's free capacity instead would miss the quantum
/// in hand (`recv_many` frees the slots it takes) and pin its last value after a drain or a
/// revoke.
pub(crate) struct SeedLaneMeter {
    resident: AtomicUsize,
    label: Arc<str>,
}

impl SeedLaneMeter {
    fn new(partition: i32) -> Self {
        Self {
            resident: AtomicUsize::new(0),
            label: Arc::from(partition.to_string()),
        }
    }

    fn add(&self, count: usize) {
        self.resident.fetch_add(count, Ordering::AcqRel);
        // Sample fresh: a concurrent release may have lowered the count below the sum.
        self.set_gauge(self.resident.load(Ordering::Acquire));
    }

    /// Saturating, so an accounting slip can never wrap the gauge.
    fn release(&self, count: usize) {
        let mut current = self.resident.load(Ordering::Acquire);
        loop {
            let next = current.saturating_sub(count);
            match self.resident.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    self.set_gauge(next);
                    return;
                }
                Err(observed) => current = observed,
            }
        }
    }

    fn zero(&self) {
        self.resident.store(0, Ordering::Release);
        self.set_gauge(0);
    }

    #[cfg(test)]
    fn resident(&self) -> usize {
        self.resident.load(Ordering::Acquire)
    }

    fn set_gauge(&self, value: usize) {
        gauge!(PARTITION_SEED_CHANNEL_DEPTH, "partition" => self.label.clone()).set(value as f64);
    }
}

/// A registered worker's two lanes: the live sender with the event-intake budget its
/// [`MeteredReceiver`] releases against, and the seed sender. One struct, so a revoke drops both
/// senders together. Cloning shares everything, so a lookup can drop the shard guard before use.
#[derive(Clone)]
struct PartitionChannel {
    live: mpsc::Sender<Vec<ShuffleMessage>>,
    intake: Arc<PartitionIntake>,
    seeds: SeedLane,
}

/// What [`add_partition`](PartitionRouter::add_partition) hands a worker: the live lane behind its
/// intake meter, and the seed lane behind its depth meter.
pub struct WorkerInbox {
    pub live: MeteredReceiver,
    pub seeds: SeedReceiver,
}

impl WorkerInbox {
    /// Uncapped live lane and an already-closed seed lane, for tests that route no seeds.
    pub fn live_only(live: mpsc::Receiver<Vec<ShuffleMessage>>) -> Self {
        let (_, seeds) = mpsc::channel(1);
        Self::unmetered(live, seeds)
    }

    /// Uncapped live lane paired with a caller-owned seed lane, for tests that drive both.
    pub fn unmetered(
        live: mpsc::Receiver<Vec<ShuffleMessage>>,
        seeds: mpsc::Receiver<ConsumedSeed>,
    ) -> Self {
        Self {
            live: MeteredReceiver::unmetered(live),
            seeds: SeedReceiver::unmetered(seeds),
        }
    }
}

/// Worker-side end of the seed lane. Seeds taken by [`recv_many`](Self::recv_many) stay counted on
/// the meter until [`finish_turn`](Self::finish_turn), so the depth gauge covers the quantum being
/// applied; dropping it zeroes the gauge, so a revoked partition's series does not pin.
pub struct SeedReceiver {
    receiver: mpsc::Receiver<ConsumedSeed>,
    meter: Arc<SeedLaneMeter>,
    /// Seeds taken since the last `finish_turn`.
    in_hand: usize,
}

impl SeedReceiver {
    fn new(receiver: mpsc::Receiver<ConsumedSeed>, meter: Arc<SeedLaneMeter>) -> Self {
        Self {
            receiver,
            meter,
            in_hand: 0,
        }
    }

    /// A lane whose sends bypass the meter, for tests that own the sender.
    pub fn unmetered(receiver: mpsc::Receiver<ConsumedSeed>) -> Self {
        Self::new(receiver, Arc::new(SeedLaneMeter::new(0)))
    }

    /// Take up to `limit` seeds, waiting for the first; `0` means the lane closed. Cancel-safe, so
    /// the worker can poll it as a `select!` branch: the count moves only on completion.
    pub async fn recv_many(&mut self, buffer: &mut Vec<ConsumedSeed>, limit: usize) -> usize {
        let taken = self.receiver.recv_many(buffer, limit).await;
        self.in_hand += taken;
        taken
    }

    /// Release everything taken since the last call. The worker calls it once every run of the
    /// quantum has applied.
    pub fn finish_turn(&mut self) {
        let taken = std::mem::take(&mut self.in_hand);
        if taken > 0 {
            self.meter.release(taken);
        }
    }

    /// Non-awaiting single take for tests; counts on the meter like [`recv_many`](Self::recv_many).
    #[cfg(test)]
    pub fn try_recv(&mut self) -> Result<ConsumedSeed, mpsc::error::TryRecvError> {
        let seed = self.receiver.try_recv()?;
        self.in_hand += 1;
        Ok(seed)
    }
}

impl Drop for SeedReceiver {
    fn drop(&mut self) {
        self.meter.zero();
    }
}

/// Routes per-partition sub-batches to long-lived per-partition worker lanes.
pub struct PartitionRouter {
    channels: DashMap<i32, PartitionChannel>,
    channel_buffer: usize,
    /// Per-partition ceiling on un-drained events; `usize::MAX` disables it (only the mpsc slots bound).
    intake_cap: usize,
    /// The seed lane's capacity, in seeds. `NonZeroUsize` because tokio panics on a zero-capacity
    /// channel, so the type carries what a worker spawn depends on.
    seed_cap: NonZeroUsize,
    /// Terminal: set by [`clear`](Self::clear), never unset. Read under the shard guard so no
    /// channel can be registered after the clear's removal pass.
    closed: AtomicBool,
}

impl PartitionRouter {
    /// Router with the event-intake budget disabled — only the mpsc slots bound — and a default
    /// seed cap. Tests only: production must use [`with_intake_cap`](Self::with_intake_cap) so both
    /// lanes are always bounded.
    pub fn new(channel_buffer: usize) -> Self {
        Self::with_intake_cap(channel_buffer, usize::MAX, DEFAULT_SEED_CAP)
    }

    pub fn with_intake_cap(
        channel_buffer: usize,
        intake_cap: usize,
        seed_cap: NonZeroUsize,
    ) -> Self {
        Self {
            channels: DashMap::new(),
            channel_buffer,
            intake_cap,
            seed_cap,
            closed: AtomicBool::new(false),
        }
    }

    /// Register both lanes for `partition` and return the worker's [`WorkerInbox`].
    ///
    /// Returns `None` if: already registered with a live channel (reuses existing), or the router
    /// is closed. A half-dead channel — either lane's receiver dropped — is replaced (self-heal)
    /// with a fresh pair and a fresh intake, discarding any stale counter from the prior
    /// incarnation.
    pub fn add_partition(&self, partition: i32) -> Option<WorkerInbox> {
        let entry = self.channels.entry(partition);
        if self.closed.load(Ordering::SeqCst) {
            drop(entry);
            warn!(
                partition,
                "router is closed (cleared for shutdown); refusing to register a worker channel"
            );
            return None;
        }
        let inbox = match entry {
            Entry::Occupied(mut slot) => {
                let dead = slot.get().live.is_closed() || slot.get().seeds.sender.is_closed();
                if dead {
                    let (channel, inbox) = self.make_channel(partition);
                    slot.insert(channel);
                    warn!(
                        partition,
                        "replacing closed worker channel on reassign (previous worker exited without revoke)"
                    );
                    Some(inbox)
                } else {
                    warn!(
                        partition,
                        "partition already registered; reusing the existing worker channel"
                    );
                    None
                }
            }
            Entry::Vacant(slot) => {
                let (channel, inbox) = self.make_channel(partition);
                slot.insert(channel);
                Some(inbox)
            }
        };
        if inbox.is_some() {
            self.emit_active_gauge();
        }
        inbox
    }

    fn make_channel(&self, partition: i32) -> (PartitionChannel, WorkerInbox) {
        let (live_tx, live_rx) = mpsc::channel(self.channel_buffer);
        let (seed_tx, seed_rx) = mpsc::channel(self.seed_cap.get());
        let intake = Arc::new(PartitionIntake::new(partition, self.intake_cap));
        let meter = Arc::new(SeedLaneMeter::new(partition));
        let live = MeteredReceiver::new(live_rx, intake.clone());
        let channel = PartitionChannel {
            live: live_tx,
            intake,
            seeds: SeedLane {
                sender: seed_tx,
                meter: meter.clone(),
            },
        };
        (
            channel,
            WorkerInbox {
                live,
                seeds: SeedReceiver::new(seed_rx, meter),
            },
        )
    }

    /// Drop the sender for `partition`, signalling the worker to shut down. Idempotent.
    pub fn remove_partition(&self, partition: i32) {
        if self.channels.remove(&partition).is_some() {
            self.emit_active_gauge();
        }
    }

    /// Drop every sender and terminally close the router. All later `add_partition` calls refuse.
    pub fn clear(&self) {
        self.closed.store(true, Ordering::SeqCst);
        self.channels.clear();
        self.emit_active_gauge();
    }

    /// Whether the router has been terminally closed.
    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
    }

    /// Group a batch by partition and dispatch each sub-batch to its worker, preserving
    /// per-partition order. Per-partition failures are collected rather than aborting the batch.
    ///
    /// This async path does **not** apply the event-intake cap, so it must carry only maintenance/
    /// control messages (which carry no events). Events go through the bounded
    /// [`try_route_batch`](Self::try_route_batch).
    pub async fn route_batch(&self, messages: Vec<(i32, ShuffleMessage)>) -> Vec<RouteError> {
        if messages.is_empty() {
            return Vec::new();
        }

        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }

        let sends = by_partition
            .into_iter()
            .map(|(partition, batch)| self.send_to_partition(partition, batch));
        join_all(sends).await.into_iter().flatten().collect()
    }

    async fn send_to_partition(
        &self,
        partition: i32,
        batch: Vec<ShuffleMessage>,
    ) -> Option<RouteError> {
        let dropped = batch.len();

        let Some(channel) = self.channel_for(partition) else {
            self.record_drop(partition, dropped, REASON_NO_WORKER);
            return Some(RouteError::NoWorker { partition, dropped });
        };

        // Uncapped: control messages carry no events, so they must always flow.
        match channel.live.send(batch).await {
            Ok(()) => {
                self.emit_channel_depth(partition, &channel.live);
                None
            }
            Err(mpsc::error::SendError(returned)) => {
                self.record_drop(partition, returned.len(), REASON_CHANNEL_CLOSED);
                Some(RouteError::ChannelClosed {
                    partition,
                    dropped: returned.len(),
                })
            }
        }
    }

    /// Non-blocking sibling of [`route_batch`](Self::route_batch): group by partition and `try_send`
    /// each sub-batch, returning the per-partition [`SendOutcome`] instead of awaiting a drain.
    pub fn try_route_batch(
        &self,
        messages: Vec<(i32, ShuffleMessage)>,
    ) -> HashMap<i32, SendOutcome> {
        if messages.is_empty() {
            return HashMap::new();
        }
        let mut by_partition: HashMap<i32, Vec<ShuffleMessage>> = HashMap::new();
        for (partition, message) in messages {
            by_partition.entry(partition).or_default().push(message);
        }
        by_partition
            .into_iter()
            .map(|(partition, batch)| (partition, self.try_send_to_partition(partition, batch)))
            .collect()
    }

    fn try_send_to_partition(&self, partition: i32, batch: Vec<ShuffleMessage>) -> SendOutcome {
        let Some(channel) = self.channel_for(partition) else {
            return SendOutcome::NoWorker(batch);
        };
        let count = batch.len();
        // `None` for an event-less batch — carried through, not defaulted to 0, so a non-Event caller
        // can't fabricate a ceiling (the dispatcher only marks when `Some`).
        let max_offset = batch.iter().filter_map(ShuffleMessage::event_offset).max();
        // Refuse (→ hold → pause) once the partition holds its event ceiling, before the batch reaches
        // the mpsc slot. Count events only, so an event-less batch reserves 0 and stays balanced with
        // the receiver's release.
        let counted = count_intake(&batch);
        if channel.intake.try_admit(counted) == Admission::Rejected {
            counter!(PARTITION_CHANNEL_FULL_TOTAL, "partition" => partition.to_string())
                .increment(batch.len() as u64);
            return SendOutcome::Full(batch);
        }
        match channel.live.try_send(batch) {
            Ok(()) => {
                self.emit_channel_depth(partition, &channel.live);
                SendOutcome::Sent { max_offset, count }
            }
            Err(TrySendError::Full(returned)) => {
                // Reserved above but the slot is full: release so the counter tracks only what landed.
                channel.intake.release(counted);
                counter!(PARTITION_CHANNEL_FULL_TOTAL, "partition" => partition.to_string())
                    .increment(returned.len() as u64);
                SendOutcome::Full(returned)
            }
            Err(TrySendError::Closed(returned)) => {
                channel.intake.release(counted);
                SendOutcome::ChannelClosed(returned)
            }
        }
    }

    /// Group `seeds` by partition, preserving offset order, and `try_send` each sub-batch onto its
    /// worker's seed lane. Never touches the live lane or its intake budget.
    pub fn try_route_seeds(&self, seeds: Vec<ConsumedSeed>) -> HashMap<i32, SeedSendOutcome> {
        if seeds.is_empty() {
            return HashMap::new();
        }
        let mut by_partition: HashMap<i32, Vec<ConsumedSeed>> = HashMap::new();
        for seed in seeds {
            by_partition.entry(seed.partition).or_default().push(seed);
        }
        by_partition
            .into_iter()
            .map(|(partition, batch)| (partition, self.try_send_seeds(partition, batch)))
            .collect()
    }

    /// Send one partition's seeds, in order, until one is refused. `seeds` is non-empty: it comes
    /// from the grouping in [`try_route_seeds`](Self::try_route_seeds).
    fn try_send_seeds(&self, partition: i32, seeds: Vec<ConsumedSeed>) -> SeedSendOutcome {
        let Some(channel) = self.channel_for(partition) else {
            return SeedSendOutcome::Refused {
                landed_max: None,
                reason: SeedRefusal::NoWorker,
                rest: seeds,
            };
        };
        let lane = &channel.seeds;

        let mut landed_max: Option<i64> = None;
        let mut landed = 0usize;
        let mut remaining = seeds.into_iter();
        let mut refused = None;
        for seed in remaining.by_ref() {
            let offset = seed.offset;
            match lane.sender.try_send(seed) {
                Ok(()) => {
                    landed += 1;
                    landed_max = Some(landed_max.map_or(offset, |max| max.max(offset)));
                }
                Err(TrySendError::Full(seed)) => {
                    refused = Some((SeedRefusal::Full, seed));
                    break;
                }
                Err(TrySendError::Closed(seed)) => {
                    refused = Some((SeedRefusal::ChannelClosed, seed));
                    break;
                }
            }
        }
        // Once per sub-batch, never per seed: one gauge write covers everything that landed.
        lane.meter.add(landed);

        let Some((reason, seed)) = refused else {
            return SeedSendOutcome::Sent {
                max_offset: landed_max.expect("a grouped sub-batch is never empty"),
            };
        };
        // The refused seed and everything behind it go back untried, so the ceiling never rises
        // past a hole and per-partition FIFO holds.
        let rest: Vec<ConsumedSeed> = std::iter::once(seed).chain(remaining).collect();
        if reason == SeedRefusal::Full {
            counter!(PARTITION_SEED_CHANNEL_FULL_TOTAL, "partition" => lane.meter.label.clone())
                .increment(rest.len() as u64);
        }
        SeedSendOutcome::Refused {
            landed_max,
            reason,
            rest,
        }
    }

    pub fn partition_count(&self) -> usize {
        self.channels.len()
    }

    /// Whether a worker channel is registered for `partition`.
    ///
    /// A registered-but-closed channel (a worker that exited without a revoke) still returns `true`:
    /// this gates maintenance-tick fan-out, and a tick to such a partition should still be attempted
    /// so it surfaces as `channel_closed` rather than being silently skipped. Only a partition with no
    /// channel at all — the idle steady state — is reported absent, letting a tick skip the guaranteed
    /// `no_worker` no-op.
    pub fn has_partition(&self, partition: i32) -> bool {
        self.channels.contains_key(&partition)
    }

    /// Clone the channel out from under the shard guard so callers can send after dropping it.
    fn channel_for(&self, partition: i32) -> Option<PartitionChannel> {
        Some(self.channels.get(&partition)?.clone())
    }

    fn record_drop(&self, partition: i32, dropped: usize, reason: &'static str) {
        warn!(
            partition,
            dropped, reason, "dropped messages while routing: target worker is gone"
        );
        counter!(PARTITION_ROUTE_DROPPED_TOTAL, "reason" => reason).increment(dropped as u64);
    }

    /// The live lane's depth. The seed lane's is kept by its [`SeedLaneMeter`], which both ends
    /// update.
    fn emit_channel_depth(&self, partition: i32, sender: &mpsc::Sender<Vec<ShuffleMessage>>) {
        let depth = sender.max_capacity().saturating_sub(sender.capacity());
        gauge!(PARTITION_CHANNEL_DEPTH, "partition" => partition.to_string()).set(depth as f64);
    }

    fn emit_active_gauge(&self) {
        gauge!(PARTITIONS_ACTIVE).set(self.channels.len() as f64);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consumers::events::CohortStreamEvent;
    use futures::future::FutureExt;

    fn event(tag: i64) -> ShuffleMessage {
        ShuffleMessage::Event {
            event: Box::new(CohortStreamEvent {
                team_id: 1,
                person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
                distinct_id: "d".to_string(),
                uuid: "u".to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: None,
                person_properties: None,
                elements_chain: None,
                source_offset: tag,
                source_partition: 0,
                redirected_from: None,
                redirect_hops: 0,
            }),
            cse_offset: 0,
            broker_ts_ms: None,
        }
    }

    fn tags(batch: &[ShuffleMessage]) -> Vec<i64> {
        batch
            .iter()
            .map(|message| match message {
                ShuffleMessage::Event { event, .. } => event.source_offset,
                ShuffleMessage::Sweep { .. }
                | ShuffleMessage::Merge { .. }
                | ShuffleMessage::Transfer { .. }
                | ShuffleMessage::Cascade { .. }
                | ShuffleMessage::RedrivePendingTransfers
                | ShuffleMessage::MergeCfGc { .. }
                | ShuffleMessage::ReconcileDrain => {
                    unreachable!("router tests route only events")
                }
            })
            .collect()
    }

    #[tokio::test]
    async fn same_partition_messages_land_on_one_channel_in_order_isolated_per_partition() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router
            .add_partition(5)
            .expect("first add returns the receiver");
        let mut rx6 = router
            .add_partition(6)
            .expect("first add returns the receiver");

        let errors = router
            .route_batch(vec![(5, event(1)), (6, event(2)), (5, event(3))])
            .await;
        assert!(errors.is_empty(), "no worker should be missing");

        assert_eq!(tags(&rx5.live.recv().await.unwrap()), vec![1, 3]);
        assert_eq!(tags(&rx6.live.recv().await.unwrap()), vec![2]);

        assert!(router.route_batch(vec![(5, event(4))]).await.is_empty());
        assert_eq!(tags(&rx5.live.recv().await.unwrap()), vec![4]);
    }

    #[tokio::test]
    async fn routing_to_a_removed_partition_surfaces_an_error_without_panicking() {
        let router = PartitionRouter::new(16);
        let _rx5 = router.add_partition(5).unwrap();

        router.remove_partition(5);
        assert_eq!(router.partition_count(), 0);

        let errors = router.route_batch(vec![(5, event(1))]).await;
        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 5,
                dropped: 1
            }]
        );
    }

    #[tokio::test]
    async fn re_adding_a_partition_after_removal_routes_cleanly() {
        let router = PartitionRouter::new(16);
        let _rx_old = router.add_partition(5).unwrap();
        router.remove_partition(5);

        let mut rx_new = router
            .add_partition(5)
            .expect("re-add after removal yields a fresh receiver");
        assert!(router.route_batch(vec![(5, event(9))]).await.is_empty());
        assert_eq!(tags(&rx_new.live.recv().await.unwrap()), vec![9]);
    }

    #[tokio::test]
    async fn re_adding_an_active_partition_reuses_the_channel() {
        let router = PartitionRouter::new(16);
        let mut rx = router.add_partition(5).unwrap();

        assert!(router.add_partition(5).is_none());
        assert_eq!(router.partition_count(), 1);

        assert!(router.route_batch(vec![(5, event(1))]).await.is_empty());
        assert_eq!(tags(&rx.live.recv().await.unwrap()), vec![1]);
    }

    #[tokio::test]
    async fn routing_after_the_worker_dropped_its_receiver_reports_channel_closed() {
        let router = PartitionRouter::new(16);
        let rx = router.add_partition(5).unwrap();
        drop(rx);

        let errors = router.route_batch(vec![(5, event(1)), (5, event(2))]).await;
        assert_eq!(
            errors,
            vec![RouteError::ChannelClosed {
                partition: 5,
                dropped: 2
            }]
        );
    }

    #[tokio::test]
    async fn mixed_batch_with_one_missing_partition_routes_the_rest() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router.add_partition(5).unwrap();

        let errors = router
            .route_batch(vec![(5, event(1)), (7, event(2)), (5, event(3))])
            .await;

        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 7,
                dropped: 1
            }]
        );
        assert_eq!(tags(&rx5.live.recv().await.unwrap()), vec![1, 3]);
    }

    #[tokio::test]
    async fn empty_batch_is_a_no_op() {
        let router = PartitionRouter::new(16);
        assert!(router.route_batch(vec![]).await.is_empty());
    }

    #[tokio::test]
    async fn route_batch_fans_out_so_a_full_channel_does_not_block_other_partitions() {
        let router = PartitionRouter::new(1);
        let mut rx1 = router.add_partition(1).unwrap();
        let mut rx2 = router.add_partition(2).unwrap();

        assert!(router.route_batch(vec![(1, event(100))]).await.is_empty());

        let routed = router.route_batch(vec![(1, event(1)), (2, event(2))]);
        tokio::pin!(routed);

        assert!(
            routed.as_mut().now_or_never().is_none(),
            "route_batch must stay pending while partition 1 is backpressured"
        );

        assert_eq!(tags(&rx2.live.try_recv().unwrap()), vec![2]);

        assert_eq!(tags(&rx1.live.try_recv().unwrap()), vec![100]);
        assert!(rx1.live.try_recv().is_err());
    }

    #[tokio::test]
    async fn clear_closes_the_router_so_add_partition_refuses() {
        let router = PartitionRouter::new(16);
        let mut rx = router.add_partition(5).unwrap();

        router.clear();
        assert!(router.is_closed());
        assert!(
            rx.live.recv().await.is_none(),
            "clear dropped the live sender"
        );

        assert!(
            router.add_partition(5).is_none(),
            "re-registration after clear is refused",
        );
        assert!(
            router.add_partition(6).is_none(),
            "first-time registration after clear is refused too",
        );
        assert_eq!(router.partition_count(), 0, "nothing was inserted");

        let errors = router.route_batch(vec![(5, event(1))]).await;
        assert_eq!(
            errors,
            vec![RouteError::NoWorker {
                partition: 5,
                dropped: 1
            }]
        );
    }

    #[tokio::test]
    async fn re_adding_a_partition_whose_worker_died_without_revoke_self_heals() {
        let router = PartitionRouter::new(16);
        let rx_dead = router.add_partition(5).unwrap();
        drop(rx_dead);

        let mut rx_new = router
            .add_partition(5)
            .expect("closed slot self-heals to a fresh receiver");
        assert_eq!(router.partition_count(), 1);

        assert!(router.route_batch(vec![(5, event(7))]).await.is_empty());
        assert_eq!(tags(&rx_new.live.recv().await.unwrap()), vec![7]);
    }

    /// An event whose `cse_offset` matches its `source_offset` tag, so [`tags`] and `max_offset`
    /// assertions line up.
    fn event_off(cse_offset: i64) -> ShuffleMessage {
        match event(cse_offset) {
            ShuffleMessage::Event { event, .. } => ShuffleMessage::Event {
                event,
                cse_offset,
                broker_ts_ms: None,
            },
            other => other,
        }
    }

    #[tokio::test]
    async fn try_route_batch_delivers_and_reports_the_max_offset_and_count() {
        let router = PartitionRouter::new(16);
        let mut rx5 = router.add_partition(5).unwrap();
        let mut rx6 = router.add_partition(6).unwrap();

        let mut outcomes = router.try_route_batch(vec![
            (5, event_off(1)),
            (6, event_off(2)),
            (5, event_off(3)),
        ]);

        match outcomes.remove(&5) {
            Some(SendOutcome::Sent { max_offset, count }) => {
                assert_eq!((max_offset, count), (Some(3), 2));
            }
            other => panic!("expected Sent for 5, got {other:?}"),
        }
        match outcomes.remove(&6) {
            Some(SendOutcome::Sent { max_offset, count }) => {
                assert_eq!((max_offset, count), (Some(2), 1));
            }
            other => panic!("expected Sent for 6, got {other:?}"),
        }
        assert_eq!(tags(&rx5.live.try_recv().unwrap()), vec![1, 3]);
        assert_eq!(tags(&rx6.live.try_recv().unwrap()), vec![2]);
    }

    #[tokio::test]
    async fn try_route_batch_returns_the_batch_on_full_without_recording_a_drop() {
        let router = PartitionRouter::new(1);
        let mut rx = router.add_partition(1).unwrap();

        // Saturate the slot, then the next try hands the batch back untouched.
        assert!(matches!(
            router.try_route_batch(vec![(1, event_off(100))]).remove(&1),
            Some(SendOutcome::Sent { .. }),
        ));

        match router.try_route_batch(vec![(1, event_off(7))]).remove(&1) {
            Some(SendOutcome::Full(returned)) => assert_eq!(tags(&returned), vec![7]),
            other => panic!("expected Full, got {other:?}"),
        }
        assert_eq!(tags(&rx.live.try_recv().unwrap()), vec![100]);
        assert!(rx.live.try_recv().is_err());
    }

    #[tokio::test]
    async fn try_route_batch_reports_no_worker_and_channel_closed() {
        let router = PartitionRouter::new(16);
        match router.try_route_batch(vec![(9, event_off(1))]).remove(&9) {
            Some(SendOutcome::NoWorker(returned)) => assert_eq!(tags(&returned), vec![1]),
            other => panic!("expected NoWorker, got {other:?}"),
        }

        let rx = router.add_partition(3).unwrap();
        drop(rx);
        match router.try_route_batch(vec![(3, event_off(1))]).remove(&3) {
            Some(SendOutcome::ChannelClosed(returned)) => assert_eq!(tags(&returned), vec![1]),
            other => panic!("expected ChannelClosed, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn try_route_batch_isolates_a_full_partition_from_a_free_one() {
        let router = PartitionRouter::new(1);
        let mut rx2 = router.add_partition(2).unwrap();
        let _rx1 = router.add_partition(1).unwrap();
        router.try_route_batch(vec![(1, event_off(100))]);

        let mut outcomes = router.try_route_batch(vec![(1, event_off(1)), (2, event_off(2))]);
        assert!(matches!(outcomes.remove(&1), Some(SendOutcome::Full(_))));
        assert!(matches!(
            outcomes.remove(&2),
            Some(SendOutcome::Sent { .. })
        ));
        assert_eq!(tags(&rx2.live.try_recv().unwrap()), vec![2]);
    }

    #[tokio::test]
    async fn try_route_batch_is_empty_for_an_empty_batch() {
        let router = PartitionRouter::new(16);
        assert!(router.try_route_batch(vec![]).is_empty());
    }

    #[tokio::test]
    async fn has_partition_tracks_registration_not_channel_liveness() {
        let router = PartitionRouter::new(16);
        assert!(!router.has_partition(5), "absent before any registration");

        let rx = router.add_partition(5).unwrap();
        assert!(
            router.has_partition(5),
            "present once a channel is registered"
        );

        // Worker exited without a revoke: the channel is closed but still registered. It must stay
        // "present" so a maintenance tick still attempts it and surfaces `channel_closed`, rather than
        // being silently skipped as if it were idle.
        drop(rx);
        assert!(
            router.has_partition(5),
            "a closed-but-registered channel still counts as present",
        );

        router.remove_partition(5);
        assert!(!router.has_partition(5), "absent after removal");
    }

    #[tokio::test]
    async fn the_event_cap_trips_full_before_the_mpsc_slots_fill() {
        // Two-event ceiling, 16 free slots: the intake refuses the third event with room to spare.
        let router = PartitionRouter::with_intake_cap(16, 2, DEFAULT_SEED_CAP);
        let mut rx = router.add_partition(5).unwrap();

        match router
            .try_route_batch(vec![(5, event_off(1)), (5, event_off(2))])
            .remove(&5)
        {
            Some(SendOutcome::Sent { count, .. }) => assert_eq!(count, 2),
            other => panic!("expected the first two events to land, got {other:?}"),
        }
        match router.try_route_batch(vec![(5, event_off(3))]).remove(&5) {
            Some(SendOutcome::Full(returned)) => assert_eq!(tags(&returned), vec![3]),
            other => panic!("expected the over-cap event to be held, got {other:?}"),
        }

        // The budget frees on the *next* recv (it covers the in-hand batch), so step past the drain.
        assert_eq!(tags(&rx.live.recv().await.unwrap()), vec![1, 2]);
        assert!(
            rx.live.try_recv().is_err(),
            "channel now empty; this recv released the drained batch",
        );
        assert!(matches!(
            router.try_route_batch(vec![(5, event_off(3))]).remove(&5),
            Some(SendOutcome::Sent { .. }),
        ));
    }

    #[tokio::test]
    async fn maintenance_sends_bypass_the_event_cap() {
        let router = PartitionRouter::with_intake_cap(16, 1, DEFAULT_SEED_CAP);
        let mut rx = router.add_partition(5).unwrap();

        assert!(matches!(
            router.try_route_batch(vec![(5, event_off(1))]).remove(&5),
            Some(SendOutcome::Sent { .. }),
        ));
        assert!(
            matches!(
                router.try_route_batch(vec![(5, event_off(2))]).remove(&5),
                Some(SendOutcome::Full(_)),
            ),
            "the partition is at its event ceiling",
        );

        let sweep = || ShuffleMessage::Sweep { due_before_ms: 1 };
        assert!(
            router.route_batch(vec![(5, sweep())]).await.is_empty(),
            "the maintenance tick flows past a full event budget",
        );

        assert_eq!(tags(&rx.live.recv().await.unwrap()), vec![1]);
        assert!(
            matches!(rx.live.recv().await, Some(batch) if matches!(batch.as_slice(), [ShuffleMessage::Sweep { .. }])),
            "the sweep was delivered despite the full event budget",
        );
    }

    fn consumed_seed(partition: i32, offset: i64) -> ConsumedSeed {
        use cohort_core::seed::{ClaimEpoch, ConditionHash, RunId, SChunkMs, SeedTile};

        crate::consumers::seeds::ConsumedSeed {
            work: crate::consumers::seeds::SeedWork::Tile(SeedTile::new(
                crate::filters::TeamId(1),
                uuid::Uuid::from_u128(offset as u128 + 1),
                ConditionHash::parse("0123456789abcdef").unwrap(),
                std::num::NonZeroU32::new(1).unwrap(),
                20_614,
                SChunkMs(1_700_000_000_000),
                RunId(uuid::Uuid::nil()),
                ClaimEpoch(1),
            )),
            partition,
            offset,
            broker_ts_ms: None,
        }
    }

    fn seed_offsets(seeds: &[ConsumedSeed]) -> Vec<i64> {
        seeds.iter().map(|seed| seed.offset).collect()
    }

    fn drain_seeds(receiver: &mut SeedReceiver) -> Vec<i64> {
        let mut taken = Vec::new();
        while let Ok(seed) = receiver.try_recv() {
            taken.push(seed.offset);
        }
        taken
    }

    fn cap(value: usize) -> NonZeroUsize {
        NonZeroUsize::new(value).expect("a test capacity is non-zero")
    }

    #[tokio::test]
    async fn seed_lane_capacity_is_independent_of_the_live_intake() {
        // One event of live budget and one slot of seed lane: saturating either must leave the
        // other free, or the two lanes are sharing a budget again.
        let router = PartitionRouter::with_intake_cap(16, 1, cap(1));
        let mut inbox = router.add_partition(5).unwrap();

        assert!(matches!(
            router.try_route_batch(vec![(5, event_off(1))]).remove(&5),
            Some(SendOutcome::Sent { .. }),
        ));
        assert!(
            matches!(
                router
                    .try_route_seeds(vec![consumed_seed(5, 10)])
                    .remove(&5),
                Some(SeedSendOutcome::Sent { max_offset: 10 }),
            ),
            "a saturated live intake must not refuse a seed",
        );

        // Both lanes are now full. Free only the seed lane, and the live lane stays refused.
        assert_eq!(drain_seeds(&mut inbox.seeds), vec![10]);
        assert!(
            matches!(
                router.try_route_batch(vec![(5, event_off(2))]).remove(&5),
                Some(SendOutcome::Full(_)),
            ),
            "draining the seed lane must not free live intake",
        );

        // Free only the live lane; the seed lane still has its slot.
        assert_eq!(tags(&inbox.live.recv().await.unwrap()), vec![1]);
        assert!(inbox.live.try_recv().is_err(), "that recv released event 1");
        assert!(matches!(
            router
                .try_route_seeds(vec![consumed_seed(5, 11)])
                .remove(&5),
            Some(SeedSendOutcome::Sent { max_offset: 11 }),
        ));
    }

    #[tokio::test]
    async fn seed_routing_preserves_order_and_ceiling_per_partition() {
        let router = PartitionRouter::with_intake_cap(16, usize::MAX, cap(8));
        let mut five = router.add_partition(5).unwrap();
        let mut six = router.add_partition(6).unwrap();

        let mut outcomes = router.try_route_seeds(vec![
            consumed_seed(5, 1),
            consumed_seed(6, 2),
            consumed_seed(5, 3),
        ]);

        assert!(matches!(
            outcomes.remove(&5),
            Some(SeedSendOutcome::Sent { max_offset: 3 })
        ));
        assert!(matches!(
            outcomes.remove(&6),
            Some(SeedSendOutcome::Sent { max_offset: 2 })
        ));
        assert!(outcomes.is_empty());
        assert_eq!(drain_seeds(&mut five.seeds), vec![1, 3]);
        assert_eq!(drain_seeds(&mut six.seeds), vec![2]);
    }

    /// A refusal is only reachable here with the lane already full, so the stop-at-first-refusal
    /// loop itself cannot be staged — that needs a concurrent drain between two `try_send`s. What
    /// is observable is its consequence, and the one that matters: the reported ceiling follows
    /// what landed, never the batch maximum, and the suffix comes back whole and in order.
    #[tokio::test]
    async fn a_seed_sub_batch_lands_as_a_prefix_and_the_ceiling_follows_only_what_landed() {
        let router = PartitionRouter::with_intake_cap(16, usize::MAX, cap(2));
        let mut inbox = router.add_partition(5).unwrap();

        let five = vec![
            consumed_seed(5, 1),
            consumed_seed(5, 2),
            consumed_seed(5, 3),
            consumed_seed(5, 4),
            consumed_seed(5, 5),
        ];
        let suffix = match router.try_route_seeds(five).remove(&5) {
            Some(SeedSendOutcome::Refused {
                landed_max,
                reason,
                rest,
            }) => {
                assert_eq!(landed_max, Some(2), "only the first two fit the lane");
                assert_eq!(reason, SeedRefusal::Full);
                assert_eq!(
                    seed_offsets(&rest),
                    vec![3, 4, 5],
                    "the suffix from the first refusal on, in order and untried",
                );
                rest
            }
            other => panic!("expected a prefix landing, got {other:?}"),
        };

        // Free exactly one slot: only the head of the suffix may land, and 4 and 5 stay behind it.
        let head = inbox.seeds.try_recv().expect("the lane holds two").offset;
        assert_eq!(head, 1);
        match router.try_route_seeds(suffix).remove(&5) {
            Some(SeedSendOutcome::Refused {
                landed_max,
                reason,
                rest,
            }) => {
                assert_eq!(landed_max, Some(3));
                assert_eq!(reason, SeedRefusal::Full);
                assert_eq!(seed_offsets(&rest), vec![4, 5]);
            }
            other => panic!("expected the third to land alone, got {other:?}"),
        }
        assert_eq!(drain_seeds(&mut inbox.seeds), vec![2, 3]);
    }

    #[tokio::test]
    async fn remove_partition_closes_both_lanes() {
        let router = PartitionRouter::new(16);
        let mut inbox = router.add_partition(5).unwrap();

        router.remove_partition(5);

        // `try_recv` rather than `recv`: a lane that outlived the revoke must fail this test, not
        // hang it (and it would hang the worker loop the same way).
        assert!(
            matches!(
                inbox.live.try_recv(),
                Err(mpsc::error::TryRecvError::Disconnected)
            ),
            "the live lane closed",
        );
        assert!(
            matches!(
                inbox.seeds.try_recv(),
                Err(mpsc::error::TryRecvError::Disconnected)
            ),
            "the seed lane closed with the same revoke",
        );
    }

    #[tokio::test]
    async fn try_route_seeds_reports_no_worker_and_channel_closed() {
        let router = PartitionRouter::new(16);
        match router.try_route_seeds(vec![consumed_seed(9, 1)]).remove(&9) {
            Some(SeedSendOutcome::Refused {
                landed_max,
                reason,
                rest,
            }) => {
                assert_eq!((landed_max, reason), (None, SeedRefusal::NoWorker));
                assert_eq!(seed_offsets(&rest), vec![1]);
            }
            other => panic!("expected NoWorker, got {other:?}"),
        }

        let inbox = router.add_partition(3).unwrap();
        drop(inbox);
        match router.try_route_seeds(vec![consumed_seed(3, 1)]).remove(&3) {
            Some(SeedSendOutcome::Refused {
                landed_max,
                reason,
                rest,
            }) => {
                assert_eq!((landed_max, reason), (None, SeedRefusal::ChannelClosed));
                assert_eq!(seed_offsets(&rest), vec![1]);
            }
            other => panic!("expected ChannelClosed, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn try_route_seeds_is_empty_for_an_empty_batch() {
        let router = PartitionRouter::new(16);
        assert!(router.try_route_seeds(vec![]).is_empty());
    }

    /// The depth gauge must cover the queued seeds and the quantum in hand, and must not pin after
    /// the lane drains or the partition is revoked.
    #[tokio::test]
    async fn the_seed_lane_meter_counts_the_quantum_in_hand_and_zeroes_on_drop() {
        let router = PartitionRouter::with_intake_cap(16, usize::MAX, cap(2));
        let mut inbox = router.add_partition(5).unwrap();
        let meter = router
            .channels
            .get(&5)
            .expect("partition 5 is registered")
            .seeds
            .meter
            .clone();

        // Three seeds onto a two-slot lane: only what landed counts, never the refused suffix.
        assert!(matches!(
            router
                .try_route_seeds(vec![
                    consumed_seed(5, 1),
                    consumed_seed(5, 2),
                    consumed_seed(5, 3)
                ])
                .remove(&5),
            Some(SeedSendOutcome::Refused {
                landed_max: Some(2),
                ..
            }),
        ));
        assert_eq!(meter.resident(), 2);

        // Taking the quantum frees the lane's slots but not the meter: the seeds are in hand.
        let mut quantum = Vec::new();
        assert_eq!(
            futures::FutureExt::now_or_never(inbox.seeds.recv_many(&mut quantum, 8)),
            Some(2)
        );
        assert_eq!(meter.resident(), 2, "the quantum in hand still counts");
        assert!(matches!(
            router.try_route_seeds(vec![consumed_seed(5, 3)]).remove(&5),
            Some(SeedSendOutcome::Sent { max_offset: 3 }),
        ));
        assert_eq!(meter.resident(), 3, "queued plus in hand");

        inbox.seeds.finish_turn();
        assert_eq!(meter.resident(), 1, "only the queued seed stays counted");

        // A revoke drops the worker's end with whatever it still held, and the series clears.
        router.remove_partition(5);
        drop(inbox);
        assert_eq!(meter.resident(), 0);
    }

    #[tokio::test]
    async fn an_idle_partition_admits_an_over_cap_batch() {
        let router = PartitionRouter::with_intake_cap(16, 2, DEFAULT_SEED_CAP);
        let mut rx = router.add_partition(5).unwrap();

        match router
            .try_route_batch(vec![
                (5, event_off(1)),
                (5, event_off(2)),
                (5, event_off(3)),
            ])
            .remove(&5)
        {
            Some(SendOutcome::Sent { count, .. }) => assert_eq!(count, 3),
            other => panic!("an idle partition must admit an over-cap batch, got {other:?}"),
        }
        assert_eq!(tags(&rx.live.recv().await.unwrap()), vec![1, 2, 3]);
    }
}
