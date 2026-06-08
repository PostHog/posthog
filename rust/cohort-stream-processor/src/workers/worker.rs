//! The long-lived per-partition Stage 1 worker.
//!
//! [`Stage1Worker::spawn`] drains one partition's channel on a dedicated tokio task, applying each
//! event through [`process_event`]. State mutation is inline (async WAL keeps writes sub-ms, so no
//! `spawn_blocking`), and a store error is logged-and-continued so one bad event never wedges the
//! partition.
//!
//! ## Produce before commit
//!
//! Per drained sub-batch the worker produces membership changes, awaits all acks, and only then
//! marks the sub-batch's offset processed. The per-partition offset is tracked over **all**
//! messages — including skipped/errored ones — so a poison event advances rather than wedges the
//! partition; **only a produce failure holds the offset back**, since the shadow output must be
//! durable before its offset commits. Re-produce on replay is idempotent for the parity diff.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{info, warn};

use crate::consumers::events::CohortStreamEvent;
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, OUTPUT_MEMBERSHIP_CHANGES_EMITTED,
    OUTPUT_PRODUCE_ERRORS, STAGE1_EVENTS_PROCESSED, STAGE1_EVENTS_SKIPPED,
    STAGE1_EVENT_PROCESS_DURATION, STAGE1_TRANSITIONS, SWEEP_KEYS_DROPPED_TOTAL,
    SWEEP_KEYS_EVICTED_TOTAL,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::{
    map_transition, now_last_updated, CohortMembershipChange, MembershipSink, MembershipStatus,
    OutputBuffer,
};
use crate::stage1::key::Stage1Key;
use crate::stage1::state::StateVariant;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::CohortStore;
use crate::sweep::EvictionQueue;
use crate::workers::event_path::{process_event, SkipReason};
use crate::workers::sweep_callback::{sweep_evict, EvictionAction, SweepDropReason};

/// A long-lived worker owning one partition's Stage 1 state. The task ends when the channel
/// `Sender` is dropped (the router's shutdown signal).
pub struct Stage1Worker {
    partition_id: u16,
    handle: JoinHandle<()>,
}

impl Stage1Worker {
    /// Spawn a worker draining `receiver` for `partition_id`. `store`, `catalog`, `sink`, and
    /// `tracker` are shared `Arc` handles; in particular the `tracker` is the one the consumer's
    /// commit loop reads.
    pub fn spawn(
        partition_id: u16,
        receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
        store: CohortStore,
        catalog: Arc<CatalogHandle>,
        sink: Arc<dyn MembershipSink>,
        tracker: Arc<OffsetTracker>,
    ) -> Self {
        let handle = tokio::spawn(run_worker(
            partition_id,
            receiver,
            store,
            catalog,
            sink,
            tracker,
        ));
        Self {
            partition_id,
            handle,
        }
    }

    pub fn partition_id(&self) -> u16 {
        self.partition_id
    }

    /// Resolves once the channel `Sender` is dropped and the loop has drained everything queued.
    pub async fn join(self) -> Result<(), tokio::task::JoinError> {
        self.handle.await
    }
}

