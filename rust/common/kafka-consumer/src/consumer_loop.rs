//! The consumer loop: the event pump (doc §3.1).
//!
//! One task owns every domain struct by value. Its single await point is a
//! biased select whose order is the starvation proof: an arm can only starve
//! the arms below it, so shutdown, the housekeeping tick, and the rare
//! rebalance events sit on top, completions above the poll (drain before
//! taking new work), and the poll last.
//!
//! The poll arm is never disabled. Backpressure is rdkafka pause/resume on
//! the assignment: a paused consumer still serves rebalance callbacks and
//! keeps `max.poll.interval.ms` alive, an unpolled one does neither.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::FutureExt;
use metrics::{counter, gauge, histogram, Counter, Gauge, Histogram};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::{BorrowedMessage, Headers, Message};
use rdkafka::types::RDKafkaErrorCode;
use rdkafka::{ClientConfig, TopicPartitionList};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::accumulator::{Accumulator, GroupCompletion, PolledMessage};
use crate::charge::{Budget, Charge};
use crate::commit::CommitManager;
use crate::context::{LoopContext, RebalanceEvent};
use crate::events::Observer;
use crate::manager::PartitionManager;
use crate::metrics as names;
use crate::sentinel::CommitSentinel;
use crate::stats;
use crate::types::{AssignmentEpoch, Offset, Partition, RawMessage};

/// Everything the loop needs to build, with the defaults an adopter can
/// override field by field.
pub struct ConsumerLoopConfig {
    /// The built rdkafka client config, `group.id` included.
    pub client: ClientConfig,
    pub topic: String,
    /// The `B` cap: uncommitted events and bytes at which polling pauses.
    pub budget: Charge,
    /// The gate reopens at this fraction of the cap on both axes.
    pub budget_low_ratio: f64,
    /// A partition whose frontier does not move for this long while work is
    /// pending fails the loop.
    pub stall_timeout: Duration,
    /// At most one batched commit issue per interval.
    pub commit_interval: Duration,
    /// The housekeeping tick: the commit clock and the stall checks.
    pub tick_interval: Duration,
    /// Messages per poll, at most.
    pub poll_max_messages: usize,
    /// Charge bytes per poll, at most; `0` turns the bound off.
    pub poll_max_bytes: usize,
    /// Completion channel depth; keep it at or above the transport's pool
    /// size so completions never block a worker.
    pub completion_capacity: usize,
    /// Bound on the synchronous final commit at shutdown.
    pub shutdown_commit_timeout: Duration,
    /// How often the commit monitor fetches the broker's committed offsets.
    pub commit_monitor_interval: Duration,
}

impl ConsumerLoopConfig {
    pub fn new(client: ClientConfig, topic: impl Into<String>) -> ConsumerLoopConfig {
        ConsumerLoopConfig {
            client,
            topic: topic.into(),
            budget: Charge {
                events: 200_000,
                bytes: 512 << 20,
            },
            budget_low_ratio: Budget::DEFAULT_LOW_RATIO,
            stall_timeout: Duration::from_secs(120),
            commit_interval: Duration::from_secs(5),
            tick_interval: Duration::from_secs(1),
            poll_max_messages: 500,
            poll_max_bytes: 0,
            completion_capacity: 64,
            shutdown_commit_timeout: Duration::from_secs(10),
            commit_monitor_interval: Duration::from_secs(30),
        }
    }
}

/// What the loop sends down to the transport side.
#[derive(Debug)]
pub enum Feed {
    /// One poll's demuxed groups.
    Batch(Accumulator<RawMessage>),
    /// A drain has begun: drop the partition's queued work, settle what is
    /// in flight, then answer with `Completion::Drained` behind the last
    /// completion. Groups for the partition that arrive after this marker
    /// are never sent either.
    Revoked {
        partition: Partition,
        epoch: AssignmentEpoch,
    },
}

/// What the transport side sends back up.
#[derive(Debug)]
pub enum Completion {
    /// One ACKed request's groups, slim. Failures never cross the seam.
    Completed(Vec<GroupCompletion>),
    /// The drain's end for the `Revoked` marker carrying this epoch.
    Drained {
        partition: Partition,
        epoch: AssignmentEpoch,
    },
}

