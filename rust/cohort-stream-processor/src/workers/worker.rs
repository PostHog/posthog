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
//! partition; **only a produce failure holds the offset back**, since the shadow output should be
//! durable before its offset commits. Holding the offset is best-effort, not self-healing: the
//! state already committed during `process_event`, so the replay hits the `is_replay` guard and
//! skips the transition — a produce-failed flip is dropped at-most-once, the same envelope as a
//! crash here. Acceptable while shadow-only; the at-least-once cutover must commit state *after*
//! the produce ack so a replay can re-emit.

use std::borrow::Cow;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::{info, warn};
use uuid::Uuid;

use crate::consumers::events::CohortStreamEvent;
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::merge::tombstone_redirect::{self, Resolution};
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
use crate::store::{CohortStore, IndexOp, PersonIndexKey};
use crate::sweep::EvictionQueue;
use crate::workers::event_path::{process_event, SkipReason};
use crate::workers::stage2_path::compose_stage2;
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

/// The drain loop. Messages are processed in arrival order — the per-partition ordering guarantee.
/// An `Event` folds through the state machine and (re)schedules its behavioral writes into `queue`;
/// a `Sweep` drains `queue` for the keys past the cutoff and evicts them. Each event sub-batch is
/// produced and acked before its offset is marked.
///
/// `queue` lives across the loop as a single-mutator `let mut` (no sync): the worker is the only one
/// to touch its own `EvictionQueue`, making the in-memory queue lock-free.
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
                // The sweep is self-contained: produces and writes its own results, carries no Kafka offset.
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
                // A produce failure drops these flips for good, same as a crash here: the state
                // already committed, so the replay hits the `is_replay` guard and won't re-emit
                // them. Fine while shadow-only (at-most-once).
                continue;
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

    // Tombstone preflight (TDD §4.5.1): redirect a post-merge straggler for a merged-away person to
    // the person it merged into. A point-read per event — a bloom-filtered miss until C2 writes
    // tombstones, so it is the only hot-path delta this slice adds. Borrows the event unchanged on the
    // common `NotMerged` path; an unparseable/empty person_id has no tombstone and falls through to
    // `process_event`'s own skip.
    let resolved: Cow<'_, CohortStreamEvent> =
        match redirect_for_tombstone(partition_id, store, event) {
            Redirected::Process(event) => event,
            // Cross-partition redirect: C1 has no producer, so drop (counted + warned). C2 replaces this
            // with the ack-awaited re-produce to `cohort_stream_events` keyed to the target. Unreachable
            // until C2 writes tombstones. See SESSION.md.
            Redirected::DropCrossPartition => return (Vec::new(), Vec::new()),
        };

    let started = Instant::now();
    let result = process_event(partition_id, store, filters, &resolved);
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
            // Stage 2: re-evaluate the composable cohorts owning any flipped leaf. A store error is
            // already counted under `store_errors_total{op}`; log and skip — the recompute self-heals
            // the missed flip on the person's next event.
            match compose_stage2(
                partition_id,
                store,
                filters,
                &outcome.transitions,
                outcome.event_ms,
                last_updated,
            ) {
                Ok(stage2_changes) => changes.extend(stage2_changes),
                Err(error) => warn!(
                    partition_id,
                    team_id = event.team_id,
                    error = %error,
                    "stage 2 composition failed; skipping (self-heals on the person's next event)",
                ),
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

/// The tombstone preflight's outcome: the event to feed to [`process_event`] (the original or a
/// person-rewritten copy), or a signal to drop a cross-partition redirect (C1 has no re-producer).
///
/// Lives briefly on the stack per event; boxing the `Cow` to shrink the size gap would add a
/// per-event allocation on the hot path — the opposite of what we want (cf. `ShuffleMessage`).
#[allow(clippy::large_enum_variant)]
enum Redirected<'a> {
    Process(Cow<'a, CohortStreamEvent>),
    DropCrossPartition,
}

/// Resolve a straggler event through the [`tombstone_redirect`] chain. Borrows the event unchanged on
/// `NotMerged`; on an inline redirect returns a copy with `person_id` rewritten to the merge target
/// and `redirected_from` stamped with the chain origin. A backend read error or an unparseable id
/// falls through to normal processing (the tombstone is consulted again on the event's replay); a
/// cross-partition redirect is dropped (C1).
fn redirect_for_tombstone<'a>(
    partition_id: u16,
    store: &CohortStore,
    event: &'a CohortStreamEvent,
) -> Redirected<'a> {
    let Ok(person_id) = Uuid::parse_str(&event.person_id) else {
        // process_event skips an empty/unparseable id; no tombstone applies.
        return Redirected::Process(Cow::Borrowed(event));
    };
    let resolution =
        match tombstone_redirect::resolve(store, partition_id, TeamId(event.team_id), person_id) {
            Ok(resolution) => resolution,
            Err(error) => {
                warn!(
                    partition_id,
                    team_id = event.team_id,
                    error = %error,
                    "tombstone preflight read failed; processing without redirect",
                );
                return Redirected::Process(Cow::Borrowed(event));
            }
        };
    tombstone_redirect::record_redirect(&resolution);
    match resolution {
        Resolution::NotMerged => Redirected::Process(Cow::Borrowed(event)),
        Resolution::Inline {
            final_person,
            origin,
        } => Redirected::Process(Cow::Owned(rewrite_to(event, final_person, origin))),
        Resolution::CrossPartition {
            target_person,
            origin,
        } => {
            warn!(
                partition_id,
                team_id = event.team_id,
                %target_person,
                %origin,
                "cross-partition tombstone redirect dropped (C1; C2 re-produces the re-keyed event)",
            );
            Redirected::DropCrossPartition
        }
    }
}