/// The drain loop. Messages are processed in arrival order — the per-partition ordering guarantee
/// the affinity model rests on. An `Event` folds through the state machine and (re)schedules its
/// behavioral writes into `queue`; a `Sweep` drains `queue` for the keys past the cutoff and evicts
/// them. Each event sub-batch is produced and acked before its offset is marked.
///
/// `queue` lives across the loop as a single-mutator `let mut` (no sync): the worker is the only one
/// to touch its own `EvictionQueue`, the worker-affinity invariant that makes the in-memory queue
/// lock-free. It is rebuilt from events per tenure and dropped when the worker exits on revoke.
async fn run_worker(
    partition_id: u16,
    mut receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
) {
    info!(partition_id, "stage 1 worker started");

    let mut queue = EvictionQueue::<Stage1Key>::new();

    while let Some(batch) = receiver.recv().await {
        // One `last_updated` for the whole sub-batch: the parity diff is insensitive to sub-ms skew.
        let last_updated = now_last_updated();
        let mut buffer = OutputBuffer::new();
        let mut max_offset: Option<i64> = None;

        for message in batch {
            match message {
                ShuffleMessage::Event { event, cse_offset } => {
                    // Over ALL events, including skipped/errored ones, so a poison event can't wedge
                    // the partition. Only a produce failure (below) holds the offset back.
                    max_offset =
                        Some(max_offset.map_or(cse_offset, |current| current.max(cse_offset)));
                    let (changes, schedules) =
                        handle_event(partition_id, &store, &catalog, &event, &last_updated);
                    buffer.extend(changes);
                    // Eager + idempotent: every behavioral write (re)schedules its eviction, in or
                    // out of a transition. A reschedule supersedes, so an earlier-pulled deadline
                    // wins. Not gated on produce — scheduling is in-memory and replay-safe.
                    for (key, deadline) in schedules {
                        queue.schedule(key, deadline);
                    }
                }
                // Self-contained: the sweep produces its own membership changes and applies its own
                // state mutation, bypassing the event buffer and offset (it carries no Kafka offset).
                ShuffleMessage::Sweep { due_before_ms } => {
                    handle_sweep(
                        partition_id,
                        &store,
                        &catalog,
                        &sink,
                        &mut queue,
                        &last_updated,
                        due_before_ms,
                    )
                    .await;
                }
            }
        }

        if !buffer.is_empty() {
            let changes = buffer.take();
            let (entered, left) = count_by_status(&changes);
            let results = sink.produce(changes).await;
            let errors = results.iter().filter(|result| result.is_err()).count();
            if errors > 0 {
                counter!(OUTPUT_PRODUCE_ERRORS).increment(errors as u64);
                warn!(
                    partition_id,
                    errors,
                    "produce to cohort_membership_changed_shadow failed; holding offset for replay",
                );
                continue; // hold the offset; Kafka replays and re-produce is idempotent
            }
            if entered > 0 {
                counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Entered.as_str())
                    .increment(entered);
            }
            if left > 0 {
                counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Left.as_str())
                    .increment(left);
            }
        }

        // A `Sweep`-only batch carries no offset, so fall through without marking. Otherwise the
        // shadow output is durable, so the offset is safe to commit; `+ 1` is the next offset to
        // consume. A clamp to the dispatch ceiling means we tried to commit past an undispatched
        // offset and must surface it.
        if let Some(max_offset) = max_offset {
            if let MarkOutcome::CappedAheadOfDispatch =
                tracker.mark_processed(partition_id as i32, max_offset + 1)
            {
                counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
                warn!(
                    partition_id,
                    next_offset = max_offset + 1,
                    "offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
                );
            }
        }
    }

    info!(partition_id, "stage 1 worker stopped");
}

/// Tally `(entered, left)` for the `output_membership_changes_emitted_total{status}` counter.
fn count_by_status(changes: &[CohortMembershipChange]) -> (u64, u64) {
    changes
        .iter()
        .fold((0, 0), |(entered, left), change| match change.status {
            MembershipStatus::Entered => (entered + 1, left),
            MembershipStatus::Left => (entered, left + 1),
        })
}