/// The transport side's ends of the two channels.
pub struct TransportHandle {
    pub feed: mpsc::UnboundedReceiver<Feed>,
    pub completions: mpsc::Sender<Completion>,
}

/// Why `run` returned. Every variant but `Stopped` means the process should
/// exit and replay from the last commit.
#[derive(Debug, thiserror::Error)]
pub enum ConsumerLoopError {
    #[error("kafka client error: {0}")]
    Kafka(#[from] KafkaError),
    #[error("fatal kafka client error ({code:?}): {reason}")]
    Fatal {
        code: RDKafkaErrorCode,
        reason: String,
    },
    #[error("partitions stalled: {0:?}")]
    Stalled(Vec<Partition>),
    #[error("the transport side closed its end of the seam")]
    TransportGone,
    #[error("a poll delivered partition {0}, which is not assigned")]
    UnassignedPartition(Partition),
}

/// A broker-driven revoke being drained: hand the whole set back once the
/// last partition in it drains.
struct HandBack {
    all: Vec<Partition>,
    remaining: HashSet<Partition>,
    since: Instant,
}

struct Meters {
    polls: Counter,
    messages_polled: Counter,
    bytes_polled: Counter,
    budget_used_events: Gauge,
    budget_used_bytes: Gauge,
    gate_closed: Gauge,
    gate_to_closed: Counter,
    gate_to_open: Counter,
    commits_issued: Counter,
    assigned_partitions: Gauge,
    rebalance_assign: Counter,
    rebalance_revoke: Counter,
    rebalance_lost: Counter,
    rebalance_error: Counter,
    drain_duration: Histogram,
    stalls: Counter,
    errors: Counter,
}

impl Meters {
    fn new(group: &str) -> Meters {
        let g = |name: &'static str| gauge!(name, names::GROUP_LABEL => group.to_string());
        let c = |name: &'static str| counter!(name, names::GROUP_LABEL => group.to_string());
        Meters {
            polls: c(names::POLLS_TOTAL),
            messages_polled: c(names::MESSAGES_POLLED_TOTAL),
            bytes_polled: c(names::BYTES_POLLED_TOTAL),
            budget_used_events: g(names::BUDGET_USED_EVENTS),
            budget_used_bytes: g(names::BUDGET_USED_BYTES),
            gate_closed: g(names::POLL_GATE_CLOSED),
            gate_to_closed: counter!(names::POLL_GATE_TRANSITIONS_TOTAL, names::GROUP_LABEL => group.to_string(), "to" => "closed"),
            gate_to_open: counter!(names::POLL_GATE_TRANSITIONS_TOTAL, names::GROUP_LABEL => group.to_string(), "to" => "open"),
            commits_issued: c(names::COMMITS_ISSUED_TOTAL),
            assigned_partitions: g(names::ASSIGNED_PARTITIONS),
            rebalance_assign: counter!(names::REBALANCES_TOTAL, names::GROUP_LABEL => group.to_string(), "event" => "assign"),
            rebalance_revoke: counter!(names::REBALANCES_TOTAL, names::GROUP_LABEL => group.to_string(), "event" => "revoke"),
            rebalance_lost: counter!(names::REBALANCES_TOTAL, names::GROUP_LABEL => group.to_string(), "event" => "lost"),
            rebalance_error: counter!(names::REBALANCES_TOTAL, names::GROUP_LABEL => group.to_string(), "event" => "error"),
            drain_duration: histogram!(names::DRAIN_DURATION_SECONDS, names::GROUP_LABEL => group.to_string()),
            stalls: c(names::STALLS_TOTAL),
            errors: c(names::ERRORS_TOTAL),
        }
    }
}

/// The event pump. Owns the domain side and the seam's loop-side ends.
pub struct ConsumerLoop<O: Observer> {
    consumer: Arc<StreamConsumer<LoopContext>>,
    topic: String,
    group: String,
    partitions: PartitionManager,
    budget: Budget,
    commits: CommitManager,
    sentinel: Arc<CommitSentinel>,
    rebalances: mpsc::UnboundedReceiver<RebalanceEvent>,
    closing: Arc<AtomicBool>,
    epoch: Arc<AtomicU64>,
    feed: mpsc::UnboundedSender<Feed>,
    completions: mpsc::Receiver<Completion>,
    observer: O,
    meters: Meters,
    poll_max_messages: usize,
    poll_max_bytes: usize,
    tick_interval: Duration,
    shutdown_commit_timeout: Duration,
    commit_monitor_interval: Duration,
    /// The assignment is paused (the gate is closed).
    paused: bool,
    shutting_down: bool,
    hand_back: Option<HandBack>,
}

impl<O: Observer> ConsumerLoop<O> {
    /// Create the rdkafka client and the seam's channels. Nothing is polled
    /// or subscribed until `run`.
    pub fn build(
        config: ConsumerLoopConfig,
        observer: O,
    ) -> Result<(ConsumerLoop<O>, TransportHandle), ConsumerLoopError> {
        let group = config
            .client
            .get("group.id")
            .unwrap_or_default()
            .to_string();
        let (rebalance_tx, rebalance_rx) = mpsc::unbounded_channel();
        let closing = Arc::new(AtomicBool::new(false));
        let epoch = Arc::new(AtomicU64::new(0));
        let context = LoopContext::new(rebalance_tx, Arc::clone(&closing), Arc::clone(&epoch));
        let consumer: StreamConsumer<LoopContext> = config.client.create_with_context(context)?;
        stats::export_limits(
            &config.client,
            config.poll_max_messages,
            config.poll_max_bytes,
        );

        let (feed_tx, feed_rx) = mpsc::unbounded_channel();
        let (completion_tx, completion_rx) = mpsc::channel(config.completion_capacity.max(1));

        let consumer_loop = ConsumerLoop {
            consumer: Arc::new(consumer),
            topic: config.topic,
            meters: Meters::new(&group),
            sentinel: Arc::new(CommitSentinel::new(group.clone())),
            group,
            partitions: PartitionManager::new(config.stall_timeout),
            budget: Budget::with_low_ratio(config.budget, config.budget_low_ratio),
            commits: CommitManager::new(config.commit_interval),
            rebalances: rebalance_rx,
            closing,
            epoch,
            feed: feed_tx,
            completions: completion_rx,
            observer,
            poll_max_messages: config.poll_max_messages.max(1),
            poll_max_bytes: config.poll_max_bytes,
            tick_interval: config.tick_interval,
            shutdown_commit_timeout: config.shutdown_commit_timeout,
            commit_monitor_interval: config.commit_monitor_interval,
            paused: false,
            shutting_down: false,
            hand_back: None,
        };
        Ok((
            consumer_loop,
            TransportHandle {
                feed: feed_rx,
                completions: completion_tx,
            },
        ))
    }

