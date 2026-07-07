//! Pipelined consume → filter → re-key → produce loop for `clickhouse_events_json`.
//!
//! Drops events with no `person_id`, skips teams with no realtime cohorts, then re-keys the
//! survivors by `(team_id, person_id)` to match the Node CDP precalculated-filters gating.
//!
//! Consume, produce-ack, and offset-commit are decoupled: the single owner task enqueues
//! survivors without awaiting delivery, resolves acks as they arrive, and periodically commits
//! the [`Ledger`]'s per-partition watermarks through `spawn_blocking`, so WarpStream's
//! ~250–500ms produce acks never throttle consumption.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use common_types::ClickHouseEvent;
use futures::stream::FuturesUnordered;
use futures::StreamExt;
use lifecycle::Handle;
use metrics::{counter, gauge, histogram};
use rdkafka::error::KafkaError;
use serde::{de::IgnoredAny, Deserialize};
use tokio::task::JoinError;
use tracing::{debug, error, info, warn};

use crate::event::CohortStreamEvent;
use crate::filter_team_index::TeamIndex;
use crate::ledger::{
    DeliveryOutcome, Ledger, NextOffset, Observation, Resolution, SourceOffset, SourcePartition,
};
use crate::observability::metrics::{
    COMMITS, COMMIT_ERRORS, EVENTS_ABANDONED, EVENTS_CONSUMED, EVENTS_DROPPED_NO_PERSON_ID,
    EVENTS_FORWARDED, EVENTS_SKIPPED_TEAM_GATE, EVENTS_UNPARSEABLE, FORWARDS_ENQUEUED,
    FORWARDS_INFLIGHT, LEDGER_PARTITIONS, PRODUCE_ACK_SECONDS, PRODUCE_ERRORS, PRODUCE_QUEUE_FULL,
    UNCOMMITTED_EVENTS,
};
use crate::producer::{CohortStreamProducer, EnqueueError};

/// Bounds the idle select wait so every loop iteration (and thus the liveness heartbeat) happens
/// at least this often on a quiet topic.
const RECV_TIMEOUT: Duration = Duration::from_millis(500);
const QUEUE_FULL_BACKOFF_CAP: Duration = Duration::from_secs(2);
/// Intake pause after a kafka-level recv error, so a persistently erroring consumer doesn't
/// hot-loop.
const RECV_ERROR_BACKOFF: Duration = Duration::from_secs(1);
/// No successful commit for this many intervals while committable work exists ⇒ stop
/// heartbeating so the stall detector restarts the pod.
const COMMIT_STALENESS_FACTOR: u32 = 3;
/// Every step of the shutdown drain shares this one budget, sized inside the consumer's 15s
/// graceful window with slack for process-exit overhead.
const SHUTDOWN_DRAIN_BUDGET: Duration = Duration::from_secs(14);
/// librdkafka-internal bound on the shutdown flush; the shared budget applies on top.
const SHUTDOWN_FLUSH_TIMEOUT: Duration = Duration::from_secs(5);
/// Slice of the shared budget reserved for the final Sync commit — the step that turns drained
/// work into committed progress must not be starved by a slow flush or ack drain.
const SHUTDOWN_COMMIT_TIMEOUT: Duration = Duration::from_secs(4);

/// Only the fields the team gate needs. Every undeclared field (notably the large
/// `properties` / `person_properties` / `groupN_properties` JSON-string blobs) is skipped by
/// `serde_json` without unescaping or allocating, instead of being materialized.
#[derive(Deserialize)]
struct GateFields {
    team_id: i32,
    /// `IgnoredAny` detects presence without allocating the value: absent and `null` deserialize to
    /// `None`, any present non-null value to `Some`.
    #[serde(default)]
    person_id: Option<IgnoredAny>,
}

#[derive(Debug, PartialEq, Eq)]
enum GateOutcome {
    Forward,
    DropNoPersonId,
    SkipTeamGate,
}

/// `person_id` is checked first: a missing routing key is attributed to `DropNoPersonId` even when
/// the team would also be skipped.
fn classify_gate(gate: &GateFields, team_index: &TeamIndex) -> GateOutcome {
    if gate.person_id.is_none() {
        return GateOutcome::DropNoPersonId;
    }
    if !team_index.contains(gate.team_id) {
        return GateOutcome::SkipTeamGate;
    }
    GateOutcome::Forward
}