/// Process one event end to end, returning the membership changes it produced (empty when skipped,
/// errored, or flipping no single-leaf cohort) **and** the behavioral writes to (re)schedule for
/// eviction (empty on every skip/error path). Emits the event-level metrics. A team absent from the
/// catalog is the worker's own preflight skip.
fn handle_event(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    event: &CohortStreamEvent,
    last_updated: &str,
) -> (Vec<CohortMembershipChange>, Vec<(Stage1Key, i64)>) {
    let snapshot = catalog.load();
    let Some(team_filters) = snapshot.team(TeamId(event.team_id)) else {
        counter!(STAGE1_EVENTS_SKIPPED, "reason" => SkipReason::NoTeamFilters.as_str())
            .increment(1);
        return (Vec::new(), Vec::new());
    };
    let filters: &TeamFilters = team_filters;

    let started = Instant::now();
    let result = process_event(partition_id, store, filters, event);
    histogram!(STAGE1_EVENT_PROCESS_DURATION).record(started.elapsed().as_secs_f64());

    match result {
        Ok(outcome) => {
            if let Some(reason) = outcome.skipped {
                counter!(STAGE1_EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                return (Vec::new(), Vec::new());
            }
            counter!(STAGE1_EVENTS_PROCESSED).increment(1);
            let mut changes = Vec::new();
            for transition in &outcome.transitions {
                if let Some(kind) = transition_metric_label(filters, transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
                changes.extend(map_transition(filters, transition, last_updated));
            }
            (changes, outcome.schedules)
        }
        Err(error) => {
            // The offset still advances: this is a corrupt-event skip that replay won't fix, so it
            // must not wedge the partition. Counted as a skip (on top of store_errors_total) so the
            // conservation identity `consumed == processed + Σskipped` stays exact.
            counter!(STAGE1_EVENTS_SKIPPED, "reason" => "store_error").increment(1);
            warn!(
                partition_id,
                team_id = event.team_id,
                error = %error,
                "stage 1 store error; skipping event without holding the offset",
            );
            (Vec::new(), Vec::new())
        }
    }
}

/// Drain the worker's eviction queue for every key past `due_before_ms` and evict it: produce any
/// membership changes (a daily `eq`/`lte`/`lt` slide can Enter, not only Leave), then — only on a
/// fully-acked produce — apply the state mutations in one `WriteBatch` and reschedule the survivors.
///
/// **Produce before write** (the inverse order of the event path, same at-least-once semantics): the
/// sweep has no Kafka offset to hold, so its retry vehicle is the un-evicted state plus the queue
/// entry. On any produce error it reschedules every popped key at its original deadline and writes
/// nothing — next tick re-derives the same changes against the still-present state and retries. A
/// crash strictly between the ack and the state-write is at-most-once (the state stays, but the
/// change was emitted), the same posture as the event path's shadow output (closed by PR 3.5).
async fn handle_sweep(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    queue: &mut EvictionQueue<Stage1Key>,
    last_updated: &str,
    due_before_ms: i64,
) {
    // Drain the due keys, keeping each deadline for the produce-error reschedule.
    let mut popped: Vec<(Stage1Key, i64)> = Vec::new();
    while let Some(entry) = queue.pop_due(due_before_ms) {
        popped.push(entry);
    }
    if popped.is_empty() {
        return;
    }

    // Group by team so each key is evicted against its own team's frozen filters (a partition hosts
    // many teams). `BTreeMap` keeps team order deterministic; pop (deadline) order is kept per team.
    let mut by_team: BTreeMap<u64, Vec<Stage1Key>> = BTreeMap::new();
    for &(key, _) in &popped {
        by_team.entry(key.team_id).or_default().push(key);
    }

    let snapshot = catalog.load();
    let mut changes = Vec::new();
    let mut results = Vec::new();
    // Reasons for keys popped but not evicted, counted on commit (below) alongside the evictions so
    // `popped == evicted + dropped` holds: a produce/write failure returns before counting either,
    // and the retry re-derives both. A read-error team is neither — its keys reschedule and retry.
    let mut drops: Vec<SweepDropReason> = Vec::new();
    for (team_id, keys) in &by_team {
        let Some(filters) = snapshot.team(TeamId(*team_id as i32)) else {
            // The team left the catalog (drift): drop its keys (they are not rescheduled, so its
            // state lingers until the next rebalance reclaims the slice).
            drops.extend(std::iter::repeat_n(SweepDropReason::TeamDrift, keys.len()));
            continue;
        };
        let filters: &TeamFilters = filters;
        match sweep_evict(filters, keys, store, due_before_ms) {
            Ok(evictions) => {
                for result in &evictions.results {
                    if let Some(transition) = &result.transition {
                        if let Some(kind) = transition_metric_label(filters, transition) {
                            counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                        }
                        changes.extend(map_transition(filters, transition, last_updated));
                    }
                }
                results.extend(evictions.results);
                drops.extend(evictions.drops);
            }
            Err(error) => {
                // A RocksDB read error for this team: reschedule its keys to retry next tick. They
                // are neither evicted nor dropped — the retry re-derives both.
                warn!(
                    partition_id,
                    team_id,
                    error = %error,
                    "sweep state read failed; rescheduling the team's keys for retry",
                );
                reschedule_team(queue, &popped, *team_id);
            }
        }
    }

    // Produce the membership changes (a daily eq/lte/lt slide can Enter, not only Leave) and await all
    // acks before mutating any state (produce before write). Split the counter before `produce` moves
    // `changes`, then increment once the flush is durable — mirroring the event-path flush.
    if !changes.is_empty() {
        let (entered, left) = count_by_status(&changes);
        let acks = sink.produce(changes).await;
        let errors = acks.iter().filter(|result| result.is_err()).count();
        if errors > 0 {
            counter!(OUTPUT_PRODUCE_ERRORS).increment(errors as u64);
            warn!(
                partition_id,
                errors,
                "sweep produce to cohort_membership_changed_shadow failed; rescheduling for replay",
            );
            reschedule_all(queue, &popped);
            return; // write nothing; the un-evicted state re-derives the same changes next tick
        }
        if entered > 0 {
            counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Entered.as_str())
                .increment(entered);
        }
        if left > 0 {
            counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Left.as_str())
                .increment(left);
        }
    }

    // Apply the evictions only once the produce is durable. Skipped when nothing was evicted (every
    // popped key was dropped) — there is no state to write, so fall through to the drop accounting.
    if !results.is_empty() {
        let written = store.write_batch(|batch| {
            for result in &results {
                match &result.action {
                    EvictionAction::Write(bytes) => batch.put_stage1(&result.key, bytes),
                    EvictionAction::Delete => batch.delete_stage1(&result.key),
                }
            }
        });
        if let Err(error) = written {
            // The changes were already produced (at-least-once); reschedule so the state advance
            // retries. Drops stay uncounted — the retry re-derives them on its eventual commit.
            warn!(
                partition_id,
                error = %error,
                "sweep state write failed; rescheduling popped keys to retry the eviction",
            );
            reschedule_all(queue, &popped);
            return;
        }

        // Reschedule the survivors (daily windows still holding buckets) at their next deadline.
        for result in &results {
            if let Some(deadline) = result.reschedule {
                queue.schedule(result.key, deadline);
            }
            counter!(SWEEP_KEYS_EVICTED_TOTAL, "variant" => result.variant.as_str()).increment(1);
        }
    }

    // Commit point reached (every eviction is durable, or there was nothing to evict): count the
    // dropped keys now — the same point as `SWEEP_KEYS_EVICTED_TOTAL` — so a produce/write failure
    // above (which returned early) re-derives and counts each drop exactly once on its eventual
    // success, keeping `popped == evicted + dropped` exact in steady state.
    for reason in &drops {
        counter!(SWEEP_KEYS_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
    }
}

/// Reschedule every popped key at its original deadline (still `< due_before_ms`, so it re-pops next
/// tick) — the produce/write-failure retry path.
fn reschedule_all(queue: &mut EvictionQueue<Stage1Key>, popped: &[(Stage1Key, i64)]) {
    for &(key, deadline) in popped {
        queue.schedule(key, deadline);
    }
}

/// Reschedule only one team's popped keys (a per-team read failure).
fn reschedule_team(
    queue: &mut EvictionQueue<Stage1Key>,
    popped: &[(Stage1Key, i64)],
    team_id: u64,
) {
    for &(key, deadline) in popped {
        if key.team_id == team_id {
            queue.schedule(key, deadline);
        }
    }
}

/// Map a transition to its `stage1_transitions_total{kind}` label. An unknown LSK maps to no metric.
/// A `BehavioralSingle` `Left` is only ever produced by the sweep (the event path never clears a
/// match), so it carries the `behavioral_left` label to keep the sweep's conservation story uniform.
/// A daily slide emits either direction — `behavioral_daily_left`, or `behavioral_daily_entered` when
/// a falling count enters an `eq`/`lte`/`lt` range; the compressed (>180-day) variant mirrors it with
/// `behavioral_compressed_left` / `behavioral_compressed_entered`.
fn transition_metric_label(
    filters: &TeamFilters,
    transition: &LeafTransition,
) -> Option<&'static str> {
    let variant = filters.by_lsk.get(&transition.leaf_state_key)?.variant;
    match (variant, transition.kind) {
        (StateVariant::BehavioralSingle, TransitionKind::Entered) => Some("behavioral_entered"),
        (StateVariant::BehavioralSingle, TransitionKind::Left) => Some("behavioral_left"),
        (StateVariant::BehavioralDailyBuckets, TransitionKind::Entered) => {
            Some("behavioral_daily_entered")
        }
        (StateVariant::BehavioralDailyBuckets, TransitionKind::Left) => {
            Some("behavioral_daily_left")
        }
        (StateVariant::BehavioralCompressedHistory, TransitionKind::Entered) => {
            Some("behavioral_compressed_entered")
        }
        (StateVariant::BehavioralCompressedHistory, TransitionKind::Left) => {
            Some("behavioral_compressed_left")
        }
        (StateVariant::PersonProperty, TransitionKind::Entered) => Some("person_entered"),
        (StateVariant::PersonProperty, TransitionKind::Left) => Some("person_left"),
    }
}