    pub fn sentinel(&self) -> Arc<CommitSentinel> {
        Arc::clone(&self.sentinel)
    }

    /// The assignment epoch counter, bumped on every assignment. Share it
    /// with the transport side so requests carry the same epoch the groups
    /// do; there must be one counter per process, not one per component.
    pub fn epoch_counter(&self) -> Arc<AtomicU64> {
        Arc::clone(&self.epoch)
    }

    /// Subscribe and pump until `shutdown` fires and the assignment has
    /// drained, or until a fatal condition. Start this only once the
    /// transport side can route: stall deadlines start at assignment.
    pub async fn run(mut self, shutdown: CancellationToken) -> Result<(), ConsumerLoopError> {
        self.consumer.subscribe(&[&self.topic])?;
        self.observer.started(&self.group, &self.topic);
        info!(group = %self.group, topic = %self.topic, "Consumer loop starting");

        let monitor = AbortOnDrop(tokio::spawn(commit_monitor(
            Arc::clone(&self.consumer),
            Arc::clone(&self.sentinel),
            self.topic.clone(),
            self.group.clone(),
            self.commit_monitor_interval,
        )));

        let mut tick = tokio::time::interval(self.tick_interval);
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

        let result = loop {
            self.observer.alive();
            if self.shutting_down && self.partitions.is_empty() {
                break Ok(());
            }
            let step = tokio::select! {
                biased;
                _ = shutdown.cancelled(), if !self.shutting_down => {
                    self.begin_shutdown();
                    Ok(())
                }
                _ = tick.tick() => self.on_tick(),
                event = self.rebalances.recv() => match event {
                    Some(event) => self.on_rebalance(event),
                    // The context holds the sender for as long as the
                    // consumer lives, and the consumer lives in `self`.
                    None => Ok(()),
                },
                completion = self.completions.recv() => match completion {
                    Some(completion) => self.on_completion(completion),
                    None => Err(ConsumerLoopError::TransportGone),
                },
                polled = recv_owned(&self.consumer, &self.topic) => self.on_polled(polled),
            };
            if let Err(err) = step {
                break Err(err);
            }
        };

        drop(monitor);
        match result {
            Ok(()) => {
                info!(group = %self.group, "Consumer loop drained; committing and leaving");
                self.close().await;
                Ok(())
            }
            Err(err) => {
                self.closing.store(true, Ordering::SeqCst);
                let consumer = Arc::clone(&self.consumer);
                drop(self);
                drop(tokio::task::spawn_blocking(move || drop(consumer)).await);
                Err(err)
            }
        }
    }

