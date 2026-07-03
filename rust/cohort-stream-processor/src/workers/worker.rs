//! Per-partition Stage 1 worker.
//!
//! [`Stage1Worker::spawn`] drains one partition's channel on a dedicated tokio task. Per sub-batch
//! it produces membership changes and straggler re-keys, awaits all acks, then marks the offset
//! processed. A produce failure holds the offset; a store error is logged and the event is skipped.

use std::borrow::Cow;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use metrics::{counter, histogram};
use tokio::task::JoinHandle;
use tracing::{info, warn};
use uuid::Uuid;

use crate::cascade::{first_cascade, CascadeMessage};
use crate::consumers::events::CohortStreamEvent;
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::merge::tombstone_redirect::{self, Resolution};
use crate::observability::metrics::{
    CASCADE_PRODUCE_ERRORS_TOTAL, COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH,
    EVICTION_QUEUE_REBUILT_KEYS_TOTAL, MERGE_REDIRECT_HOP_CAPPED_TOTAL,
    MERGE_REKEY_PRODUCE_FAILURE_TOTAL, OUTPUT_MEMBERSHIP_CHANGES_EMITTED, OUTPUT_PRODUCE_ERRORS,
    STAGE1_EVENTS_PROCESSED, STAGE1_EVENTS_SKIPPED, STAGE1_EVENT_PROCESS_DURATION,
    STAGE1_STATE_DECODE_ERROR, STAGE1_TRANSITIONS, SWEEP_KEYS_DROPPED_TOTAL,
    SWEEP_KEYS_EVICTED_TOTAL,
};
use crate::partitions::intake::MeteredReceiver;
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::partitions::shuffle_message::ShuffleMessage;
use crate::producer::{
    map_transition, now_last_updated, CohortMembershipChange, MembershipSink, MembershipStatus,
    OutputBuffer,
};
use crate::stage1::key::Stage1Key;
use crate::stage1::state::{StateVariant, StatefulRecord};
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{IndexOp, PersonIndexKey, ReadLane, StagedBatch, StoreHandle};
use crate::sweep::EvictionQueue;
use crate::workers::cascade_path::handle_cascade;
use crate::workers::event_path::{
    process_event_offloaded, schedule_deadline, EventNameGating, SkipReason,
};
use crate::workers::merge_gc::{handle_merge_gc, MergeGcCursor};
use crate::workers::merge_path::{handle_apply, handle_merge, handle_redrive, MergeWorkerDeps};
use crate::workers::person_memo::{PersonMemo, PersonMemoConfig};
use crate::workers::stage2_gc::{handle_stage2_orphan_gc, Stage2GcCursor};
use crate::workers::stage2_path::compose_stage2;
use crate::workers::sweep_callback::{sweep_evict, EvictionAction, SweepDropReason};

/// Max eviction keys a single sweep pass drains. Daily-bucket deadlines cluster on tz-midnight, so a
/// large team's whole wave can come due on one tick; capping the pop loop bounds the per-pass RocksDB
/// read + produce + write batch + Stage 2 pass so events do not queue behind one giant sweep. Leftover
/// due keys stay scheduled and drain on the next sweep tick.
const MAX_SWEEP_KEYS_PER_PASS: usize = 10_000;

const REBUILD_SCAN_PAGE: usize = 10_000;

/// Chunk size for a team's sweep-state prefetch. The keys are read in fixed-size batches so each
/// `multi_get_stage1` call spans a bounded number of keys — capping the time any single read op holds
/// before the sweep can make progress.
const SWEEP_MULTI_GET_CHUNK: usize = 1024;

/// Cooperative-yield cadence inside the worker fold. `handle_event` is synchronous, so a backlog of
/// CPU-bound events would hold the runtime thread, starving the commit task and consume loop. A
/// wall-clock interval adapts to per-event cost across catalogs of different sizes.
const WORKER_YIELD_INTERVAL: Duration = Duration::from_millis(5);

pub struct Stage1Worker {
    partition_id: u16,
    handle: JoinHandle<()>,
}

impl Stage1Worker {
    /// Spawn with the person memo disabled. The memoizing variant is [`Self::spawn_with_memo`].
    #[allow(clippy::too_many_arguments)]
    pub fn spawn(
        partition_id: u16,
        receiver: MeteredReceiver,
        store: StoreHandle,
        catalog: Arc<CatalogHandle>,
        sink: Arc<dyn MembershipSink>,
        tracker: Arc<OffsetTracker>,
        merge: Arc<MergeWorkerDeps>,
        durable_restore: bool,
    ) -> Self {
        Self::spawn_with_memo(
            partition_id,
            receiver,
            store,
            catalog,
            sink,
            tracker,
            merge,
            durable_restore,
            PersonMemoConfig::DISABLED,
            EventNameGating::Disabled,
        )
    }

    /// When `durable_restore` is on, re-seeds the `EvictionQueue` from `cf_stage1` on spawn so a
    /// dormant person's `Left` still fires after a crash-restart.
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_with_memo(
        partition_id: u16,
        receiver: MeteredReceiver,
        store: StoreHandle,
        catalog: Arc<CatalogHandle>,
        sink: Arc<dyn MembershipSink>,
        tracker: Arc<OffsetTracker>,
        merge: Arc<MergeWorkerDeps>,
        durable_restore: bool,
        person_memo: PersonMemoConfig,
        event_name_gating: EventNameGating,
    ) -> Self {
        let handle = tokio::spawn(run_worker(
            partition_id,
            receiver,
            store,
            catalog,
            sink,
            tracker,
            merge,
            durable_restore,
            person_memo,
            event_name_gating,
        ));
        Self {
            partition_id,
            handle,
        }
    }

    pub fn partition_id(&self) -> u16 {
        self.partition_id
    }

    pub async fn join(self) -> Result<(), tokio::task::JoinError> {
        self.handle.await
    }
}