/// `event` is boxed to keep the enum small: `Forward` is the only large variant and is built only
/// for survivors.
#[derive(Debug)]
enum Decoded {
    Forward {
        event: Box<ClickHouseEvent>,
        person_id: String,
    },
    DropNoPersonId,
    SkipTeamGate,
    /// Serde failure at either phase — counted and settled, never an `Err`. Infallibility matters:
    /// `recv_with` auto-stores offsets on decode errors, and a stored poison-pill offset could be
    /// committed past unacked forwards by an auto-commit path. With this variant the decode-error
    /// auto-store is unreachable; only the empty-payload branch still auto-stores, and stored
    /// offsets stay inert because auto-commit is off (see `Config::build_consumer_config`). The
    /// ledger owns every observed offset.
    Unparseable,
}

/// Cheap gate parse for every event; a full `ClickHouseEvent` parse only for survivors, over the
/// same bytes so forwarded envelopes are byte-identical to a single-parse path.
fn decode_gated(payload: &[u8], team_index: &TeamIndex) -> Decoded {
    let Ok(gate) = serde_json::from_slice::<GateFields>(payload) else {
        return Decoded::Unparseable;
    };
    match classify_gate(&gate, team_index) {
        GateOutcome::DropNoPersonId => Decoded::DropNoPersonId,
        GateOutcome::SkipTeamGate => Decoded::SkipTeamGate,
        GateOutcome::Forward => {
            let Ok(mut event) = serde_json::from_slice::<ClickHouseEvent>(payload) else {
                return Decoded::Unparseable;
            };
            let Some(person_id) = event.person_id.take() else {
                // Unreachable: the gate saw a present non-null person_id, and a non-string one would
                // have failed the full parse above. Fail safe instead of panicking.
                warn!("gate-forwarded event had no person_id after full parse; dropping");
                return Decoded::DropNoPersonId;
            };
            Decoded::Forward {
                event: Box::new(event),
                person_id,
            }
        }
    }
}

/// Resolved delivery of one forwarded event, carried back to the pipeline task by an
/// [`AckFuture`]. Named (not a bare tuple) so each destructuring site reads by field instead of
/// re-establishing what each position means.
struct DeliveryAck {
    partition: SourcePartition,
    offset: SourceOffset,
    sent_at: Instant,
    result: Result<(), KafkaError>,
}

type AckFuture = Pin<Box<dyn Future<Output = DeliveryAck> + Send>>;
type CommitResult = Result<Result<(), KafkaError>, JoinError>;
type CommitFuture =
    Pin<Box<dyn Future<Output = (Vec<(SourcePartition, NextOffset)>, CommitResult)> + Send>>;

#[derive(Debug, Clone, Copy)]
pub struct ShufflerSettings {
    pub max_inflight_forwards: usize,
    pub commit_interval: Duration,
    pub queue_full_backoff: Duration,
}

/// A gate survivor whose enqueue hit `QueueFull`, parked until the producer queue drains. Its
/// offset is not observed by the ledger until the enqueue lands, so a crash while parked simply
/// replays it.
struct PendingForward {
    event: CohortStreamEvent,
    partition: SourcePartition,
    offset: SourceOffset,
}

/// Whether the recv arm may consume. Pausing is a hard ordering gate — a parked survivor must
/// reach the producer before any newer event for the same `(team, person)` — but only intake
/// stops: acks, commits, shutdown, and the liveness heartbeat keep flowing because the loop
/// itself never sleeps.
enum Intake {
    Open,
    /// `QueueFull`: re-enqueue the parked forward at `resume_at`, doubling `backoff` (capped)
    /// on each further failure. Boxed to keep the always-carried `Open` variant word-sized.
    RetryForward {
        forward: Box<PendingForward>,
        resume_at: tokio::time::Instant,
        backoff: Duration,
    },
    /// Transient kafka-level recv error; resume consuming at `resume_at`.
    Backoff {
        resume_at: tokio::time::Instant,
    },
}

impl Intake {
    fn is_open(&self) -> bool {
        matches!(self, Intake::Open)
    }