    // ---- arms ----

    fn begin_shutdown(&mut self) {
        self.shutting_down = true;
        // From here every broker revoke is answered inline (see `context`).
        self.closing.store(true, Ordering::SeqCst);
        let assigned = self.partitions.assigned();
        info!(
            partitions = assigned.len(),
            "Shutdown: draining the assignment"
        );
        self.pause_all();
        for p in assigned {
            if self.partitions.is_revoking(p) {
                continue;
            }
            self.begin_drain(p);
        }
    }

    fn on_tick(&mut self) -> Result<(), ConsumerLoopError> {
        let now = Instant::now();
        let refund = {
            let mut issue = issuer(
                &self.consumer,
                &self.sentinel,
                &self.topic,
                &self.meters,
                &self.observer,
            );
            self.commits.tick(now, &mut issue)
        };
        self.budget.refund(refund);
        self.apply_gate();

        // Keep librdkafka's `max.poll.interval.ms` clock moving while the
        // assignment is paused and nothing wakes the poll arm.
        if let Some(polled) = recv_owned(&self.consumer, &self.topic).now_or_never() {
            self.on_polled(polled)?;
        }

        let stalled = self.partitions.stalled(now);
        if !stalled.is_empty() {
            self.meters.stalls.increment(1);
            self.observer.stalled(&stalled);
            return Err(ConsumerLoopError::Stalled(stalled));
        }
        Ok(())
    }

    fn on_rebalance(&mut self, event: RebalanceEvent) -> Result<(), ConsumerLoopError> {
        match event {
            RebalanceEvent::Assigned { partitions, epoch } => self.on_assigned(partitions, epoch),
            RebalanceEvent::Revoked {
                partitions,
                lost,
                handed_back,
            } => self.on_revoked(partitions, lost, handed_back),
            RebalanceEvent::Error(err) => {
                warn!(error = %err, "Rebalance error; abandoning the assignment");
                self.meters.rebalance_error.increment(1);
                let all = self.partitions.assigned();
                self.abandon(&all);
                self.hand_back = None;
            }
        }
        self.meters
            .assigned_partitions
            .set(self.partitions.len() as f64);
        Ok(())
    }

    fn on_assigned(&mut self, partitions: Vec<Partition>, epoch: AssignmentEpoch) {
        let now = Instant::now();
        self.meters.rebalance_assign.increment(1);
        let mut fresh = Vec::with_capacity(partitions.len());
        for p in partitions {
            if self.partitions.is_assigned(p) {
                warn!(
                    partition = p.0,
                    "Assigned a partition already held; ignoring"
                );
                continue;
            }
            self.partitions.assign(p, epoch, now);
            fresh.push(p);
        }
        info!(partitions = ?fresh, epoch = epoch.0, "Partitions assigned");
        if self.paused || self.shutting_down {
            // Assignment resets rdkafka's pause flags: keep the gate honest.
            self.pause(&fresh);
        }
        if self.shutting_down {
            for p in fresh.iter().copied() {
                self.begin_drain(p);
            }
        }
        self.observer.assigned(&fresh, epoch);
    }

