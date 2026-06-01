//! The long-lived per-partition Stage 1 worker (TDD §2.3, §2.5, §6.1 PR 1.8).
//!
//! [`Stage1Worker::spawn`] takes ownership of one partition's channel `Receiver` (handed out by
//! [`PartitionRouter::add_partition`](crate::partitions::router::PartitionRouter::add_partition))
//! and drains it on a dedicated tokio task, applying each event through [`process_event`]. It
//! mirrors `kafka-deduplicator`'s `partition_worker.rs::run_worker`: a `while let Some(batch) =
//! recv().await` loop, sync state mutation inline (async WAL keeps writes sub-ms — no
//! `spawn_blocking` in M1), and **log-and-continue** on a store error so one bad event never wedges
//! the partition.
//!
//! ## Produce before commit (PR 1.8)
//!
//! The worker owns the offset commit, because the transitions are computed here, after the durable
//! state write. Per drained sub-batch it: applies each event, projects the resulting transitions
//! into membership changes ([`map_transition`]), flushes them to the [`MembershipSink`], and only
//! then marks the sub-batch's `cohort_stream_events` offset processed (the established shuffler
//! idiom: produce → await acks → commit only on full success, else hold for Kafka replay). The
//! per-partition offset is tracked over **all** messages — including skipped/errored ones — so a
//! poison event advances rather than wedges the partition; **only a produce failure holds the
//! offset back** (the shadow output must be durable before its offset is committed). Re-produce on
//! replay is idempotent for the per-cohort parity diff.

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
    STAGE1_EVENT_PROCESS_DURATION, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::{
    map_transition, now_last_updated, CohortMembershipChange, MembershipSink, MembershipStatus,
    OutputBuffer,
};
use crate::stage1::state::StateVariant;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::CohortStore;
use crate::workers::event_path::{process_event, SkipReason};

/// A long-lived worker owning one partition's RocksDB-backed Stage 1 state. Spawned per assigned
/// partition; the task ends when the channel `Sender` is dropped (the router's shutdown signal).
pub struct Stage1Worker {
    partition_id: u16,
    handle: JoinHandle<()>,
}

impl Stage1Worker {
    /// Spawn a worker draining `receiver` for `partition_id`. `store`, `catalog`, `sink`, and
    /// `tracker` are shared handles (cheap `Arc` clones), so every partition's worker reads the
    /// same DB and filter snapshot, produces through the same sink, and records offsets in the same
    /// tracker the consumer's commit loop reads.
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

    /// The partition this worker owns.
    pub fn partition_id(&self) -> u16 {
        self.partition_id
    }

    /// Wait for the worker to finish draining and exit. Resolves once the channel `Sender` has been
    /// dropped and the loop has processed everything queued.
    pub async fn join(self) -> Result<(), tokio::task::JoinError> {
        self.handle.await
    }
}