    /// Only meaningful when paused; the select arm awaiting this is guarded on `!is_open()`.
    fn resume_at(&self) -> tokio::time::Instant {
        match self {
            Intake::Open => tokio::time::Instant::now(),
            Intake::RetryForward { resume_at, .. } | Intake::Backoff { resume_at } => *resume_at,
        }
    }
}

pub struct EventShuffler {
    consumer: SingleTopicConsumer,
    producer: CohortStreamProducer,
    team_index: Arc<TeamIndex>,
    handle: Handle,
    settings: ShufflerSettings,
}

impl EventShuffler {
    pub fn new(
        consumer: SingleTopicConsumer,
        producer: CohortStreamProducer,
        team_index: Arc<TeamIndex>,
        handle: Handle,
        settings: ShufflerSettings,
    ) -> Self {
        Self {
            consumer,
            producer,
            team_index,
            handle,
            settings,
        }
    }

    /// The single pipeline task: owns the consumer, producer, [`Ledger`], [`Intake`] gate,
    /// pending ack futures, and the one-slot commit task. Backpressure is the recv guard — at
    /// the in-flight cap or while intake is paused the recv arm is disabled but acks and commits
    /// keep draining, and every `DeliveryFuture` resolves within `message.timeout.ms` regardless
    /// of broker state, so the loop cannot deadlock and never stops heartbeating on its own.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!("shuffler pipeline starting");

        let mut ledger = Ledger::default();
        let mut pending_acks: FuturesUnordered<AckFuture> = FuturesUnordered::new();
        let mut pending_commit: FuturesUnordered<CommitFuture> = FuturesUnordered::new();
        let mut intake = Intake::Open;
        let mut commit_in_flight = false;
        let mut commit_tick = tokio::time::interval(self.settings.commit_interval);
        commit_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let staleness_threshold = self.settings.commit_interval * COMMIT_STALENESS_FACTOR;
        let mut last_commit_ok = Instant::now();

        loop {
            tokio::select! {
                biased;

                _ = self.handle.shutdown_recv() => {
                    info!("shutdown signal received, stopping intake");
                    break;
                }

                Some(ack) = pending_acks.next() => {
                    record_delivery(&mut ledger, ack);
                }

                Some((offsets, result)) = pending_commit.next() => {
                    commit_in_flight = false;
                    if apply_commit_result(&mut ledger, offsets, result) {
                        last_commit_ok = Instant::now();
                    }
                }

                _ = commit_tick.tick(), if !commit_in_flight => {
                    if let Some(commit) = self.start_commit(&mut ledger) {
                        pending_commit.push(commit);
                        commit_in_flight = true;
                    }
                }

                _ = tokio::time::sleep_until(intake.resume_at()), if !intake.is_open() => {
                    intake = match std::mem::replace(&mut intake, Intake::Open) {
                        Intake::RetryForward { forward, backoff, .. } => {
                            self.try_enqueue(forward, backoff, &mut ledger, &mut pending_acks)
                        }
                        Intake::Open | Intake::Backoff { .. } => Intake::Open,
                    };
                }

                // Fail-closed until the team index loads once: don't consume — and advance
                // offsets past — events while the gate would forward nothing.
                recv = tokio::time::timeout(
                    RECV_TIMEOUT,
                    self.consumer.recv_with(|payload| Ok(decode_gated(payload, &self.team_index))),
                ), if intake.is_open()
                    && ledger.in_flight() < self.settings.max_inflight_forwards
                    && self.team_index.is_loaded() =>
                {
                    match recv {
                        Ok(Ok((decoded, offset))) => {
                            intake = self.intake(&mut ledger, &mut pending_acks, decoded, &offset);
                        }
                        Ok(Err(err)) => match err {
                            // Auto-stored by recv_with, but inert: this loop never commits
                            // stored offsets, only explicit ledger watermarks. Worst case at a
                            // partition tail: commit stays one message short → one-message
                            // replay on restart.
                            RecvErr::Empty => debug!("skipped message with empty payload"),
                            RecvErr::Serde(e) => {
                                warn!(error = %e, "unreachable: infallible decode reported serde error");
                            }
                            RecvErr::Kafka(e) => {
                                warn!(error = %e, "kafka recv error; pausing intake");
                                intake = Intake::Backoff {
                                    resume_at: tokio::time::Instant::now() + RECV_ERROR_BACKOFF,
                                };
                            }
                        },
                        Err(_elapsed) => {} // idle poll; heartbeat below keeps liveness fresh
                    }
                }
            }

            // Heartbeat gated by commit freshness: a wedged committer with committable work must
            // trip the stall detector, but an idle topic (nothing to commit) stays healthy.
            let commit_is_stale = last_commit_ok.elapsed() > staleness_threshold;
            if should_heartbeat(commit_is_stale, ledger.has_committable()) {
                self.handle.report_healthy();
            }
        }