    fn on_revoked(&mut self, partitions: Vec<Partition>, lost: bool, handed_back: bool) {
        if lost {
            self.meters.rebalance_lost.increment(1);
        } else {
            self.meters.rebalance_revoke.increment(1);
        }
        info!(partitions = ?partitions, lost, handed_back, "Partitions revoked");
        self.sentinel.forget(partitions.iter().copied());
        self.observer.revoked(&partitions, lost);

        if handed_back {
            // Already gone at the broker (lost) or answered inline (closing):
            // no final commit is possible, so drop the drivers now.
            self.abandon(&partitions);
            if lost {
                self.hand_back = None;
            }
            return;
        }

        let now = Instant::now();
        let hand_back = self.hand_back.get_or_insert_with(|| HandBack {
            all: Vec::new(),
            remaining: HashSet::new(),
            since: now,
        });
        for p in partitions.iter().copied() {
            hand_back.all.push(p);
            hand_back.remaining.insert(p);
        }
        for p in partitions {
            if self.partitions.is_assigned(p) && !self.partitions.is_revoking(p) {
                self.begin_drain(p);
            } else if !self.partitions.is_assigned(p) {
                // Nothing to drain: count it as already drained.
                self.hand_back.as_mut().map(|h| h.remaining.remove(&p));
            }
        }
        self.maybe_hand_back();
    }

    fn on_completion(&mut self, completion: Completion) -> Result<(), ConsumerLoopError> {
        let now = Instant::now();
        match completion {
            Completion::Completed(groups) => {
                let advances = self.partitions.complete(groups, now);
                let refund = {
                    let mut issue = issuer(
                        &self.consumer,
                        &self.sentinel,
                        &self.topic,
                        &self.meters,
                        &self.observer,
                    );
                    self.commits.progress(advances, now, &mut issue)
                };
                self.budget.refund(refund);
            }
            Completion::Drained { partition, epoch } => {
                if self.partitions.epoch(partition) != Some(epoch) {
                    info!(
                        partition = partition.0,
                        epoch = epoch.0,
                        "Drained marker for a partition no longer held at that epoch; ignoring"
                    );
                    return Ok(());
                }
                let harvest = self.partitions.drained(partition);
                let refund = {
                    let mut issue = issuer(
                        &self.consumer,
                        &self.sentinel,
                        &self.topic,
                        &self.meters,
                        &self.observer,
                    );
                    self.commits.finish_revoke(harvest, now, &mut issue)
                };
                self.budget.refund(refund);
                self.observer.drained(&harvest, true);
                if let Some(hand_back) = &mut self.hand_back {
                    hand_back.remaining.remove(&partition);
                }
                self.maybe_hand_back();
                self.meters
                    .assigned_partitions
                    .set(self.partitions.len() as f64);
            }
        }
        self.apply_gate();
        Ok(())
    }