/// Rewrite a straggler to its inline merge target: `person_id` becomes `final_person`, and
/// `redirected_from` is stamped with the chain `origin` **only if not already set** — a chained
/// re-produce keeps the first origin, which keys the merged record's `redirect_dedup`.
fn rewrite_to(event: &CohortStreamEvent, final_person: Uuid, origin: Uuid) -> CohortStreamEvent {
    CohortStreamEvent {
        person_id: final_person.to_string(),
        redirected_from: event
            .redirected_from
            .clone()
            .or_else(|| Some(origin.to_string())),
        ..event.clone()
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
/// change was emitted), the same posture as the event path's shadow output.
///
/// **Stage 2 runs after the Stage 1 commit**: once the eviction batch is durable, the tick's leaf
/// transitions fan out through [`compose_stage2`] — the same evaluator the event path uses — so a
/// time-driven leaf flip recomposes its composable cohorts against the post-eviction `cf_stage1`,
/// and the composed changes go out in a second, independent produce (disjoint cohort ids from the
/// single-leaf produce, so no `(cohort, person)` row straddles the boundary). That pass is
/// write-before-produce — compose commits `cf_stage2` before the produce — so it is at-most-once: a
/// failed produce (or a crash) drops the flip; an active person self-heals on their next event, a
/// dormant person's flip is lost until commit-after-ack durability lands (PR 3.5).
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
    // `changes`, then increment once the flush is durable.
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
                    // A full-expiry delete also retracts the leaf from the person's `cf_person_index`
                    // set, in the same batch, so the merge drain (M3) enumerating P_old's leaves never
                    // reads a stale key for state that no longer exists. The `Stage1Key` carries the
                    // person-index coordinates, so no extra read is needed; the drain still tolerates a
                    // residual hole (a `multi_get_stage1` miss is skipped), but keeping the index minimal
                    // bounds that work.
                    EvictionAction::Delete => {
                        batch.delete_stage1(&result.key);
                        batch.merge_person_index(
                            &PersonIndexKey {
                                partition_id: result.key.partition_id,
                                team_id: result.key.team_id,
                                person_id: result.key.person_id,
                            },
                            IndexOp::Remove(result.key.leaf_state_key),
                        );
                    }
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

        // Reschedule survivors at their next deadline.
        for result in &results {
            if let Some(deadline) = result.reschedule {
                queue.schedule(result.key, deadline);
            }
            counter!(SWEEP_KEYS_EVICTED_TOTAL, "variant" => result.variant.as_str()).increment(1);
        }
    }

    // Count drops here at the commit point so a produce/write failure (which returned early)
    // re-derives them, keeping popped == evicted + dropped exact.
    for reason in &drops {
        counter!(SWEEP_KEYS_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
    }

    // Stage 2: recompose the composable cohorts owning any leaf this tick flipped. Reached only
    // once the eviction batch committed (the failure paths above returned), so `compose_stage2`
    // reads post-eviction `cf_stage1` — a fully-drained `Delete` reads back as a non-member. The
    // transitions are re-read from `results` (`changes` was moved into the first produce); a
    // resultless tick composes nothing.
    let mut by_team_transitions: BTreeMap<u64, Vec<LeafTransition>> = BTreeMap::new();
    for result in &results {
        if let Some(transition) = &result.transition {
            by_team_transitions
                .entry(result.key.team_id)
                .or_default()
                .push(transition.clone());
        }
    }
    let mut stage2_changes = Vec::new();
    for (team_id, transitions) in &by_team_transitions {
        // The same `snapshot` the eviction ran under (no reload, so no team-drift window between
        // the two passes); a team with results always resolved above, so `None` is unreachable and
        // skipped defensively. A store error is logged and skipped, mirroring the event path — the
        // recompute self-heals the missed flip on the person's next event.
        let Some(filters) = snapshot.team(TeamId(*team_id as i32)) else {
            continue;
        };
        let filters: &TeamFilters = filters;
        match compose_stage2(
            partition_id,
            store,
            filters,
            transitions,
            due_before_ms,
            last_updated,
        ) {
            Ok(changes) => stage2_changes.extend(changes),
            Err(error) => warn!(
                partition_id,
                team_id,
                error = %error,
                "sweep stage 2 composition failed; skipping (self-heals on the person's next event)",
            ),
        }
    }
    if stage2_changes.is_empty() {
        return;
    }

    // The second produce. Write-before-produce: compose already committed `cf_stage2`, so a failed
    // produce here cannot retry (the recompute would diff against the advanced bit and emit
    // nothing) — the flip is dropped at-most-once, acceptable while shadow-only. Compose owns the
    // `STAGE2_*` counters post-commit; only the emission counter is incremented here.
    let (entered, left) = count_by_status(&stage2_changes);
    let acks = sink.produce(stage2_changes).await;
    let errors = acks.iter().filter(|result| result.is_err()).count();
    if errors > 0 {
        counter!(OUTPUT_PRODUCE_ERRORS).increment(errors as u64);
        warn!(
            partition_id,
            errors,
            "sweep stage 2 produce to cohort_membership_changed_shadow failed; dropping (cf_stage2 already committed, at-most-once)",
        );
        return;
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

/// Reschedule every popped key at its original deadline (still `< due_before_ms`, so it re-pops next
/// tick).
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

/// Map a transition to its `stage1_transitions_total{kind}` label. An unknown LSK returns `None`.
/// A `BehavioralSingle` `Left` is only emitted by the sweep (the event path never clears a match).
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

#[cfg(test)]
mod tombstone_redirect_tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::json;
    use tempfile::TempDir;

    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::store::{StoreConfig, TombstoneKey};

    const TEAM: i32 = 7;
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    /// A single person-property leaf cohort (`email == "u@p.com"`), so one leaf flip is the cohort's
    /// whole membership and `handle_event` emits a per-cohort change directly.
    fn person_catalog() -> Arc<CatalogHandle> {
        let leaf = json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        });
        let cohort = json!({ "properties": { "type": "AND", "values": [leaf] } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(TEAM), &cohort)
            .unwrap();
        Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TeamId(TEAM),
            builder.freeze(UTC),
        )])))
    }

    fn applied(entries: &[(i32, i64)]) -> AppliedOffsets {
        let mut applied = AppliedOffsets::default();
        for &(partition, offset) in entries {
            applied.record(partition, offset);
        }
        applied
    }

    fn person_event(
        person: Uuid,
        email: &str,
        source_partition: i32,
        source_offset: i64,
    ) -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: TEAM,
            person_id: person.to_string(),
            distinct_id: "d".to_string(),
            uuid: "u".to_string(),
            event: "$pageview".to_string(),
            timestamp: "2026-05-26 12:34:56.789000".to_string(),
            properties: Some("{}".to_string()),
            person_properties: Some(format!(r#"{{"email":"{email}"}}"#)),
            elements_chain: None,
            source_offset,
            source_partition,
            redirected_from: None,
        }
    }

    fn stage1_key(partition_id: u16, lsk: LeafStateKey, person: Uuid) -> Stage1Key {
        Stage1Key {
            partition_id,
            team_id: TEAM as u64,
            leaf_state_key: lsk,
            person_id: person,
        }
    }

    fn write_tombstone(store: &CohortStore, partition_id: u16, old: Uuid, new: Uuid) {
        let value = Tombstone {
            new_person: new,
            merged_at_ms: 1,
        };
        store
            .write_batch(|b| {
                b.put_tombstone(
                    &TombstoneKey {
                        partition_id,
                        team_id: TEAM as u64,
                        person: old,
                    },
                    &value.encode(),
                )
            })
            .unwrap();
    }

    #[test]
    fn inline_redirect_folds_into_redirect_dedup_origin_not_the_main_map() {
        // A straggler for a merged-away P_old (P_new co-resides) is redirected to P_new and folded via
        // `redirect_dedup[P_old]` — the double-fold guard: the fold must NOT touch P_new's main map.
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

        let p_new = Uuid::from_u128(2);
        let partition_id = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as u16;
        let p_old = Uuid::from_u128(1);
        write_tombstone(&store, partition_id, p_old, p_new);

        // P_new: not a member; main offsets {5:50}, an ancestor entry for P_old at {5:100}.
        let mut seed = StatefulRecord::new(
            Stage1State::PersonProperty {
                matches: false,
                last_updated_at_ms: 1_000,
                last_updated_offset: 0,
            },
            applied(&[(5, 50)]),
        );
        seed.redirect_dedup.insert(p_old, applied(&[(5, 100)]));
        let p_new_key = stage1_key(partition_id, lsk, p_new);
        store
            .write_batch(|b| b.put_stage1(&p_new_key, &seed.encode()))
            .unwrap();

        // A matching straggler for P_old at offset 101 (> the ancestor's 100): folds into P_new.
        let straggler = person_event(p_old, "u@p.com", 5, 101);
        let (changes, _schedules) = handle_event(partition_id, &store, &catalog, &straggler, "ts");

        // The single-leaf cohort flips to Entered for P_new (not P_old).
        assert_eq!(changes.len(), 1, "the straggler entered P_new");
        assert_eq!(changes[0].person_id, p_new.to_string());
        assert_eq!(changes[0].status, MembershipStatus::Entered);

        let after =
            StatefulRecord::decode(&store.get_stage1(&p_new_key).unwrap().unwrap()).unwrap();
        assert!(matches!(
            after.state,
            Stage1State::PersonProperty { matches: true, .. }
        ));
        assert!(
            after.redirect_dedup[&p_old].is_replay(5, 101),
            "the fold advanced redirect_dedup[origin]",
        );
        assert!(
            after.applied_offsets.is_replay(5, 50) && !after.applied_offsets.is_replay(5, 51),
            "the main map is untouched by a redirected straggler",
        );

        // No state was created for P_old — it stays merged away.
        assert!(store
            .get_stage1(&stage1_key(partition_id, lsk, p_old))
            .unwrap()
            .is_none());
    }

    #[test]
    fn cross_partition_redirect_is_dropped_in_c1() {
        // P_new hashes to a different partition: C1 has no re-producer, so the straggler is dropped
        // (counted + warned) and writes nothing. C2 replaces this with the ack-awaited re-produce.
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

        let p_old = Uuid::from_u128(1);
        let partition_id = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as u16;
        let p_new = (10u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 != partition_id)
            .unwrap();
        write_tombstone(&store, partition_id, p_old, p_new);

        let straggler = person_event(p_old, "u@p.com", 5, 1);
        let (changes, schedules) = handle_event(partition_id, &store, &catalog, &straggler, "ts");

        assert!(
            changes.is_empty(),
            "the cross-partition redirect is dropped"
        );
        assert!(schedules.is_empty());
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, p_old))
                .unwrap()
                .is_none(),
            "no state written for P_old",
        );
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, p_new))
                .unwrap()
                .is_none(),
            "no state written for P_new on this worker",
        );
    }

    #[test]
    fn no_tombstone_processes_the_event_normally() {
        // The common path: no tombstone, so the event folds for its own person.
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = Uuid::from_u128(3);
        let partition_id = partition_of(TeamId(TEAM), &alice, COHORT_PARTITION_COUNT) as u16;

        let event = person_event(alice, "u@p.com", 5, 0);
        let (changes, _schedules) = handle_event(partition_id, &store, &catalog, &event, "ts");
        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].person_id, alice.to_string());
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, alice))
                .unwrap()
                .is_some(),
            "alice's own state was written",
        );
    }
}