        self.drain_and_commit(ledger, pending_acks, pending_commit, intake)
            .await;
        info!("shuffler pipeline stopped");
    }

    fn intake(
        &self,
        ledger: &mut Ledger,
        pending_acks: &mut FuturesUnordered<AckFuture>,
        decoded: Decoded,
        offset: &Offset,
    ) -> Intake {
        counter!(EVENTS_CONSUMED).increment(1);
        let partition = SourcePartition(offset.partition());
        let source_offset = SourceOffset(offset.get_value());

        let (event, person_id) = match decoded {
            Decoded::Forward { event, person_id } => (event, person_id),
            Decoded::DropNoPersonId => {
                counter!(EVENTS_DROPPED_NO_PERSON_ID).increment(1);
                ledger.observe(partition, source_offset, Observation::Settled);
                return Intake::Open;
            }
            Decoded::SkipTeamGate => {
                counter!(EVENTS_SKIPPED_TEAM_GATE).increment(1);
                ledger.observe(partition, source_offset, Observation::Settled);
                return Intake::Open;
            }
            Decoded::Unparseable => {
                counter!(EVENTS_UNPARSEABLE).increment(1);
                ledger.observe(partition, source_offset, Observation::Settled);
                return Intake::Open;
            }
        };

        let forward = Box::new(PendingForward {
            event: CohortStreamEvent::from_clickhouse(
                *event,
                person_id,
                partition.0,
                source_offset.0,
            ),
            partition,
            offset: source_offset,
        });
        self.try_enqueue(
            forward,
            self.settings.queue_full_backoff,
            ledger,
            pending_acks,
        )
    }

    /// One non-blocking enqueue attempt. `QueueFull` parks the forward for a timer-arm retry
    /// after `backoff`: the queue drains independently via librdkafka's delivery thread, and
    /// `message.timeout.ms` bounds how long it can stay full even with a dead broker.
    fn try_enqueue(
        &self,
        forward: Box<PendingForward>,
        backoff: Duration,
        ledger: &mut Ledger,
        pending_acks: &mut FuturesUnordered<AckFuture>,
    ) -> Intake {
        match self.producer.enqueue(&forward.event) {
            Ok(delivery) => {
                counter!(FORWARDS_ENQUEUED).increment(1);
                let PendingForward {
                    partition, offset, ..
                } = *forward;
                ledger.observe(partition, offset, Observation::InFlight);
                let sent_at = Instant::now();
                pending_acks.push(Box::pin(async move {
                    let result = match delivery.await {
                        Ok(Ok(_)) => Ok(()),
                        Ok(Err((err, _message))) => Err(err),
                        Err(_canceled) => Err(KafkaError::Canceled),
                    };
                    DeliveryAck {
                        partition,
                        offset,
                        sent_at,
                        result,
                    }
                }));
                Intake::Open
            }
            Err(EnqueueError::QueueFull) => {
                counter!(PRODUCE_QUEUE_FULL).increment(1);
                Intake::RetryForward {
                    resume_at: tokio::time::Instant::now() + backoff,
                    backoff: (backoff * 2).min(QUEUE_FULL_BACKOFF_CAP),
                    forward,
                }
            }
            Err(EnqueueError::Fatal(err)) => {
                counter!(PRODUCE_ERRORS).increment(1);
                counter!(EVENTS_ABANDONED).increment(1);
                warn!(error = %err, "fatal enqueue error; abandoning event");
                ledger.observe(forward.partition, forward.offset, Observation::Settled);
                Intake::Open
            }
        }
    }

    /// Plans a commit from the current assignment snapshot and spawns the blocking Sync commit
    /// into the single in-flight slot. Emits the ledger gauges even when there is nothing to
    /// commit.
    fn start_commit(&self, ledger: &mut Ledger) -> Option<CommitFuture> {
        let assigned = match self.consumer.assigned_partitions() {
            Ok(partitions) => partitions.into_iter().map(SourcePartition).collect(),
            Err(err) => {
                warn!(error = %err, "failed to snapshot partition assignment; skipping commit tick");
                return None;
            }
        };
        let plan = ledger.commit_plan(&assigned);
        if !plan.pruned.is_empty() {
            debug!(pruned = ?plan.pruned, "pruned revoked partitions from ledger");
        }

        let stats = ledger.stats();
        gauge!(FORWARDS_INFLIGHT).set(stats.in_flight as f64);
        gauge!(UNCOMMITTED_EVENTS).set(stats.uncommitted_events as f64);
        gauge!(LEDGER_PARTITIONS).set(stats.partitions as f64);

        if plan.offsets.is_empty() {
            return None;
        }
        let raw: Vec<(i32, i64)> = plan.offsets.iter().map(|&(p, n)| (p.0, n.0)).collect();
        let consumer = self.consumer.clone();
        let task = tokio::task::spawn_blocking(move || consumer.commit_partition_offsets(&raw));
        Some(Box::pin(async move { (plan.offsets, task.await) }))
    }

    /// Sequential shutdown: settle the in-flight commit, flush the producer, drain remaining
    /// acks, then one final Sync commit. Every step runs under one shared
    /// [`SHUTDOWN_DRAIN_BUDGET`] deadline with the final commit's slice reserved, so the drain
    /// provably fits the 15s graceful window. Anything unresolved at a deadline simply replays
    /// under the new consumer (at-least-once).
    async fn drain_and_commit(
        &self,
        mut ledger: Ledger,
        mut pending_acks: FuturesUnordered<AckFuture>,
        mut pending_commit: FuturesUnordered<CommitFuture>,
        intake: Intake,
    ) {
        let deadline = tokio::time::Instant::now() + SHUTDOWN_DRAIN_BUDGET;
        let pre_commit_deadline = deadline - SHUTDOWN_COMMIT_TIMEOUT;

        // Settle the in-flight commit first so the final plan is a real delta.
        if !pending_commit.is_empty() {
            match tokio::time::timeout_at(pre_commit_deadline, pending_commit.next()).await {
                Ok(Some((offsets, result))) => {
                    apply_commit_result(&mut ledger, offsets, result);
                }
                Ok(None) => {}
                Err(_) => warn!("in-flight commit did not settle before shutdown deadline"),
            }
        }

        // A forward parked on QueueFull gets one last attempt; if the queue is still full its
        // offset was never observed, so the commit stops short of it and the new owner replays.
        if let Intake::RetryForward {
            forward, backoff, ..
        } = intake
        {
            if let Intake::RetryForward { forward, .. } =
                self.try_enqueue(forward, backoff, &mut ledger, &mut pending_acks)
            {
                warn!(
                    partition = forward.partition.0,
                    offset = forward.offset.0,
                    "producer queue still full at shutdown; parked forward will replay"
                );
            }
        }

        let producer = self.producer.clone();
        let flush = tokio::task::spawn_blocking(move || producer.flush(SHUTDOWN_FLUSH_TIMEOUT));
        match tokio::time::timeout_at(pre_commit_deadline, flush).await {
            Ok(Ok(Ok(()))) => {}
            Ok(Ok(Err(err))) => warn!(error = %err, "producer flush failed during shutdown"),
            Ok(Err(err)) => error!(error = %err, "producer flush task panicked"),
            Err(_) => warn!("producer flush exceeded the shutdown budget"),
        }

        while !pending_acks.is_empty() {
            match tokio::time::timeout_at(pre_commit_deadline, pending_acks.next()).await {
                Ok(Some(ack)) => {
                    record_delivery(&mut ledger, ack);
                }
                Ok(None) => break,
                Err(_) => {
                    warn!(
                        unresolved = pending_acks.len(),
                        "ack drain deadline reached; unresolved forwards will replay"
                    );
                    break;
                }
            }
        }

        if let Some(commit) = self.start_commit(&mut ledger) {
            match tokio::time::timeout_at(deadline, commit).await {
                Ok((offsets, result)) => {
                    apply_commit_result(&mut ledger, offsets, result);
                }
                Err(_) => warn!("final offset commit timed out; committed work will replay"),
            }
        }
    }
}