    fn on_polled(
        &mut self,
        first: Result<Option<Polled>, KafkaError>,
    ) -> Result<(), ConsumerLoopError> {
        let mut poll = PollBatch::default();
        match first {
            Ok(Some(polled)) => poll.push(polled),
            Ok(None) => {}
            Err(err) => return self.on_recv_error(err),
        }
        // Drain what is ready now, bounded; no linger, the transport paces.
        while poll.count < self.poll_max_messages
            && (self.poll_max_bytes == 0 || poll.bytes < self.poll_max_bytes)
        {
            match recv_owned(&self.consumer, &self.topic).now_or_never() {
                Some(Ok(Some(polled))) => poll.push(polled),
                Some(Ok(None)) => continue,
                Some(Err(err)) => {
                    self.on_recv_error(err)?;
                    break;
                }
                None => break,
            }
        }
        let count = poll.count;
        let batch = poll.batch;

        // The callback may have fired during collection. Assignments apply
        // now (their messages may be in this poll); revokes apply after this
        // batch is released, so the marker rides behind it.
        let mut deferred = Vec::new();
        while let Ok(event) = self.rebalances.try_recv() {
            match event {
                RebalanceEvent::Assigned { partitions, epoch } => {
                    self.on_assigned(partitions, epoch)
                }
                other => deferred.push(other),
            }
        }

        if count > 0 {
            for (p, _) in &batch {
                if !self.partitions.is_assigned(*p) {
                    return Err(ConsumerLoopError::UnassignedPartition(*p));
                }
            }
            let mut acc = Accumulator::default();
            let charge = self.partitions.accept(batch, &mut acc);
            self.budget.charge(charge);
            self.meters.polls.increment(1);
            self.meters.messages_polled.increment(charge.events);
            self.meters.bytes_polled.increment(charge.bytes);
            self.observer.poll_accepted(count, charge);
            if self.feed.send(Feed::Batch(acc)).is_err() {
                return Err(ConsumerLoopError::TransportGone);
            }
            self.apply_gate();
        }

        for event in deferred {
            self.on_rebalance(event)?;
        }
        Ok(())
    }

    fn on_recv_error(&mut self, err: KafkaError) -> Result<(), ConsumerLoopError> {
        if let KafkaError::PartitionEOF(_) = err {
            return Ok(());
        }
        if let KafkaError::MessageConsumptionFatal(code) = err {
            let reason = self
                .consumer
                .client()
                .fatal_error()
                .map(|(_, reason)| reason)
                .unwrap_or_default();
            return Err(ConsumerLoopError::Fatal { code, reason });
        }
        // A fatal client error (such as UnreleasedInstanceId from a
        // static-membership collision) permanently disables the consumer;
        // exit so the process restarts instead of re-polling a dead client.
        if let Some((code, reason)) = self.consumer.client().fatal_error() {
            return Err(ConsumerLoopError::Fatal { code, reason });
        }
        warn!(error = %err, "Kafka recv error");
        self.meters.errors.increment(1);
        Ok(())
    }

    // ---- helpers ----

    /// Mark the partition revoking and send the in-band marker.
    fn begin_drain(&mut self, p: Partition) {
        let Some(epoch) = self.partitions.epoch(p) else {
            return;
        };
        self.partitions.revoking(p);
        drop(self.feed.send(Feed::Revoked {
            partition: p,
            epoch,
        }));
    }

    /// Drop the drivers without a final commit and refund everything they
    /// held. The marker still goes down so the transport clears its queues;
    /// the `Drained` it answers with dies by epoch.
    fn abandon(&mut self, partitions: &[Partition]) {
        for p in partitions.iter().copied() {
            if !self.partitions.is_assigned(p) {
                continue;
            }
            if !self.partitions.is_revoking(p) {
                self.begin_drain(p);
            }
            let harvest = self.partitions.drained(p);
            let refund = self.commits.abandon(harvest);
            self.budget.refund(refund);
            self.observer.drained(&harvest, false);
        }
        self.apply_gate();
    }

    /// Hand the revoke set back once every partition in it has drained.
    fn maybe_hand_back(&mut self) {
        let Some(hand_back) = &self.hand_back else {
            return;
        };
        if !hand_back.remaining.is_empty() {
            return;
        }
        let hand_back = self.hand_back.take().expect("checked above");
        let tpl = self.tpl(hand_back.all.iter().copied());
        if let Err(err) = self.consumer.incremental_unassign(&tpl) {
            warn!(error = %err, partitions = ?hand_back.all, "incremental_unassign failed");
        }
        let elapsed = hand_back.since.elapsed();
        self.meters.drain_duration.record(elapsed.as_secs_f64());
        info!(partitions = ?hand_back.all, elapsed = ?elapsed, "Partitions handed back");
    }