#[allow(clippy::too_many_arguments)]
async fn run_worker(
    partition_id: u16,
    mut receiver: MeteredReceiver,
    handle: StoreHandle,
    catalog: Arc<CatalogHandle>,
    sink: Arc<dyn MembershipSink>,
    tracker: Arc<OffsetTracker>,
    merge: Arc<MergeWorkerDeps>,
    durable_restore: bool,
    person_memo: PersonMemoConfig,
    event_name_gating: EventNameGating,
) {
    info!(partition_id, "stage 1 worker started");

    let mut queue = EvictionQueue::<Stage1Key>::new();
    // Reused across batches so cached results survive between events.
    let mut person_memo = PersonMemo::new(person_memo);
    // No-op for a cold partition (bloom-filtered scan finds nothing to schedule).
    if durable_restore {
        rebuild_eviction_queue(partition_id, &handle, &mut queue).await;
    }
    // In-memory resume cursors; loss on rebalance is benign (GC re-scans from the start).
    let mut gc_cursor = MergeGcCursor::default();
    let mut stage2_gc_cursor = Stage2GcCursor::default();

    // Persists across batches so a stream of buffered batches still yields on the wall-clock interval.
    let mut last_yield = Instant::now();
    while let Some(batch) = receiver.recv().await {
        let last_updated = now_last_updated();
        let mut buffer = OutputBuffer::new();
        let mut re_keys: Vec<CohortStreamEvent> = Vec::new();
        let mut max_offset: Option<i64> = None;
        // Set when a pre-arm flush fails: holds the whole batch's offset so Kafka replays it.
        let mut held = false;

        for message in batch {
            match message {
                ShuffleMessage::Event { event, cse_offset } => {
                    max_offset =
                        Some(max_offset.map_or(cse_offset, |current| current.max(cse_offset)));
                    let effects = handle_event(
                        partition_id,
                        &handle,
                        &catalog,
                        &event,
                        &last_updated,
                        merge.partition_count,
                        &mut person_memo,
                        event_name_gating,
                    )
                    .await;
                    buffer.extend(effects.changes);
                    for (key, deadline) in effects.schedules {
                        queue.schedule(key, deadline);
                    }
                    re_keys.extend(effects.re_keys);
                }
                ShuffleMessage::Sweep { due_before_ms } => {
                    if flush_event_changes_before_inline(
                        &sink,
                        &mut buffer,
                        partition_id,
                        &mut held,
                    )
                    .await
                    {
                        break;
                    }
                    handle_sweep(
                        partition_id,
                        &handle,
                        &catalog,
                        &sink,
                        &merge,
                        &mut queue,
                        &last_updated,
                        due_before_ms,
                    )
                    .await;
                }
                ShuffleMessage::Merge { event, offset } => {
                    if flush_event_changes_before_inline(
                        &sink,
                        &mut buffer,
                        partition_id,
                        &mut held,
                    )
                    .await
                    {
                        break;
                    }
                    handle_merge(
                        partition_id,
                        &handle,
                        &catalog,
                        &sink,
                        &merge,
                        &mut queue,
                        &last_updated,
                        &event,
                        offset,
                    )
                    .await;
                }
                ShuffleMessage::Transfer { transfer, offset } => {
                    if flush_event_changes_before_inline(
                        &sink,
                        &mut buffer,
                        partition_id,
                        &mut held,
                    )
                    .await
                    {
                        break;
                    }
                    handle_apply(
                        partition_id,
                        &handle,
                        &catalog,
                        &sink,
                        &merge,
                        &mut queue,
                        &last_updated,
                        &transfer,
                        offset,
                    )
                    .await;
                }
                ShuffleMessage::Cascade { message, offset } => {
                    if flush_event_changes_before_inline(
                        &sink,
                        &mut buffer,
                        partition_id,
                        &mut held,
                    )
                    .await
                    {
                        break;
                    }
                    handle_cascade(
                        partition_id,
                        &handle,
                        &catalog,
                        &sink,
                        &merge,
                        &last_updated,
                        &message,
                        offset,
                    )
                    .await;
                }
                ShuffleMessage::RedrivePendingTransfers => {
                    handle_redrive(partition_id, &handle, &merge).await;
                }
                ShuffleMessage::MergeCfGc {
                    marker_cutoff_ms,
                    tombstone_cutoff_ms,
                } => {
                    // Run each GC pass as a whole sync section on the blocking pool. The in-memory
                    // resume cursor moves in and comes back out by value; a teardown cancellation
                    // resets it to `Default`, which is benign — the GC re-scans from the prefix start
                    // next tenure, exactly as it does after a rebalance.
                    let scan_limit = merge.gc_scan_limit;
                    let mut cursor = std::mem::take(&mut gc_cursor);
                    gc_cursor = handle
                        .run_section("merge_gc", move |store| {
                            handle_merge_gc(
                                partition_id,
                                store,
                                &mut cursor,
                                marker_cutoff_ms,
                                tombstone_cutoff_ms,
                                scan_limit,
                            );
                            cursor
                        })
                        .await
                        .unwrap_or_default();
                    if merge.stage2_orphan_gc_enabled {
                        // An `Arc<CatalogHandle>` clone moves into the section so the handler keeps
                        // its two safety gates (is_loaded, empty-catalog) unchanged; the cursor makes
                        // the same by-value round-trip as the merge GC above.
                        let catalog = catalog.clone();
                        let mut cursor = std::mem::take(&mut stage2_gc_cursor);
                        stage2_gc_cursor = handle
                            .run_section("stage2_orphan_gc", move |store| {
                                handle_stage2_orphan_gc(
                                    partition_id,
                                    store,
                                    &catalog,
                                    &mut cursor,
                                    scan_limit,
                                );
                                cursor
                            })
                            .await
                            .unwrap_or_default();
                    }
                }
            }

            if last_yield.elapsed() >= WORKER_YIELD_INTERVAL {
                tokio::task::yield_now().await;
                last_yield = Instant::now();
            }
        }

        if held {
            continue;
        }

        if !buffer.is_empty() {
            let changes = buffer.take();
            // Build cascades from a borrow before `changes` is moved into produce; gate-off allocates nothing.
            let cascades = first_cascades(&merge, &changes, max_offset.unwrap_or(0));
            let errors = produce_membership(&sink, changes).await;
            if errors > 0 {
                warn!(
                    partition_id,
                    errors,
                    "produce to cohort_membership_changed_shadow failed; holding offset for replay",
                );
                continue;
            }
            let cascade_errors = produce_cascades(&merge, cascades).await;
            if cascade_errors > 0 {
                warn!(
                    partition_id,
                    errors = cascade_errors,
                    "produce to cohort_cascade_events failed; holding offset for replay",
                );
                continue;
            }
        }

        if !re_keys.is_empty() {
            let produced = re_keys.len() as u64;
            let acks = merge.stream_event_sink.produce(re_keys).await;
            let errors = acks.iter().filter(|result| result.is_err()).count();
            if errors > 0 {
                counter!(MERGE_REKEY_PRODUCE_FAILURE_TOTAL).increment(errors as u64);
                warn!(
                    partition_id,
                    errors,
                    "straggler re-key produce to cohort_stream_events failed; holding offset for replay",
                );
                continue;
            }
            tombstone_redirect::record_re_keyed(produced);
        }

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

/// Flush buffered event-path changes so they land before an inline (sweep/merge/transfer) produce,
/// preserving produce order == state-commit order. No-op when the buffer is empty.
/// Returns the failed-ack count (`0` = fully acked / empty).
async fn flush_membership_buffer(
    sink: &Arc<dyn MembershipSink>,
    buffer: &mut OutputBuffer,
) -> usize {
    if buffer.is_empty() {
        return 0;
    }
    produce_membership(sink, buffer.take()).await
}

/// Flush buffered event-path changes ahead of an inline arm. Returns `true` when the flush failed:
/// sets `held` so the caller `break`s and `mark_processed` is skipped, causing Kafka to replay.
/// Returns `false` (empty or all acked) to run the arm normally.
async fn flush_event_changes_before_inline(
    sink: &Arc<dyn MembershipSink>,
    buffer: &mut OutputBuffer,
    partition_id: u16,
    held: &mut bool,
) -> bool {
    let errors = flush_membership_buffer(sink, buffer).await;
    if errors > 0 {
        *held = true;
        warn!(
            partition_id,
            errors, "produce to cohort_membership_changed_shadow failed; holding offset for replay",
        );
        return true;
    }
    false
}

pub(crate) fn count_by_status(changes: &[CohortMembershipChange]) -> (u64, u64) {
    changes
        .iter()
        .fold((0, 0), |(entered, left), change| match change.status {
            MembershipStatus::Entered => (entered + 1, left),
            MembershipStatus::Left => (entered, left + 1),
        })
}

/// Produce membership `changes`, await acks, and record metrics. Returns the failed-ack count
/// (`0` = fully acked). The caller owns the per-site warn and recovery action.
pub(crate) async fn produce_membership(
    sink: &Arc<dyn MembershipSink>,
    changes: Vec<CohortMembershipChange>,
) -> usize {
    let (entered, left) = count_by_status(&changes);
    let acks = sink.produce(changes).await;
    let errors = acks.iter().filter(|result| result.is_err()).count();
    if errors > 0 {
        counter!(OUTPUT_PRODUCE_ERRORS).increment(errors as u64);
        return errors;
    }
    if entered > 0 {
        counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Entered.as_str())
            .increment(entered);
    }
    if left > 0 {
        counter!(OUTPUT_MEMBERSHIP_CHANGES_EMITTED, "status" => MembershipStatus::Left.as_str())
            .increment(left);
    }
    0
}

/// Build the first-hop cascade messages for each membership change. Empty when the gate is off or
/// the slice is empty, so the off path allocates nothing. Must be called before `changes` is moved
/// into `produce_membership`. `source_offset` is informational only.
pub(crate) fn first_cascades(
    merge: &MergeWorkerDeps,
    changes: &[CohortMembershipChange],
    source_offset: i64,
) -> Vec<CascadeMessage> {
    if !merge.cascade.enabled || changes.is_empty() {
        return Vec::new();
    }
    changes
        .iter()
        .map(|change| first_cascade(change.clone(), source_offset))
        .collect()
}

/// Produce cascade messages and await acks. Returns the failed-ack count (`0` when empty or fully
/// acked). The caller owns the recovery posture: the event path holds the offset; the sweep/merge
/// paths drop (at-most-once). Shared by the first-hop leg and onward-hop consumer legs.
pub(crate) async fn produce_cascades(
    merge: &MergeWorkerDeps,
    cascades: Vec<CascadeMessage>,
) -> usize {
    if cascades.is_empty() {
        return 0;
    }
    let acks = merge.cascade_sink.produce(cascades).await;
    let errors = acks.iter().filter(|result| result.is_err()).count();
    if errors > 0 {
        counter!(CASCADE_PRODUCE_ERRORS_TOTAL).increment(errors as u64);
    }
    errors
}

#[derive(Default)]
struct EventEffects {
    changes: Vec<CohortMembershipChange>,
    schedules: Vec<(Stage1Key, i64)>,
    re_keys: Vec<CohortStreamEvent>,
}

#[allow(clippy::too_many_arguments)]
async fn handle_event(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    event: &CohortStreamEvent,
    last_updated: &str,
    partition_count: u32,
    person_memo: &mut PersonMemo,
    event_name_gating: EventNameGating,
) -> EventEffects {
    let snapshot = catalog.load();
    let generation = snapshot.generation();
    let Some(team_filters) = snapshot.team(TeamId(event.team_id)) else {
        counter!(STAGE1_EVENTS_SKIPPED, "reason" => SkipReason::NoTeamFilters.as_str())
            .increment(1);
        return EventEffects::default();
    };
    let filters: &TeamFilters = team_filters;

    let resolved: Cow<'_, CohortStreamEvent> =
        match redirect_for_tombstone(partition_id, handle, event, partition_count).await {
            Redirected::Process(event) => event,
            Redirected::ReKey(re_keyed) => {
                return EventEffects {
                    re_keys: vec![re_keyed],
                    ..EventEffects::default()
                }
            }
        };

    let started = Instant::now();
    let result = process_event_offloaded(
        partition_id,
        handle,
        filters,
        generation,
        &resolved,
        person_memo,
        event_name_gating,
    )
    .await;
    histogram!(STAGE1_EVENT_PROCESS_DURATION).record(started.elapsed().as_secs_f64());

    match result {
        Ok(outcome) => {
            if let Some(reason) = outcome.skipped {
                counter!(STAGE1_EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                return EventEffects::default();
            }
            counter!(STAGE1_EVENTS_PROCESSED).increment(1);
            let mut changes = Vec::new();
            for transition in &outcome.transitions {
                if let Some(kind) = transition_metric_label(filters, transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
                changes.extend(map_transition(filters, transition, last_updated));
            }
            match compose_stage2(
                partition_id,
                handle,
                filters,
                &outcome.transitions,
                outcome.event_ms,
                last_updated,
            )
            .await
            {
                Ok(stage2_changes) => changes.extend(stage2_changes),
                Err(error) => warn!(
                    partition_id,
                    team_id = event.team_id,
                    error = %error,
                    "stage 2 composition failed; skipping (self-heals on the person's next event)",
                ),
            }
            EventEffects {
                changes,
                schedules: outcome.schedules,
                re_keys: Vec::new(),
            }
        }
        Err(error) => {
            counter!(STAGE1_EVENTS_SKIPPED, "reason" => "store_error").increment(1);
            warn!(
                partition_id,
                team_id = event.team_id,
                error = %error,
                "stage 1 store error; skipping event without holding the offset",
            );
            EventEffects::default()
        }
    }
}

enum Redirected<'a> {
    Process(Cow<'a, CohortStreamEvent>),
    ReKey(CohortStreamEvent),
}

async fn redirect_for_tombstone<'a>(
    partition_id: u16,
    handle: &StoreHandle,
    event: &'a CohortStreamEvent,
    partition_count: u32,
) -> Redirected<'a> {
    let Ok(person_id) = Uuid::parse_str(&event.person_id) else {
        return Redirected::Process(Cow::Borrowed(event));
    };
    let resolution = match tombstone_redirect::resolve_offloaded(
        handle,
        partition_id,
        TeamId(event.team_id),
        person_id,
        partition_count,
    )
    .await
    {
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
            if event.redirect_hops >= tombstone_redirect::MAX_CROSS_PARTITION_REDIRECT_HOPS {
                counter!(MERGE_REDIRECT_HOP_CAPPED_TOTAL).increment(1);
                warn!(
                    partition_id,
                    team_id = event.team_id,
                    %target_person,
                    %origin,
                    hops = event.redirect_hops,
                    "cross-partition redirect hop cap hit (corrupt tombstone cycle?); processing inline at the best-known target",
                );
                return Redirected::Process(Cow::Owned(rewrite_to(event, target_person, origin)));
            }
            let mut re_keyed = rewrite_to(event, target_person, origin);
            re_keyed.redirect_hops += 1;
            Redirected::ReKey(re_keyed)
        }
    }
}

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