fn record_delivery(ledger: &mut Ledger, ack: DeliveryAck) {
    let DeliveryAck {
        partition,
        offset,
        sent_at,
        result,
    } = ack;
    let outcome = match &result {
        Ok(()) => {
            counter!(EVENTS_FORWARDED).increment(1);
            DeliveryOutcome::Acked
        }
        Err(err) => {
            counter!(PRODUCE_ERRORS).increment(1);
            counter!(EVENTS_ABANDONED).increment(1);
            // Counter-visible rather than log-visible: a broker outage abandons at consume rate.
            debug!(
                error = %err,
                partition = partition.0,
                offset = offset.0,
                "delivery failed after librdkafka retries; abandoning event"
            );
            DeliveryOutcome::Abandoned
        }
    };
    let label = match outcome {
        DeliveryOutcome::Acked => "acked",
        DeliveryOutcome::Abandoned => "abandoned",
    };
    histogram!(PRODUCE_ACK_SECONDS, "outcome" => label).record(sent_at.elapsed().as_secs_f64());

    if ledger.resolve(partition, offset, outcome) == Resolution::Untracked {
        debug!(
            partition = partition.0,
            offset = offset.0,
            "straggler delivery for a pruned partition"
        );
    }
}

/// Returns true when the broker confirmed the commit (and the ledger was updated). Failed
/// commits are only counted: the unconfirmed delta is re-emitted at the next tick.
fn apply_commit_result(
    ledger: &mut Ledger,
    offsets: Vec<(SourcePartition, NextOffset)>,
    result: CommitResult,
) -> bool {
    match result {
        Ok(Ok(())) => {
            ledger.confirm_committed(&offsets);
            counter!(COMMITS).increment(1);
            true
        }
        Ok(Err(err)) => {
            counter!(COMMIT_ERRORS).increment(1);
            warn!(error = %err, "offset commit failed; retrying next tick");
            false
        }
        Err(err) => {
            counter!(COMMIT_ERRORS).increment(1);
            error!(error = %err, "offset commit task panicked");
            false
        }
    }
}