    fn apply_gate(&mut self) {
        let used = self.budget.used();
        self.meters.budget_used_events.set(used.events as f64);
        self.meters.budget_used_bytes.set(used.bytes as f64);
        if self.shutting_down {
            return;
        }
        let open = self.budget.gate_open();
        if open && self.paused {
            self.resume_all();
            self.meters.gate_to_open.increment(1);
            self.observer.gate_closed(false, used);
        } else if !open && !self.paused {
            self.pause_all();
            self.meters.gate_to_closed.increment(1);
            self.observer.gate_closed(true, used);
        }
    }

    fn pause_all(&mut self) {
        let assigned = self.partitions.assigned();
        self.pause(&assigned);
        self.paused = true;
        self.meters.gate_closed.set(1.0);
    }

    fn pause(&self, partitions: &[Partition]) {
        if partitions.is_empty() {
            return;
        }
        if let Err(err) = self.consumer.pause(&self.tpl(partitions.iter().copied())) {
            warn!(error = %err, "pause failed");
        }
    }

    fn resume_all(&mut self) {
        let assigned = self.partitions.assigned();
        if !assigned.is_empty() {
            if let Err(err) = self.consumer.resume(&self.tpl(assigned.into_iter())) {
                warn!(error = %err, "resume failed");
            }
        }
        self.paused = false;
        self.meters.gate_closed.set(0.0);
    }

    fn tpl(&self, partitions: impl Iterator<Item = Partition>) -> TopicPartitionList {
        let mut tpl = TopicPartitionList::new();
        for p in partitions {
            tpl.add_partition(&self.topic, p.0);
        }
        tpl
    }