/// The drain loop. One sub-batch at a time, one event at a time, in arrival order — the
/// per-partition ordering guarantee the affinity model rests on. Each sub-batch is produced and
/// acked before its offset is marked (produce before commit).
async fn run_worker(
    partition_id: u16,
    mut receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
    store: CohortStore,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
) {
    info!(partition_id, "stage 1 worker started");

    while let Some(batch) = receiver.recv().await {
        // Stamp `last_updated` once for the whole drained sub-batch — the per-(cohort, person)
        // parity diff is insensitive to sub-millisecond skew, and it keeps the flush consistent.
        let last_updated = now_last_updated();
        let mut buffer = OutputBuffer::new();
        let mut max_offset: Option<i64> = None;

        for message in batch {
            let ShuffleMessage::Event { event, cse_offset } = message;
            // Track the max offset over ALL messages — even a skipped/errored event must advance the
            // offset so a poison event can't wedge the partition (matching PR 1.7). Only a produce
            // failure (below) holds it back.
            max_offset = Some(max_offset.map_or(cse_offset, |current| current.max(cse_offset)));
            buffer.extend(handle_event(
                partition_id,
                &store,
                &catalog,
                &event,
                &last_updated,
            ));
        }

        let Some(max_offset) = max_offset else {
            continue; // empty sub-batch — nothing to produce or mark
        };

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
                continue; // hold the offset back — Kafka replays, state + re-produce are idempotent
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

        // Success (or an empty buffer): the sub-batch's shadow output is durable, so its offset is
        // safe to commit. `+ 1` is the next offset to consume. The tracker clamps the mark to the
        // dispatch ceiling; a clamp that bites means we tried to commit past an undispatched offset
        // (the F1 invariant), which must be surfaced rather than silently swallowed.
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

    info!(partition_id, "stage 1 worker stopped");
}

/// Tally a flush's changes by status for the `output_membership_changes_emitted_total{status}`
/// counter.
fn count_by_status(changes: &[CohortMembershipChange]) -> (u64, u64) {
    changes
        .iter()
        .fold((0, 0), |(entered, left), change| match change.status {
            MembershipStatus::Entered => (entered + 1, left),
            MembershipStatus::Left => (entered, left + 1),
        })
}

/// Process one event end to end, returning the membership changes it produced (empty when the event
/// is skipped, errors, or flips no single-leaf cohort). Emits the event-level metrics. A team absent
/// from the catalog is the worker's own preflight skip; everything else flows through
/// [`process_event`].
fn handle_event(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    event: &CohortStreamEvent,
    last_updated: &str,
) -> Vec<CohortMembershipChange> {
    let snapshot = catalog.load();
    let Some(team_filters) = snapshot.team(TeamId(event.team_id)) else {
        counter!(STAGE1_EVENTS_SKIPPED, "reason" => SkipReason::NoTeamFilters.as_str())
            .increment(1);
        return Vec::new();
    };
    let filters: &TeamFilters = team_filters;

    let started = Instant::now();
    let result = process_event(partition_id, store, filters, event);
    histogram!(STAGE1_EVENT_PROCESS_DURATION).record(started.elapsed().as_secs_f64());

    match result {
        Ok(outcome) => {
            if let Some(reason) = outcome.skipped {
                counter!(STAGE1_EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                return Vec::new();
            }
            counter!(STAGE1_EVENTS_PROCESSED).increment(1);
            let mut changes = Vec::new();
            for transition in &outcome.transitions {
                if let Some(kind) = transition_metric_label(filters, transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
                changes.extend(map_transition(filters, transition, last_updated));
            }
            changes
        }
        Err(error) => {
            // The store already counted the backend failure (store_errors_total). The offset still
            // advances (via max_offset) — this is a corrupt-event skip that replay won't fix, so it
            // must not wedge the partition. Only a produce error holds the offset. Count it as a
            // skip too (F9), so the conservation identity `consumed == processed + Σskipped` stays
            // exact even under store errors (otherwise the event vanishes from both tallies).
            counter!(STAGE1_EVENTS_SKIPPED, "reason" => "store_error").increment(1);
            warn!(
                partition_id,
                team_id = event.team_id,
                error = %error,
                "stage 1 store error; skipping event without holding the offset",
            );
            Vec::new()
        }
    }
}

/// Map a transition to its `stage1_transitions_total{kind}` label by resolving the leaf's variant
/// in the current snapshot. `behavioral_left` is impossible in M1 (no eviction yet) and an unknown
/// LSK shouldn't occur, so those combinations emit no metric.
fn transition_metric_label(
    filters: &TeamFilters,
    transition: &LeafTransition,
) -> Option<&'static str> {
    let variant = filters.by_lsk.get(&transition.leaf_state_key)?.variant;
    match (variant, transition.kind) {
        (StateVariant::BehavioralSingle, TransitionKind::Entered) => Some("behavioral_entered"),
        (StateVariant::PersonProperty, TransitionKind::Entered) => Some("person_entered"),
        (StateVariant::PersonProperty, TransitionKind::Left) => Some("person_left"),
        (StateVariant::BehavioralSingle, TransitionKind::Left) => None,
    }
}