/// Liveness gate for the pipeline loop. Stale-and-committable is the only state that withholds the
/// heartbeat — a committer wedged for [`COMMIT_STALENESS_FACTOR`] intervals while committable work
/// waits must trip the stall detector. An idle topic (nothing committable) stays healthy even when
/// the last commit is old, and any fresh commit clears the staleness.
fn should_heartbeat(commit_stale: bool, has_committable: bool) -> bool {
    !commit_stale || !has_committable
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::sample_clickhouse_event;
    use serde_json::{json, Value};

    fn index_with(teams: &[i32]) -> TeamIndex {
        TeamIndex::from_teams(teams.iter().copied())
    }

    fn gate_fields(team_id: i32, person_id: Option<IgnoredAny>) -> GateFields {
        GateFields { team_id, person_id }
    }

    #[test]
    fn heartbeat_withheld_only_when_stale_and_committable() {
        // The single false case: a wedged committer with work waiting must stop heartbeating so
        // the stall detector restarts the pod.
        assert!(!should_heartbeat(true, true));
        // Stale but nothing to commit = idle topic, stays healthy.
        assert!(should_heartbeat(true, false));
        // Fresh commits keep the pod healthy regardless of pending work.
        assert!(should_heartbeat(false, true));
        assert!(should_heartbeat(false, false));
    }

    #[test]
    fn classify_gate_covers_every_gate_outcome() {
        let cases = [
            (
                "forward",
                Some(IgnoredAny),
                2,
                vec![2],
                GateOutcome::Forward,
            ),
            ("no person", None, 2, vec![2], GateOutcome::DropNoPersonId),
            (
                "team gate",
                Some(IgnoredAny),
                99,
                vec![2],
                GateOutcome::SkipTeamGate,
            ),
            (
                "no person precedence",
                None,
                99,
                vec![2],
                GateOutcome::DropNoPersonId,
            ),
            (
                "empty index",
                Some(IgnoredAny),
                2,
                vec![],
                GateOutcome::SkipTeamGate,
            ),
        ];

        for (name, person_id, team_id, teams, expected) in cases {
            let index = index_with(&teams);
            assert_eq!(
                classify_gate(&gate_fields(team_id, person_id), &index),
                expected,
                "case: {name}"
            );
        }
    }

    #[test]
    fn unloaded_index_forwards_nothing() {
        let index = TeamIndex::new();
        assert_eq!(
            classify_gate(&gate_fields(2, Some(IgnoredAny)), &index),
            GateOutcome::SkipTeamGate
        );
    }

    #[test]
    fn dropped_event_never_materializes_blobs() {
        // A JSON-object `properties` fails the full parse (the field is a stringified blob): outside
        // the index the gate ignores the blob and skips; inside it the survivor parse rejects it as
        // unparseable.
        let mut value: Value =
            serde_json::to_value(sample_clickhouse_event(99, Some("p"))).unwrap();
        value["properties"] = json!({ "a": [1, 2, 3] });
        let payload = serde_json::to_vec(&value).unwrap();

        assert!(matches!(
            decode_gated(&payload, &index_with(&[2])),
            Decoded::SkipTeamGate
        ));
        assert!(matches!(
            decode_gated(&payload, &index_with(&[99])),
            Decoded::Unparseable
        ));
    }

    #[test]
    fn garbage_payload_is_unparseable_not_an_error() {
        assert!(matches!(
            decode_gated(b"not json at all", &index_with(&[2])),
            Decoded::Unparseable
        ));
    }

    #[test]
    fn missing_person_mode_skips_mismatched_team_instead_of_erroring() {
        // `person_mode` is required by the full parse but ignored by the gate.
        let mut value: Value =
            serde_json::to_value(sample_clickhouse_event(99, Some("p"))).unwrap();
        value.as_object_mut().unwrap().remove("person_mode");
        let payload = serde_json::to_vec(&value).unwrap();

        assert!(matches!(
            decode_gated(&payload, &index_with(&[2])),
            Decoded::SkipTeamGate
        ));
    }

    #[test]
    fn person_id_presence_matches_full_parse_semantics() {
        let index = index_with(&[2]);
        let base: Value =
            serde_json::to_value(sample_clickhouse_event(2, Some("ignored"))).unwrap();
        let decode = |value: Value| decode_gated(&serde_json::to_vec(&value).unwrap(), &index);

        // Absent: drop (person check runs before the team gate).
        let mut absent = base.clone();
        absent.as_object_mut().unwrap().remove("person_id");
        assert!(matches!(decode(absent), Decoded::DropNoPersonId));

        // `null`: drop.
        let mut null = base.clone();
        null["person_id"] = Value::Null;
        assert!(matches!(decode(null), Decoded::DropNoPersonId));

        // Empty string is present: forward.
        let mut empty = base.clone();
        empty["person_id"] = json!("");
        match decode(empty) {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "");
                assert!(
                    event.person_id.is_none(),
                    "person_id must be taken from the event"
                );
            }
            other => panic!("expected Forward, got {other:?}"),
        }

        // Valid string: forward.
        let mut valid = base.clone();
        valid["person_id"] = json!("p");
        match decode(valid) {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "p");
                assert!(event.person_id.is_none());
            }
            other => panic!("expected Forward, got {other:?}"),
        }
    }

    #[test]
    fn survivor_fully_materializes_the_forward_envelope() {
        let payload = serde_json::to_vec(&sample_clickhouse_event(2, Some("p"))).unwrap();
        match decode_gated(&payload, &index_with(&[2])) {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "p");
                assert_eq!(event.team_id, 2);
                assert!(event.person_id.is_none(), "person_id should be taken");
                // Blobs skipped on the drop path are fully parsed for survivors.
                assert_eq!(
                    event.properties.as_deref(),
                    Some(r#"{"$current_url":"/pricing"}"#)
                );
                assert_eq!(
                    event.person_properties.as_deref(),
                    Some(r#"{"email":"u@p.com"}"#)
                );
            }
            other => panic!("expected Forward, got {other:?}"),
        }
    }
}