    /// The end of a clean shutdown: re-submit every attempted offset
    /// synchronously so the commits are known to have landed, then close.
    async fn close(self) {
        let attempted = self.sentinel.attempted();
        let consumer = Arc::clone(&self.consumer);
        let topic = self.topic.clone();
        let timeout = self.shutdown_commit_timeout;
        if !attempted.is_empty() {
            let final_commit = tokio::task::spawn_blocking(move || {
                let mut tpl = TopicPartitionList::new();
                for (p, o) in &attempted {
                    drop(tpl.add_partition_offset(&topic, p.0, rdkafka::Offset::Offset(o.0)));
                }
                consumer.commit(&tpl, CommitMode::Sync)
            });
            match tokio::time::timeout(timeout, final_commit).await {
                Ok(Ok(Ok(()))) => info!("Final commit landed"),
                Ok(Ok(Err(err))) => warn!(error = %err, "Final commit failed"),
                Ok(Err(err)) => warn!(error = %err, "Final commit task failed"),
                Err(_) => warn!("Final commit timed out"),
            }
        }
        let consumer = Arc::clone(&self.consumer);
        drop(self);
        // rdkafka's Drop runs consumer_close and polls until it completes.
        drop(tokio::task::spawn_blocking(move || drop(consumer)).await);
    }
}

impl<O: Observer> Drop for ConsumerLoop<O> {
    /// A cancelled `run` drops the consumer without reaching `close`; the
    /// close-time revoke must still be answered inline or the drop spins.
    fn drop(&mut self) {
        self.closing.store(true, Ordering::SeqCst);
    }
}

/// One polled message in the loop's own terms.
struct Polled {
    partition: Partition,
    message: PolledMessage<RawMessage>,
}

/// One poll under collection: messages grouped per partition in delivery
/// order, as the manager's `accept` wants them.
#[derive(Default)]
struct PollBatch {
    batch: Vec<(Partition, Vec<PolledMessage<RawMessage>>)>,
    index: HashMap<Partition, usize>,
    count: usize,
    bytes: usize,
}

impl PollBatch {
    fn push(&mut self, polled: Polled) {
        self.count += 1;
        self.bytes += polled.message.charge.bytes as usize;
        let slot = *self.index.entry(polled.partition).or_insert_with(|| {
            self.batch.push((polled.partition, Vec::new()));
            self.batch.len() - 1
        });
        self.batch[slot].1.push(polled.message);
    }
}

/// Await one message and hand it over owned, so the arm's output borrows
/// nothing from the consumer. `Ok(None)` is a message on another topic.
async fn recv_owned(
    consumer: &StreamConsumer<LoopContext>,
    topic: &str,
) -> Result<Option<Polled>, KafkaError> {
    let message = consumer.recv().await?;
    Ok(owned(&message, topic))
}

fn owned(message: &BorrowedMessage<'_>, topic: &str) -> Option<Polled> {
    if message.topic() != topic {
        warn!(
            topic = message.topic(),
            "Message on an unsubscribed topic; ignoring"
        );
        return None;
    }
    let key = message.key().map(<[u8]>::to_vec);
    let payload = message.payload().map(<[u8]>::to_vec).unwrap_or_default();
    let mut headers = Vec::new();
    let mut header_bytes = 0usize;
    if let Some(borrowed) = message.headers() {
        headers.reserve(borrowed.count());
        for i in 0..borrowed.count() {
            let header = borrowed.get(i);
            let value = header.value.map(<[u8]>::to_vec).unwrap_or_default();
            header_bytes += header.key.len() + value.len();
            headers.push((header.key.to_string(), value));
        }
    }
    let bytes = payload.len() + key.as_ref().map_or(0, Vec::len) + header_bytes;
    let partition = Partition(message.partition());
    let offset = Offset(message.offset());
    Some(Polled {
        partition,
        message: PolledMessage {
            offset,
            key,
            charge: Charge {
                events: 1,
                bytes: bytes as u64,
            },
            inner: RawMessage {
                partition,
                offset,
                timestamp_ms: message.timestamp().to_millis(),
                payload,
                headers,
            },
        },
    })
}

/// The injected commit issue: async, fire-and-forget, never blocks the loop.
fn issuer<'a, O: Observer>(
    consumer: &'a StreamConsumer<LoopContext>,
    sentinel: &'a CommitSentinel,
    topic: &'a str,
    meters: &'a Meters,
    observer: &'a O,
) -> impl FnMut(&[(Partition, Offset)]) + 'a {
    move |batch: &[(Partition, Offset)]| {
        let mut tpl = TopicPartitionList::new();
        for (p, o) in batch {
            drop(tpl.add_partition_offset(topic, p.0, rdkafka::Offset::Offset(o.0)));
        }
        sentinel.check_issue(batch);
        match consumer.commit(&tpl, CommitMode::Async) {
            Ok(()) => meters.commits_issued.increment(1),
            Err(err) => {
                warn!(error = %err, "Commit issue failed");
                meters.errors.increment(1);
            }
        }
        observer.committed(batch);
    }
}

/// Periodically fetch the broker's committed offsets for the current
/// assignment (an OffsetFetch round trip) and feed them to the sentinel.
async fn commit_monitor(
    consumer: Arc<StreamConsumer<LoopContext>>,
    sentinel: Arc<CommitSentinel>,
    topic: String,
    group: String,
    interval: Duration,
) {
    loop {
        tokio::time::sleep(interval).await;
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
                let observed: Vec<(Partition, Offset)> = committed
                    .elements()
                    .iter()
                    .filter(|e| e.topic() == topic)
                    .filter_map(|e| match e.offset() {
                        rdkafka::Offset::Offset(offset) => {
                            Some((Partition(e.partition()), Offset(offset)))
                        }
                        // Invalid = no offset stored for the partition yet.
                        _ => None,
                    })
                    .collect();
                sentinel.observe_broker_committed(observed);
            }
            Ok(Ok(None)) => {}
            Ok(Err(err)) => {
                counter!(names::COMMIT_MONITOR_ERRORS_TOTAL, names::GROUP_LABEL => group.clone())
                    .increment(1);
                warn!(error = %err, "Commit monitor failed to fetch committed offsets");
            }
            Err(err) => {
                counter!(names::COMMIT_MONITOR_ERRORS_TOTAL, names::GROUP_LABEL => group.clone())
                    .increment(1);
                warn!(error = %err, "Commit monitor task join error");
            }
        }
    }
}

/// Aborts the wrapped task when dropped.
struct AbortOnDrop(JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}