#[allow(clippy::too_many_arguments)]
async fn handle_sweep(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<Stage1Key>,
    last_updated: &str,
    due_before_ms: i64,
) {
    let mut popped: Vec<(Stage1Key, i64)> = Vec::new();
    while popped.len() < MAX_SWEEP_KEYS_PER_PASS {
        let Some(entry) = queue.pop_due(due_before_ms) else {
            break;
        };
        popped.push(entry);
    }
    if popped.is_empty() {
        return;
    }

    let mut by_team: BTreeMap<u64, Vec<Stage1Key>> = BTreeMap::new();
    for &(key, _) in &popped {
        by_team.entry(key.team_id).or_default().push(key);
    }

    let snapshot = catalog.load();
    let mut changes = Vec::new();
    let mut results = Vec::new();
    let mut drops: Vec<SweepDropReason> = Vec::new();
    for (team_id, keys) in &by_team {
        let Some(filters) = snapshot.team(TeamId(*team_id as i32)) else {
            drops.extend(std::iter::repeat_n(SweepDropReason::TeamDrift, keys.len()));
            continue;
        };
        let filters: &TeamFilters = filters;
        // Prefetch the team's states in bounded chunks so no single read op spans the whole wave. A
        // read failure anywhere in the team reschedules the whole team's keys and applies none of it
        // (the per-team retry semantics), so gather every chunk before evicting.
        let mut values: Vec<Option<Vec<u8>>> = Vec::with_capacity(keys.len());
        let mut read_failed = false;
        for chunk in keys.chunks(SWEEP_MULTI_GET_CHUNK) {
            // Maintenance lane: the permit rotates between chunks so no single read op spans the whole
            // wave, keeping each op short against the shutdown grace and fair against event reads.
            match handle
                .multi_get_stage1(chunk.to_vec(), ReadLane::Maintenance)
                .await
            {
                Ok(chunk_values) => values.extend(chunk_values),
                Err(error) => {
                    warn!(
                        partition_id,
                        team_id,
                        error = %error,
                        "sweep state read failed; rescheduling the team's keys for retry",
                    );
                    reschedule_team(queue, &popped, *team_id);
                    read_failed = true;
                    break;
                }
            }
        }
        if read_failed {
            continue;
        }

        let evictions = sweep_evict(filters, keys, values, due_before_ms);
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

    if !changes.is_empty() {
        let errors = produce_membership(sink, changes).await;
        if errors > 0 {
            warn!(
                partition_id,
                errors,
                "sweep produce to cohort_membership_changed_shadow failed; rescheduling for replay",
            );
            reschedule_all(queue, &popped);
            return;
        }
    }

    if !results.is_empty() {
        let mut staged = StagedBatch::default();
        for result in &results {
            match &result.action {
                EvictionAction::Write(bytes) => staged.put_stage1(&result.key, bytes),
                EvictionAction::Delete => {
                    staged.delete_stage1(&result.key);
                    staged.merge_person_index(
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
        let written = handle.commit(staged).await;
        if let Err(error) = written {
            warn!(
                partition_id,
                error = %error,
                "sweep state write failed; rescheduling popped keys to retry the eviction",
            );
            reschedule_all(queue, &popped);
            return;
        }

        for result in &results {
            if let Some(deadline) = result.reschedule {
                queue.schedule(result.key, deadline);
            }
            counter!(SWEEP_KEYS_EVICTED_TOTAL, "variant" => result.variant.as_str()).increment(1);
        }
    }

    for reason in &drops {
        counter!(SWEEP_KEYS_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
    }

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
        let Some(filters) = snapshot.team(TeamId(*team_id as i32)) else {
            continue;
        };
        let filters: &TeamFilters = filters;
        match compose_stage2(
            partition_id,
            handle,
            filters,
            transitions,
            due_before_ms,
            last_updated,
        )
        .await
        {
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

    // Only Stage 2 membership changes cascade; single-leaf evictions self-heal on the referrer's next event.
    let cascades = first_cascades(merge, &stage2_changes, 0);
    let errors = produce_membership(sink, stage2_changes).await;
    if errors > 0 {
        warn!(
            partition_id,
            errors,
            "sweep stage 2 produce to cohort_membership_changed_shadow failed; dropping (cf_stage2 already committed, at-most-once)",
        );
        return;
    }
    let cascade_errors = produce_cascades(merge, cascades).await;
    if cascade_errors > 0 {
        warn!(
            partition_id,
            errors = cascade_errors,
            "sweep cascade produce failed; dropping (at-most-once). Recovery depends on each referrer being re-evaluated on its next event; the sweep does not re-evaluate cohort-ref shapes with no behavioral leaf",
        );
    }
}

/// Re-seed the per-worker [`EvictionQueue`] from `cf_stage1`, scheduling every behavioral key on its
/// stored deadline. Skips `PersonProperty` variants (no time-based eviction) and `i64::MAX` deadlines
/// (permanent). Corrupt records are counted and skipped — the event path re-derives them. A scan error
/// stops early; new events reschedule any missing keys.
async fn rebuild_eviction_queue(
    partition_id: u16,
    handle: &StoreHandle,
    queue: &mut EvictionQueue<Stage1Key>,
) {
    let mut cursor: Option<Vec<u8>> = None;
    let mut rebuilt: u64 = 0;
    loop {
        // Maintenance lane inside the facade: the boot rebuild scans off the runtime threads.
        let page = match handle
            .scan_stage1(partition_id, cursor.clone(), REBUILD_SCAN_PAGE)
            .await
        {
            Ok(page) => page,
            Err(err) => {
                warn!(
                    partition_id,
                    error = %err,
                    "durable restore: cf_stage1 scan failed; eviction queue may be incomplete",
                );
                break;
            }
        };
        let page_len = page.len();
        let next_cursor = page.last().map(|(k, _)| k.encode().to_vec());
        for (key, value) in page {
            match StatefulRecord::decode(&value) {
                // Use the same scheduling policy as the event path to prevent drift.
                Ok(record) => {
                    if let Some(deadline) = schedule_deadline(&record.state) {
                        queue.schedule(key, deadline);
                        rebuilt += 1;
                    }
                }
                Err(_) => counter!(STAGE1_STATE_DECODE_ERROR).increment(1),
            }
        }
        cursor = next_cursor;
        if page_len < REBUILD_SCAN_PAGE {
            break;
        }
        // Workers re-seed concurrently on restart; yield between pages so the boot scan doesn't
        // saturate the runtime before the consume loop starts.
        tokio::task::yield_now().await;
    }
    if rebuilt > 0 {
        counter!(EVICTION_QUEUE_REBUILT_KEYS_TOTAL, "partition" => partition_id.to_string())
            .increment(rebuilt);
        info!(
            partition_id,
            rebuilt, "durable restore: re-seeded eviction queue from cf_stage1",
        );
    }
}

fn reschedule_all(queue: &mut EvictionQueue<Stage1Key>, popped: &[(Stage1Key, i64)]) {
    for &(key, deadline) in popped {
        queue.schedule(key, deadline);
    }
}

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

pub(crate) fn transition_metric_label(
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
// The tests seed and assert against the store directly through `CohortStore` (the sanctioned
// direct-store surface for tests) while driving the workers through the `StoreHandle` facade.
#[allow(clippy::disallowed_methods)]
mod tombstone_redirect_tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::json;
    use tempfile::TempDir;
    use tokio::sync::mpsc;

    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::producer::{
        CaptureCascadeSink, CaptureSink, CaptureStreamEventSink, CaptureTransferSink,
    };
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::stage2::state::Stage2State;
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, TombstoneKey,
    };
    use crate::workers::merge_path::TransferRetryPolicy;
    use crate::workers::CascadeConfig;

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

    /// Wrap a test store in the default `All` operating point (permits 16/6) so the workers and the
    /// direct `handle_event` calls exercise the same blocking-pool transport production uses.
    fn test_handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
    }

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
            redirect_hops: 0,
        }
    }

    fn cross_partition_pair() -> (Uuid, u16, Uuid) {
        let p_old = Uuid::from_u128(1);
        let partition_id = partition_of(TeamId(TEAM), &p_old, COHORT_PARTITION_COUNT) as u16;
        let p_new = (10u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 != partition_id)
            .expect("some uuid hashes off p_old's partition");
        (p_old, partition_id, p_new)
    }

    fn merge_deps_with(stream_sink: CaptureStreamEventSink) -> Arc<MergeWorkerDeps> {
        Arc::new(MergeWorkerDeps {
            transfer_sink: Arc::new(CaptureTransferSink::new()),
            stream_event_sink: Arc::new(stream_sink),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(crate::producer::CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: crate::workers::CascadeConfig::default(),
            partition_count: COHORT_PARTITION_COUNT,
        })
    }

    /// Deps with the `stage2_orphan_gc_enabled` kill-switch set to `stage2_orphan_gc_enabled`.
    fn merge_deps_stage2_gc(stage2_orphan_gc_enabled: bool) -> Arc<MergeWorkerDeps> {
        Arc::new(MergeWorkerDeps {
            transfer_sink: Arc::new(CaptureTransferSink::new()),
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled,
            cascade_sink: Arc::new(crate::producer::CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: crate::workers::CascadeConfig::default(),
            partition_count: COHORT_PARTITION_COUNT,
        })
    }

    /// Deps with a captured cascade sink and the cascade gate set to `enabled`.
    fn merge_deps_cascade(cascade_sink: CaptureCascadeSink, enabled: bool) -> Arc<MergeWorkerDeps> {
        Arc::new(MergeWorkerDeps {
            transfer_sink: Arc::new(CaptureTransferSink::new()),
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(cascade_sink),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: CascadeConfig {
                enabled,
                depth_cap: 8,
                fanout_cap: 1000,
            },
            partition_count: COHORT_PARTITION_COUNT,
        })
    }

    /// Run one event that flips cohort 1 through a worker, returning the partition and its tracker.
    async fn run_flip(
        store: &CohortStore,
        merge: Arc<MergeWorkerDeps>,
        membership: &CaptureSink,
        person: Uuid,
    ) -> (u16, Arc<OffsetTracker>) {
        let partition_id = partition_of(TeamId(TEAM), &person, COHORT_PARTITION_COUNT) as u16;
        let tracker = Arc::new(OffsetTracker::new());
        run_batch(
            partition_id,
            store,
            person_catalog(),
            membership,
            &tracker,
            merge,
            1,
            vec![ShuffleMessage::Event {
                event: Box::new(person_event(person, "u@p.com", 5, 0)),
                cse_offset: 0,
            }],
        )
        .await;
        (partition_id, tracker)
    }

    #[tokio::test]
    async fn event_flip_with_cascade_on_produces_a_depth_one_first_cascade() {
        let (_dir, store) = temp_store();
        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (partition_id, tracker) = run_flip(
            &store,
            merge_deps_cascade(cascade.clone(), true),
            &membership,
            Uuid::from_u128(0x5A1CE),
        )
        .await;

        assert_eq!(membership.changes().len(), 1, "alice entered cohort 1");
        let cascades = cascade.messages();
        assert_eq!(cascades.len(), 1, "one first-hop cascade for the flip");
        assert_eq!(cascades[0].change.cohort_id, 1);
        assert_eq!(cascades[0].depth, 1);
        assert_eq!(cascades[0].cascade_chain, vec![1]);
        assert_eq!(cascades[0].originating_cohort_id, 1);
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            Some(&1),
            "the acked two-topic produce releases the events offset",
        );
    }

    #[tokio::test]
    async fn event_flip_with_cascade_off_produces_no_cascade() {
        let (_dir, store) = temp_store();
        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::new();
        let (partition_id, tracker) = run_flip(
            &store,
            merge_deps_cascade(cascade.clone(), false),
            &membership,
            Uuid::from_u128(0x5A1CF),
        )
        .await;

        assert_eq!(
            membership.changes().len(),
            1,
            "the flip still emits membership"
        );
        assert!(
            cascade.messages().is_empty(),
            "gate off: no cascade produced"
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            Some(&1),
        );
    }

    #[tokio::test]
    async fn cascade_produce_failure_holds_the_events_batch() {
        let (_dir, store) = temp_store();
        let membership = CaptureSink::new();
        let cascade = CaptureCascadeSink::failing_always();
        let (partition_id, tracker) = run_flip(
            &store,
            merge_deps_cascade(cascade.clone(), true),
            &membership,
            Uuid::from_u128(0x5A1D0),
        )
        .await;

        assert_eq!(
            membership.changes().len(),
            1,
            "membership is the first leg and acked before the cascade leg",
        );
        assert!(cascade.messages().is_empty(), "the cascade produce failed");
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            None,
            "a failed cascade produce holds the events offset for replay",
        );
    }

    #[allow(clippy::too_many_arguments)]
    async fn run_batch(
        partition_id: u16,
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
        membership: &CaptureSink,
        tracker: &Arc<OffsetTracker>,
        merge: Arc<MergeWorkerDeps>,
        dispatched: i64,
        batch: Vec<ShuffleMessage>,
    ) {
        let (tx, rx) = mpsc::channel(4);
        let rx = MeteredReceiver::unmetered(rx);
        let worker = Stage1Worker::spawn(
            partition_id,
            rx,
            test_handle(store),
            catalog,
            Arc::new(membership.clone()),
            tracker.clone(),
            merge,
            false,
        );
        tracker.mark_dispatched(partition_id as i32, dispatched);
        tx.send(batch).await.unwrap();
        drop(tx);
        worker.join().await.unwrap();
    }

    async fn run_one_straggler(
        partition_id: u16,
        store: &CohortStore,
        catalog: Arc<CatalogHandle>,
        membership: &CaptureSink,
        tracker: &Arc<OffsetTracker>,
        merge: Arc<MergeWorkerDeps>,
        event: CohortStreamEvent,
    ) {
        run_batch(
            partition_id,
            store,
            catalog,
            membership,
            tracker,
            merge,
            1,
            vec![ShuffleMessage::Event {
                event: Box::new(event),
                cse_offset: 0,
            }],
        )
        .await;
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

    #[tokio::test]
    async fn inline_redirect_folds_into_redirect_dedup_origin_not_the_main_map() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);

        let p_new = Uuid::from_u128(2);
        let partition_id = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as u16;
        let p_old = Uuid::from_u128(1);
        write_tombstone(&store, partition_id, p_old, p_new);

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

        let straggler = person_event(p_old, "u@p.com", 5, 101);
        let effects = handle_event(
            partition_id,
            &test_handle(&store),
            &catalog,
            &straggler,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;

        assert_eq!(effects.changes.len(), 1, "the straggler entered P_new");
        assert_eq!(effects.changes[0].person_id, p_new.to_string());
        assert_eq!(effects.changes[0].status, MembershipStatus::Entered);

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

        assert!(store
            .get_stage1(&stage1_key(partition_id, lsk, p_old))
            .unwrap()
            .is_none());
    }

    #[tokio::test]
    async fn cross_partition_redirect_re_keys_the_straggler_to_the_target() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let (p_old, partition_id, p_new) = cross_partition_pair();
        write_tombstone(&store, partition_id, p_old, p_new);

        let stream_sink = CaptureStreamEventSink::new();
        let membership = CaptureSink::new();
        let tracker = Arc::new(OffsetTracker::new());
        run_one_straggler(
            partition_id,
            &store,
            catalog,
            &membership,
            &tracker,
            merge_deps_with(stream_sink.clone()),
            person_event(p_old, "u@p.com", 5, 9),
        )
        .await;

        let produced = stream_sink.events();
        assert_eq!(produced.len(), 1, "one re-keyed event produced");
        let re_keyed = &produced[0];
        assert_eq!(
            re_keyed.person_id,
            p_new.to_string(),
            "person rewritten to the target",
        );
        assert_eq!(
            re_keyed.redirected_from,
            Some(p_old.to_string()),
            "first origin stamped",
        );
        assert_eq!(
            (re_keyed.source_partition, re_keyed.source_offset),
            (5, 9),
            "original source coords preserved for the target's redirect_dedup",
        );
        assert_eq!(re_keyed.redirect_hops, 1, "one produced hop");

        assert!(membership.changes().is_empty(), "no local processing");
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, p_old))
                .unwrap()
                .is_none(),
            "no state written for P_old in the source slice",
        );
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, p_new))
                .unwrap()
                .is_none(),
            "no state written for P_new in the source slice",
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            Some(&1),
            "the acked re-key produce releases the events offset",
        );
    }

    #[tokio::test]
    async fn re_key_produce_failure_holds_the_events_offset_until_redelivery_succeeds() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let (p_old, partition_id, p_new) = cross_partition_pair();
        write_tombstone(&store, partition_id, p_old, p_new);
        let membership = CaptureSink::new();
        let tracker = Arc::new(OffsetTracker::new());

        let failing = CaptureStreamEventSink::failing_always();
        run_one_straggler(
            partition_id,
            &store,
            catalog.clone(),
            &membership,
            &tracker,
            merge_deps_with(failing.clone()),
            person_event(p_old, "u@p.com", 5, 9),
        )
        .await;
        assert!(
            failing.events().is_empty(),
            "the failed flush recorded nothing"
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            None,
            "the failed produce holds the events offset",
        );

        let succeeding = CaptureStreamEventSink::new();
        run_one_straggler(
            partition_id,
            &store,
            catalog,
            &membership,
            &tracker,
            merge_deps_with(succeeding.clone()),
            person_event(p_old, "u@p.com", 5, 9),
        )
        .await;
        let produced = succeeding.events();
        assert_eq!(
            produced.len(),
            1,
            "the redelivery re-derives and produces the re-key"
        );
        assert_eq!(produced[0].person_id, p_new.to_string());
        assert_eq!(
            (produced[0].source_partition, produced[0].source_offset),
            (5, 9),
            "the re-derived copy carries the original source coords (dedupable at the target)",
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            Some(&1),
            "the later success releases the held offset",
        );
    }

    #[tokio::test]
    async fn membership_produce_failure_in_a_mixed_batch_withholds_the_re_key_and_the_mark() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let (p_old, partition_id, p_new) = cross_partition_pair();
        write_tombstone(&store, partition_id, p_old, p_new);
        let alice = (100u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TeamId(TEAM), p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .expect("some uuid hashes onto p_old's partition");
        let batch = || {
            vec![
                ShuffleMessage::Event {
                    event: Box::new(person_event(alice, "u@p.com", 5, 0)),
                    cse_offset: 0,
                },
                ShuffleMessage::Event {
                    event: Box::new(person_event(p_old, "u@p.com", 5, 9)),
                    cse_offset: 1,
                },
            ]
        };

        let membership = CaptureSink::failing_first(1);
        let stream_sink = CaptureStreamEventSink::new();
        let tracker = Arc::new(OffsetTracker::new());

        run_batch(
            partition_id,
            &store,
            catalog.clone(),
            &membership,
            &tracker,
            merge_deps_with(stream_sink.clone()),
            2,
            batch(),
        )
        .await;
        assert!(
            membership.changes().is_empty(),
            "the failed flush recorded nothing"
        );
        assert!(
            stream_sink.events().is_empty(),
            "the membership failure withholds the straggler's re-key produce",
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            None,
            "the membership failure holds the whole sub-batch's offset",
        );

        run_batch(
            partition_id,
            &store,
            catalog,
            &membership,
            &tracker,
            merge_deps_with(stream_sink.clone()),
            2,
            batch(),
        )
        .await;
        assert!(
            membership.changes().is_empty(),
            "the replay emits no duplicate membership change (the failed flip stays dropped, at-most-once)",
        );
        let produced = stream_sink.events();
        assert_eq!(produced.len(), 1, "the replay produces the re-key once");
        assert_eq!(produced[0].person_id, p_new.to_string());
        assert_eq!(
            (produced[0].source_partition, produced[0].source_offset),
            (5, 9),
            "the re-key carries the straggler's original source coords",
        );
        assert_eq!(
            tracker.committable_offsets().get(&(partition_id as i32)),
            Some(&2),
            "the acked replay releases the offset past both events",
        );
    }

    #[tokio::test]
    async fn re_keyed_event_folds_into_p_new_exactly_once_via_redirect_dedup() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let (p_old, source_partition, p_new) = cross_partition_pair();
        let target_partition = partition_of(TeamId(TEAM), &p_new, COHORT_PARTITION_COUNT) as u16;
        assert_ne!(source_partition, target_partition);
        write_tombstone(&store, source_partition, p_old, p_new);
        let handle = test_handle(&store);

        let straggler = person_event(p_old, "u@p.com", 5, 9);
        let mut effects = handle_event(
            source_partition,
            &handle,
            &catalog,
            &straggler,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;
        assert!(effects.changes.is_empty());
        assert!(effects.schedules.is_empty());
        assert_eq!(effects.re_keys.len(), 1);
        let re_keyed = effects.re_keys.pop().unwrap();

        let effects = handle_event(
            target_partition,
            &handle,
            &catalog,
            &re_keyed,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;
        assert_eq!(effects.changes.len(), 1, "folds into P_new exactly once");
        assert_eq!(effects.changes[0].person_id, p_new.to_string());
        assert_eq!(effects.changes[0].status, MembershipStatus::Entered);
        assert!(effects.re_keys.is_empty(), "no further hop: P_new is live");

        let folded = StatefulRecord::decode(
            &store
                .get_stage1(&stage1_key(target_partition, lsk, p_new))
                .unwrap()
                .expect("P_new state written in the target slice"),
        )
        .unwrap();
        assert!(
            folded.redirect_dedup[&p_old].is_replay(5, 9),
            "the fold recorded the original source coords under redirect_dedup[origin]",
        );
        assert!(
            !folded.applied_offsets.is_replay(5, 9),
            "the main map stays untouched by a redirected straggler",
        );

        let dup = handle_event(
            target_partition,
            &handle,
            &catalog,
            &re_keyed,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;
        assert!(dup.changes.is_empty(), "the duplicate folds zero times");
        assert!(dup.re_keys.is_empty());
    }

    #[tokio::test]
    async fn hop_capped_redirect_processes_inline_at_the_best_known_target() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let (p_old, partition_id, p_new) = cross_partition_pair();
        write_tombstone(&store, partition_id, p_old, p_new);

        let straggler = CohortStreamEvent {
            redirect_hops: tombstone_redirect::MAX_CROSS_PARTITION_REDIRECT_HOPS,
            ..person_event(p_old, "u@p.com", 5, 9)
        };
        let effects = handle_event(
            partition_id,
            &test_handle(&store),
            &catalog,
            &straggler,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;

        assert!(effects.re_keys.is_empty(), "no re-produce at the cap");
        assert_eq!(effects.changes.len(), 1, "processed inline instead");
        assert_eq!(effects.changes[0].person_id, p_new.to_string());

        let folded = StatefulRecord::decode(
            &store
                .get_stage1(&stage1_key(partition_id, lsk, p_new))
                .unwrap()
                .expect("the degraded fold writes P_new state in the local slice"),
        )
        .unwrap();
        assert!(
            folded.redirect_dedup[&p_old].is_replay(5, 9),
            "the inline degrade still dedups by the chain origin",
        );
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, p_old))
                .unwrap()
                .is_none(),
            "no P_old state rebuilt",
        );
    }

    #[tokio::test]
    async fn no_tombstone_processes_the_event_normally() {
        let (_dir, store) = temp_store();
        let catalog = person_catalog();
        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let alice = Uuid::from_u128(3);
        let partition_id = partition_of(TeamId(TEAM), &alice, COHORT_PARTITION_COUNT) as u16;

        let event = person_event(alice, "u@p.com", 5, 0);
        let effects = handle_event(
            partition_id,
            &test_handle(&store),
            &catalog,
            &event,
            "ts",
            COHORT_PARTITION_COUNT,
            &mut PersonMemo::disabled(),
            EventNameGating::Disabled,
        )
        .await;
        assert_eq!(effects.changes.len(), 1);
        assert_eq!(effects.changes[0].person_id, alice.to_string());
        assert!(
            store
                .get_stage1(&stage1_key(partition_id, lsk, alice))
                .unwrap()
                .is_some(),
            "alice's own state was written",
        );
    }

    /// The `MergeCfGc` arm runs the `cf_stage2` orphan GC only when `stage2_orphan_gc_enabled`: a
    /// SingleLeaf cohort's row (an orphan) survives with the kill-switch off and is reclaimed with it on.
    #[tokio::test]
    async fn merge_cf_gc_arm_runs_stage2_orphan_gc_only_when_enabled() {
        for (enabled, expect_present) in [(false, true), (true, false)] {
            let (_dir, store) = temp_store();
            let person = Uuid::from_u128(0xC0FFEE);
            let partition_id = partition_of(TeamId(TEAM), &person, COHORT_PARTITION_COUNT) as u16;
            let orphan = Stage2Key {
                partition_id,
                team_id: TEAM as u64,
                cohort_id: 1, // SingleLeaf in person_catalog → an orphan
                person_id: person,
            };
            store
                .write_batch(|b| {
                    b.put_stage2(
                        &orphan,
                        &Stage2State {
                            in_cohort: true,
                            last_evaluated_at_ms: 1,
                        }
                        .encode(),
                    )
                })
                .unwrap();

            let membership = CaptureSink::new();
            let tracker = Arc::new(OffsetTracker::new());
            run_batch(
                partition_id,
                &store,
                person_catalog(),
                &membership,
                &tracker,
                merge_deps_stage2_gc(enabled),
                1,
                vec![ShuffleMessage::MergeCfGc {
                    marker_cutoff_ms: 0,
                    tombstone_cutoff_ms: 0,
                }],
            )
            .await;

            assert_eq!(
                store.get_stage2(&orphan).unwrap().is_some(),
                expect_present,
                "MergeCfGc arm runs the orphan GC iff enabled (enabled={enabled})",
            );
        }
    }
}
