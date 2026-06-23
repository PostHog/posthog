//! Merge-protocol worker paths: the produce/track I/O around the drain/apply handlers in
//! [`crate::merge`].
//!
//! [`handle_merge`] drains a `PersonMergeEvent` on P_old's worker and owns the transfer produce;
//! [`handle_apply`] applies a `MergeStateTransfer` on P_new's worker. Both produce their own
//! membership output and mark their own [`OffsetTracker`].

use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono_tz::UTC;
use metrics::{counter, gauge, histogram};
use tracing::{debug, warn};

use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{TeamFiltersBuilder, TeamId};
use crate::merge::apply_handler::{handle_transfer, ApplyOutcome};
use crate::merge::drain_handler::{handle_merge_event, DrainOutcome};
use crate::merge::transfer::{MergeStateTransfer, PendingTransfer, PersonMergeEvent};
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, MERGE_APPLY_DURATION_SECONDS,
    MERGE_DRAIN_DURATION_SECONDS, MERGE_HELD_OFFSET_GAUGE, MERGE_OUTBOX_CLEAR_FAILURE_TOTAL,
    MERGE_PENDING_TRANSFERS_GAUGE, MERGE_TRANSFERS_SKIPPED_EMPTY_TOTAL,
    MERGE_TRANSFER_FORWARDS_TOTAL, MERGE_TRANSFER_PRODUCE_FAILURE_TOTAL, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::partitions::partitioner::COHORT_PARTITION_COUNT;
use crate::producer::{
    map_transition, CaptureCascadeSink, CaptureStreamEventSink, CaptureTransferSink, CascadeSink,
    CohortMembershipChange, MembershipSink, StreamEventSink, TransferSink,
};
use crate::stage1::key::Stage1Key;
use crate::stage1::transition::LeafTransition;
use crate::store::{CohortStore, PendingTransferKey};
use crate::sweep::EvictionQueue;
use crate::workers::stage2_path::compose_stage2;
use crate::workers::worker::{
    first_cascades, produce_cascades, produce_membership, transition_metric_label,
};

/// Inline bounded backoff for the transfer produce.
///
/// Worst-case worker hold = `(max_retries + 1)` produce attempts, each fast-failing at the transfer
/// sink's `message.timeout.ms`, plus the sum of the backoff sleeps. With the defaults — 6 attempts ×
/// the 2 s transfer timeout ([`crate::config::Config::merge_transfer_message_timeout_ms`]) + ≈15.5 s
/// of backoff ≈ **27.5 s** — that fits the 30 s graceful-shutdown window (the binding constraint
/// here, tighter than the 60 s liveness deadline), and only because the transfer sink uses its own
/// short timeout.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TransferRetryPolicy {
    /// Retries after the initial attempt (total attempts = `max_retries + 1`).
    pub max_retries: u32,
    pub base: Duration,
    pub cap: Duration,
}

impl Default for TransferRetryPolicy {
    fn default() -> Self {
        Self {
            max_retries: 5,
            base: Duration::from_millis(500),
            cap: Duration::from_secs(8),
        }
    }
}

impl TransferRetryPolicy {
    /// The pause before 1-based retry `attempt`: `base * 2^(attempt-1)`, capped at `cap`.
    fn backoff(&self, attempt: u32) -> Duration {
        self.base
            .saturating_mul(2u32.saturating_pow(attempt.saturating_sub(1)))
            .min(self.cap)
    }
}

/// Default merge-CF GC per-tick, per-CF scan cap when the deps are built without explicit config
/// (tests). Mirrors `Config::merge_gc_scan_limit`'s default.
pub const DEFAULT_MERGE_GC_SCAN_LIMIT: usize = 10_000;

/// Cascade depth/fan-out caps and the master gate. With `enabled` false the cascade transport is
/// inert (the producer builds nothing, the consumer drains without re-evaluating).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CascadeConfig {
    pub enabled: bool,
    /// An incoming cascade at `depth >= this` drops its outgoing hop.
    pub depth_cap: u8,
    /// Max referrer re-evaluations per upstream flip; the remainder self-heals.
    pub fanout_cap: usize,
}

impl Default for CascadeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            depth_cap: 8,
            fanout_cap: 1000,
        }
    }
}

pub struct MergeWorkerDeps {
    pub transfer_sink: Arc<dyn TransferSink>,
    pub stream_event_sink: Arc<dyn StreamEventSink>,
    pub merge_tracker: Arc<OffsetTracker>,
    pub transfer_tracker: Arc<OffsetTracker>,
    pub retry: TransferRetryPolicy,
    /// Max keys scanned (and at most deleted) per merge CF, per partition, per GC tick. Reused as the
    /// `cf_stage2` orphan-GC page cap.
    pub gc_scan_limit: usize,
    /// Whether the `cf_stage2` orphan GC pass runs on each merge-GC tick (kill-switch, default on).
    pub stage2_orphan_gc_enabled: bool,
    /// Sink for the internal `cohort_cascade_events` topic (a no-op when the gate is off).
    pub cascade_sink: Arc<dyn CascadeSink>,
    /// Isolated from the merge/transfer trackers so cascade-path lag is observable separately.
    pub cascade_tracker: Arc<OffsetTracker>,
    pub cascade: CascadeConfig,
    /// Partition count the merge math routes against. Production 64; test lanes lower it. Threaded
    /// from [`crate::config::Config::cohort_partition_count`] so a re-partitioned lane cannot
    /// misroute against a hardcoded literal.
    pub partition_count: u32,
}

impl MergeWorkerDeps {
    pub fn capture() -> Arc<Self> {
        Arc::new(Self {
            transfer_sink: Arc::new(CaptureTransferSink::new()),
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: CascadeConfig::default(),
            partition_count: COHORT_PARTITION_COUNT,
        })
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn handle_merge(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<Stage1Key>,
    last_updated: &str,
    event: &PersonMergeEvent,
    offset: i64,
) {
    let msg_coords = (partition_id as i32, offset);

    // Drain against empty filters when the team is absent to avoid wedging.
    let snapshot = catalog.load();
    let fallback: TeamFilters;
    let filters: &TeamFilters = match snapshot.team(TeamId(event.team_id)) {
        Some(team) => team,
        None => {
            fallback = empty_team_filters();
            &fallback
        }
    };

    let started = Instant::now();
    let outcome = handle_merge_event(
        partition_id,
        store,
        filters,
        event,
        msg_coords,
        queue,
        merge.partition_count,
    );
    histogram!(MERGE_DRAIN_DURATION_SECONDS).record(started.elapsed().as_secs_f64());

    let pending_key = PendingTransferKey {
        partition_id,
        team_id: event.team_id as u64,
        old_person: event.old_person_uuid,
    };
    match outcome {
        Ok(DrainOutcome::FastPath { transitions }) => {
            produce_merge_transitions(
                partition_id,
                store,
                sink,
                merge,
                filters,
                &transitions,
                event.merged_at_ms,
                last_updated,
                offset,
            )
            .await;
            mark_processed(&merge.merge_tracker, partition_id, offset);
        }
        Ok(DrainOutcome::Drained { transfer }) => {
            if transfer.leaves.is_empty() {
                counter!(MERGE_TRANSFERS_SKIPPED_EMPTY_TOTAL).increment(1);
                mark_processed(&merge.merge_tracker, partition_id, offset);
                return;
            }
            produce_and_settle(partition_id, store, merge, &transfer, &pending_key, offset).await;
        }
        Ok(DrainOutcome::AlreadyDrained) => match store.get_pending_transfer(&pending_key) {
            Ok(None) => mark_processed(&merge.merge_tracker, partition_id, offset),
            Ok(Some(bytes)) => match PendingTransfer::decode(&bytes) {
                Ok(pending) => {
                    produce_and_settle(
                        partition_id,
                        store,
                        merge,
                        &pending.transfer,
                        &pending_key,
                        offset,
                    )
                    .await;
                }
                Err(error) => {
                    warn!(
                        partition_id,
                        team_id = event.team_id,
                        old_person = %event.old_person_uuid,
                        error = %error,
                        "pending transfer failed to decode; committing past it (entry left for the redrive to surface)",
                    );
                    mark_processed(&merge.merge_tracker, partition_id, offset);
                }
            },
            Err(error) => {
                // Category A: the outbox read itself failed, so we cannot re-produce the staged
                // transfer this pass and have no other handle on it — a sticky hold redelivers the
                // merge so a later pass (or the next tenure) can resolve it.
                warn!(
                    partition_id,
                    team_id = event.team_id,
                    error = %error,
                    "pending transfer read failed; holding the merge offset for redelivery",
                );
                hold(&merge.merge_tracker, partition_id, offset);
            }
        },
        Ok(DrainOutcome::Skipped(_)) => {
            mark_processed(&merge.merge_tracker, partition_id, offset);
        }
        Err(error) => {
            // Category A: the drain's atomic `write_batch` failed, so it left no
            // `cf_merge_drains_applied` marker and produced no transfer — nothing recovers this but a
            // replay of the merge message. A sticky hold redelivers it; advancing past it would drop
            // the merge silently.
            warn!(
                partition_id,
                team_id = event.team_id,
                old_person = %event.old_person_uuid,
                error = %error,
                "merge drain store error; holding the merge offset for redelivery",
            );
            hold(&merge.merge_tracker, partition_id, offset);
        }
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) async fn handle_apply(
    partition_id: u16,
    store: &CohortStore,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<Stage1Key>,
    last_updated: &str,
    transfer: &MergeStateTransfer,
    offset: i64,
) {
    let transfer_coords = (partition_id as i32, offset);

    let snapshot = catalog.load();
    let fallback: TeamFilters;
    let filters: &TeamFilters = match snapshot.team(TeamId(transfer.team_id)) {
        Some(team) => team,
        None => {
            fallback = empty_team_filters();
            &fallback
        }
    };

    let started = Instant::now();
    let outcome = handle_transfer(
        partition_id,
        store,
        filters,
        transfer,
        transfer_coords,
        queue,
        merge.partition_count,
    );
    histogram!(MERGE_APPLY_DURATION_SECONDS).record(started.elapsed().as_secs_f64());

    match outcome {
        Ok(ApplyOutcome::Applied { transitions }) => {
            produce_merge_transitions(
                partition_id,
                store,
                sink,
                merge,
                filters,
                &transitions,
                transfer.merged_at_ms,
                last_updated,
                offset,
            )
            .await;
            mark_processed(&merge.transfer_tracker, partition_id, offset);
        }
        Ok(ApplyOutcome::AlreadyApplied) => {
            mark_processed(&merge.transfer_tracker, partition_id, offset);
        }
        Ok(ApplyOutcome::Forward {
            transfer: forwarded,
        }) => {
            forward_transfer(partition_id, merge, &forwarded, offset).await;
        }
        Ok(ApplyOutcome::HopCapped) => {
            // No state and no marker were written; mark so a corrupt tombstone cycle does not wedge
            // the partition (the counter already fired in the handler).
            mark_processed(&merge.transfer_tracker, partition_id, offset);
        }
        Err(error) => {
            // Category A: the atomic apply `write_batch` failed, so no `cf_merge_applied` marker was
            // written and the Kafka transfer is the last copy of P_old's state (drain already deleted
            // its leaves, the outbox slot was cleared on the produce ack). A sticky hold replays the
            // transfer cleanly; advancing past it would lose the state for good.
            warn!(
                partition_id,
                team_id = transfer.team_id,
                new_person = %transfer.new_person_uuid,
                error = %error,
                "transfer apply store error; holding the transfer offset for redelivery",
            );
            hold(&merge.transfer_tracker, partition_id, offset);
        }
    }
}

/// Forward a re-targeted transfer to the survivor's partition (the raced chained-merge case).
///
/// A **single** produce attempt on the transfer sink (not the inline retry budget — the apply path
/// must not hold the worker): a failed produce holds the transfer offset (no mark) so redelivery
/// re-resolves and re-produces. The forward writes no state, so the hold is self-healing. The
/// transfer offset is marked only after the ack, and the forward is counted post-ack (`re_keyed`).
async fn forward_transfer(
    partition_id: u16,
    merge: &MergeWorkerDeps,
    forwarded: &MergeStateTransfer,
    offset: i64,
) {
    let acks = merge.transfer_sink.produce(vec![forwarded.clone()]).await;
    if !acks.iter().all(Result::is_ok) {
        // Category B: the forward wrote no state and no outbox entry, so the failed produce leaves
        // nothing to redrive — a sticky hold redelivers the transfer, which re-resolves and re-forwards
        // (the survivor's marker dedups any duplicate).
        warn!(
            partition_id,
            team_id = forwarded.team_id,
            old_person = %forwarded.old_person_uuid,
            target = %forwarded.new_person_uuid,
            forward_hops = forwarded.forward_hops,
            "transfer forward produce failed; holding the transfer offset for redelivery",
        );
        hold(&merge.transfer_tracker, partition_id, offset);
        return;
    }
    counter!(MERGE_TRANSFER_FORWARDS_TOTAL, "path" => "re_keyed").increment(1);
    mark_processed(&merge.transfer_tracker, partition_id, offset);
}

const REDRIVE_MAX_ATTEMPTS_PER_TICK: usize = 8;

/// Cap on the pending-transfer scan: a small multiple of the per-tick attempt cap, so the redrive has
/// the next few ticks' worth of work staged without copying the whole outbox each tick.
const SCAN_PENDING_TRANSFERS_LIMIT: usize = REDRIVE_MAX_ATTEMPTS_PER_TICK * 8;

pub(crate) async fn handle_redrive(
    partition_id: u16,
    store: &CohortStore,
    merge: &MergeWorkerDeps,
) {
    let entries =
        match store.scan_pending_transfers(partition_id, None, SCAN_PENDING_TRANSFERS_LIMIT) {
            Ok(entries) => entries,
            Err(error) => {
                warn!(
                    partition_id,
                    error = %error,
                    "pending-transfer redrive scan failed; retrying next tick",
                );
                return;
            }
        };
    // Saturates at the scan limit, so this reflects `min(backlog, SCAN_PENDING_TRANSFERS_LIMIT)` — it
    // still distinguishes an empty outbox from a backed-up one, just not the exact backlog depth.
    gauge!(MERGE_PENDING_TRANSFERS_GAUGE, "partition" => partition_id.to_string())
        .set(entries.len() as f64);

    let mut attempted = 0usize;
    for (key, bytes) in entries {
        if attempted == REDRIVE_MAX_ATTEMPTS_PER_TICK {
            debug!(
                partition_id,
                "redrive tick reached its produce-attempt cap; remaining entries wait for the next tick",
            );
            break;
        }
        let pending = match PendingTransfer::decode(&bytes) {
            Ok(pending) => pending,
            Err(error) => {
                warn!(
                    partition_id,
                    team_id = key.team_id,
                    old_person = %key.old_person,
                    error = %error,
                    "pending transfer failed to decode during redrive; leaving the entry in place",
                );
                continue;
            }
        };
        let team_id = pending.transfer.team_id;
        let old_person = pending.transfer.old_person_uuid;
        attempted += 1;
        let acks = merge.transfer_sink.produce(vec![pending.transfer]).await;
        if !acks.iter().all(Result::is_ok) {
            warn!(
                partition_id,
                team_id,
                old_person = %old_person,
                "redrive transfer produce failed; leaving the entry for the next tick",
            );
            continue;
        }
        if let Err(error) = store.clear_pending_transfer(&key) {
            counter!(MERGE_OUTBOX_CLEAR_FAILURE_TOTAL).increment(1);
            warn!(
                partition_id,
                team_id,
                old_person = %old_person,
                error = %error,
                "outbox clear failed after an acked redrive produce; marking anyway",
            );
        }
        debug_assert_eq!(pending.merge_msg_partition, partition_id as i32);
        mark_processed(&merge.merge_tracker, partition_id, pending.merge_msg_offset);
    }
}

/// Produce `transfer` with inline retry; on ack clear its outbox slot and mark the merge offset.
async fn produce_and_settle(
    partition_id: u16,
    store: &CohortStore,
    merge: &MergeWorkerDeps,
    transfer: &MergeStateTransfer,
    pending_key: &PendingTransferKey,
    offset: i64,
) {
    if !produce_transfer_with_retry(&merge.transfer_sink, transfer, &merge.retry, partition_id)
        .await
    {
        // Category C: deliberately **no** `hold` here. The transfer stays staged in
        // `cf_pending_transfers` and the periodic redrive (`handle_redrive`) owns recovery — it
        // re-produces and then `mark_processed`es `K + 1`. A sticky hold would pin `K` even after the
        // redrive advances past it, wedging the partition on a message the outbox already handles.
        counter!(MERGE_TRANSFER_PRODUCE_FAILURE_TOTAL).increment(1);
        warn!(
            partition_id,
            team_id = transfer.team_id,
            old_person = %transfer.old_person_uuid,
            new_person = %transfer.new_person_uuid,
            "transfer produce exhausted its retry budget; leaving the entry pending and skipping the offset mark",
        );
        return;
    }
    if let Err(error) = store.clear_pending_transfer(pending_key) {
        counter!(MERGE_OUTBOX_CLEAR_FAILURE_TOTAL).increment(1);
        warn!(
            partition_id,
            team_id = transfer.team_id,
            old_person = %transfer.old_person_uuid,
            error = %error,
            "outbox clear failed after an acked transfer produce; committing anyway",
        );
    }
    mark_processed(&merge.merge_tracker, partition_id, offset);
}

/// Produce one transfer, retrying inline with bounded backoff. Returns whether the produce was acked.
async fn produce_transfer_with_retry(
    sink: &Arc<dyn TransferSink>,
    transfer: &MergeStateTransfer,
    retry: &TransferRetryPolicy,
    partition_id: u16,
) -> bool {
    for attempt in 0..=retry.max_retries {
        if attempt > 0 {
            tokio::time::sleep(retry.backoff(attempt)).await;
        }
        let acks = sink.produce(vec![transfer.clone()]).await;
        if acks.iter().all(Result::is_ok) {
            return true;
        }
        debug!(
            partition_id,
            attempt,
            team_id = transfer.team_id,
            old_person = %transfer.old_person_uuid,
            "transfer produce attempt failed",
        );
    }
    false
}

/// Fan transitions into membership output (single-leaf + Stage 2), then produce (at-most-once).
/// `source_offset` seeds each flip's first cascade; both produces drop on failure.
#[allow(clippy::too_many_arguments)]
async fn produce_merge_transitions(
    partition_id: u16,
    store: &CohortStore,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    filters: &TeamFilters,
    transitions: &[LeafTransition],
    merged_at_ms: i64,
    last_updated: &str,
    source_offset: i64,
) {
    if transitions.is_empty() {
        return;
    }
    let mut changes: Vec<CohortMembershipChange> = Vec::new();
    for transition in transitions {
        if let Some(kind) = transition_metric_label(filters, transition) {
            counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
        }
        changes.extend(map_transition(filters, transition, last_updated));
    }
    match compose_stage2(
        partition_id,
        store,
        filters,
        transitions,
        merged_at_ms,
        last_updated,
    ) {
        Ok(stage2_changes) => changes.extend(stage2_changes),
        Err(error) => warn!(
            partition_id,
            error = %error,
            "merge stage 2 composition failed; skipping (self-heals on the person's next event)",
        ),
    }
    if changes.is_empty() {
        return;
    }

    let cascades = first_cascades(merge, &changes, source_offset);
    let errors = produce_membership(sink, changes).await;
    if errors > 0 {
        warn!(
            partition_id,
            errors,
            "merge membership produce failed; dropping (state already committed, at-most-once)",
        );
        return;
    }
    let cascade_errors = produce_cascades(merge, cascades).await;
    if cascade_errors > 0 {
        warn!(
            partition_id,
            errors = cascade_errors,
            "merge cascade produce failed; dropping (at-most-once). Recovery depends on each referrer being re-evaluated on its next event; the sweep does not re-evaluate cohort-ref shapes with no behavioral leaf",
        );
    }
}

fn mark_processed(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    if let MarkOutcome::CappedAheadOfDispatch =
        tracker.mark_processed(partition_id as i32, offset + 1)
    {
        counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
        warn!(
            partition_id,
            next_offset = offset + 1,
            "offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
        );
    }
}

/// Pin the partition's commit floor at the failed message's **own** offset (no `+ 1`, unlike
/// [`mark_processed`]) so Kafka redelivers it instead of a later success leapfrogging it. The hold is
/// sticky for the worker's tenure; emit [`MERGE_HELD_OFFSET_GAUGE`] so the resulting commit-stall is
/// never silent (alert on a sustained non-zero level).
fn hold(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    // Report the resulting floor (an earlier hold may pin a lower offset), not the raw `offset`, so
    // the gauge matches the position Kafka will actually redeliver.
    let floor = tracker.hold(partition_id as i32, offset);
    gauge!(MERGE_HELD_OFFSET_GAUGE, "partition" => partition_id.to_string()).set(floor as f64);
}

/// Fallback for a team absent from the catalog: no cohorts, UTC timezone.
fn empty_team_filters() -> TeamFilters {
    TeamFiltersBuilder::default().freeze(UTC)
}

#[cfg(test)]
mod tests {
    use super::*;
    use envconfig::Envconfig;
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::merge::transfer::TransferLeaf;
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::store::StoreConfig;

    #[test]
    fn default_retry_policy_budget() {
        let policy = TransferRetryPolicy::default();
        assert_eq!(policy.max_retries, 5);
        let backoffs: Vec<Duration> = (1..=policy.max_retries)
            .map(|a| policy.backoff(a))
            .collect();
        assert_eq!(
            backoffs,
            vec![
                Duration::from_millis(500),
                Duration::from_secs(1),
                Duration::from_secs(2),
                Duration::from_secs(4),
                Duration::from_secs(8),
            ],
        );
        let total: Duration = backoffs.iter().sum();
        assert_eq!(total, Duration::from_millis(15_500), "≈15.5 s end to end");
    }

    /// The inline transfer-retry worst case — every produce attempt fast-failing at the dedicated
    /// transfer timeout, plus all backoff sleeps — must stay inside the 30 s graceful-shutdown window
    /// (the binding constraint, tighter than the 60 s liveness deadline). Sourced from the live config
    /// default and the retry-policy default so a drift in *either* trips this test.
    #[test]
    fn inline_transfer_retry_worst_case_fits_the_graceful_shutdown_window() {
        let config = crate::config::Config::init_from_hashmap(&std::collections::HashMap::new())
            .expect("envconfig defaults load");
        let policy = config.transfer_retry_policy();

        // total attempts = initial + retries; each can block for the full transfer message timeout.
        let attempts = policy.max_retries + 1;
        let per_attempt =
            Duration::from_millis(u64::from(config.merge_transfer_message_timeout_ms));
        let produce_block = per_attempt * attempts;

        let backoff: Duration = (1..=policy.max_retries).map(|a| policy.backoff(a)).sum();
        let worst_case = produce_block + backoff;

        // 6 × 2 s + 15.5 s = 27.5 s with the current defaults.
        assert_eq!(worst_case, Duration::from_millis(27_500));

        const GRACEFUL_SHUTDOWN_WINDOW: Duration = Duration::from_secs(30);
        assert!(
            worst_case <= GRACEFUL_SHUTDOWN_WINDOW,
            "inline transfer retry worst case {worst_case:?} exceeds the {GRACEFUL_SHUTDOWN_WINDOW:?} graceful-shutdown window",
        );
    }

    #[test]
    fn backoff_is_capped_and_saturating() {
        let policy = TransferRetryPolicy {
            max_retries: 64,
            base: Duration::from_secs(1),
            cap: Duration::from_secs(8),
        };
        assert_eq!(policy.backoff(4), Duration::from_secs(8));
        assert_eq!(policy.backoff(64), Duration::from_secs(8));
        assert_eq!(policy.backoff(0), Duration::from_secs(1));
    }

    #[tokio::test(start_paused = true)]
    async fn produce_with_retry_succeeds_after_transient_failures_without_wall_clock_sleep() {
        let wall = std::time::Instant::now();
        let capture = CaptureTransferSink::failing_first(2);
        let sink: Arc<dyn TransferSink> = Arc::new(capture.clone());
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid::Uuid::from_u128(1),
            new_person_uuid: uuid::Uuid::from_u128(2),
            merged_at_ms: 1,
            source_partition: 0,
            source_offset: 0,
            leaves: vec![],
            forward_hops: 0,
        };

        let acked =
            produce_transfer_with_retry(&sink, &transfer, &TransferRetryPolicy::default(), 0).await;

        assert!(acked, "third attempt succeeds within the budget");
        assert_eq!(capture.transfers(), vec![transfer]);
        assert!(
            wall.elapsed() < Duration::from_secs(2),
            "backoff ran on the paused clock, not the wall clock",
        );
    }

    #[tokio::test(start_paused = true)]
    async fn produce_with_retry_exhausts_after_max_retries() {
        let capture = CaptureTransferSink::failing_always();
        let sink: Arc<dyn TransferSink> = Arc::new(capture.clone());
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid::Uuid::from_u128(1),
            new_person_uuid: uuid::Uuid::from_u128(2),
            merged_at_ms: 1,
            source_partition: 0,
            source_offset: 0,
            leaves: vec![],
            forward_hops: 0,
        };

        let acked =
            produce_transfer_with_retry(&sink, &transfer, &TransferRetryPolicy::default(), 0).await;

        assert!(!acked);
        assert!(capture.transfers().is_empty());
    }

    const REDRIVE_PARTITION: u16 = 3;

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn capture_deps(transfer_sink: CaptureTransferSink) -> MergeWorkerDeps {
        MergeWorkerDeps {
            transfer_sink: Arc::new(transfer_sink),
            stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
            merge_tracker: Arc::new(OffsetTracker::new()),
            transfer_tracker: Arc::new(OffsetTracker::new()),
            retry: TransferRetryPolicy::default(),
            gc_scan_limit: DEFAULT_MERGE_GC_SCAN_LIMIT,
            stage2_orphan_gc_enabled: true,
            cascade_sink: Arc::new(CaptureCascadeSink::new()),
            cascade_tracker: Arc::new(OffsetTracker::new()),
            cascade: CascadeConfig::default(),
            partition_count: COHORT_PARTITION_COUNT,
        }
    }

    fn staged_pending(p_old: Uuid, merge_offset: i64) -> (PendingTransferKey, PendingTransfer) {
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: p_old,
            new_person_uuid: Uuid::from_u128(0xBEEF),
            merged_at_ms: 1,
            source_partition: REDRIVE_PARTITION as i32,
            source_offset: merge_offset,
            leaves: vec![TransferLeaf::new(
                LeafStateKey([0xAB; 16]),
                StatefulRecord::new(
                    Stage1State::BehavioralSingle {
                        has_match: true,
                        last_event_at_ms: 1,
                        earliest_eviction_at_ms: i64::MAX,
                    },
                    AppliedOffsets::default(),
                ),
            )],
            forward_hops: 0,
        };
        let key = PendingTransferKey {
            partition_id: REDRIVE_PARTITION,
            team_id: 7,
            old_person: p_old,
        };
        let pending = PendingTransfer {
            transfer,
            merge_msg_partition: REDRIVE_PARTITION as i32,
            merge_msg_offset: merge_offset,
        };
        (key, pending)
    }

    fn stage(store: &CohortStore, key: &PendingTransferKey, bytes: &[u8]) {
        store
            .write_batch(|batch| batch.put_pending_transfer(key, bytes))
            .unwrap();
    }

    #[tokio::test]
    async fn redrive_re_produces_a_staged_entry_clears_it_and_marks_the_stored_coords() {
        let (_dir, store) = temp_store();
        let (key, pending) = staged_pending(Uuid::from_u128(1), 41);
        stage(&store, &key, &pending.encode());

        let sink = CaptureTransferSink::new();
        let deps = capture_deps(sink.clone());
        // The exhausted merge was dispatched this tenure, so its ceiling is already raised.
        deps.merge_tracker
            .mark_dispatched(REDRIVE_PARTITION as i32, 42);

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;

        assert_eq!(sink.transfers(), vec![pending.transfer]);
        assert!(
            store.get_pending_transfer(&key).unwrap().is_none(),
            "the entry was cleared after the ack",
        );
        assert_eq!(
            deps.merge_tracker
                .committable_offsets()
                .get(&(REDRIVE_PARTITION as i32)),
            Some(&42),
            "the stored merge-message coordinates were marked",
        );
    }

    #[tokio::test]
    async fn redrive_produce_failure_leaves_the_entry_and_the_offset_for_the_next_tick() {
        let (_dir, store) = temp_store();
        let (key, pending) = staged_pending(Uuid::from_u128(1), 41);
        stage(&store, &key, &pending.encode());

        let sink = CaptureTransferSink::failing_first(1);
        let deps = capture_deps(sink.clone());
        deps.merge_tracker
            .mark_dispatched(REDRIVE_PARTITION as i32, 42);

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;
        assert!(sink.transfers().is_empty());
        assert!(store.get_pending_transfer(&key).unwrap().is_some());
        assert!(
            deps.merge_tracker.committable_offsets().is_empty(),
            "a failed redrive marks nothing",
        );

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;
        assert_eq!(sink.transfers(), vec![pending.transfer]);
        assert!(store.get_pending_transfer(&key).unwrap().is_none());
        assert_eq!(
            deps.merge_tracker
                .committable_offsets()
                .get(&(REDRIVE_PARTITION as i32)),
            Some(&42),
        );
    }

    #[tokio::test(start_paused = true)]
    async fn redrive_makes_a_single_produce_attempt_per_tick_with_no_backoff() {
        let (_dir, store) = temp_store();
        let (key, pending) = staged_pending(Uuid::from_u128(1), 41);
        stage(&store, &key, &pending.encode());
        let deps = capture_deps(CaptureTransferSink::failing_always());
        deps.merge_tracker
            .mark_dispatched(REDRIVE_PARTITION as i32, 42);

        let before = tokio::time::Instant::now();
        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;

        assert_eq!(
            tokio::time::Instant::now() - before,
            Duration::ZERO,
            "no backoff sleep on the paused clock — exactly one attempt per tick",
        );
        assert!(store.get_pending_transfer(&key).unwrap().is_some());
    }

    #[tokio::test]
    async fn redrive_leaves_an_undecodable_entry_in_place_and_still_recovers_the_rest() {
        let (_dir, store) = temp_store();
        let corrupt_key = PendingTransferKey {
            partition_id: REDRIVE_PARTITION,
            team_id: 7,
            old_person: Uuid::from_u128(1),
        };
        stage(&store, &corrupt_key, b"not-a-pending-transfer");
        let (good_key, good) = staged_pending(Uuid::from_u128(2), 41);
        stage(&store, &good_key, &good.encode());

        let sink = CaptureTransferSink::new();
        let deps = capture_deps(sink.clone());
        deps.merge_tracker
            .mark_dispatched(REDRIVE_PARTITION as i32, 42);

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;

        assert_eq!(
            sink.transfers(),
            vec![good.transfer],
            "the good entry was recovered",
        );
        assert!(store.get_pending_transfer(&good_key).unwrap().is_none());
        assert!(
            store.get_pending_transfer(&corrupt_key).unwrap().is_some(),
            "the corrupt entry stays for every later tick to surface",
        );
    }

    #[tokio::test]
    async fn redrive_attempts_at_most_the_cap_per_tick_and_the_remainder_survives() {
        let (_dir, store) = temp_store();
        let backlog = REDRIVE_MAX_ATTEMPTS_PER_TICK + 3;
        let staged: Vec<_> = (0..backlog)
            .map(|i| {
                let (key, pending) = staged_pending(Uuid::from_u128(i as u128 + 1), 41 + i as i64);
                stage(&store, &key, &pending.encode());
                key
            })
            .collect();

        let sink = CaptureTransferSink::new();
        let deps = capture_deps(sink.clone());
        deps.merge_tracker
            .mark_dispatched(REDRIVE_PARTITION as i32, 41 + backlog as i64);

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;
        assert_eq!(
            sink.transfers().len(),
            REDRIVE_MAX_ATTEMPTS_PER_TICK,
            "tick 1 attempted exactly the cap",
        );
        for key in &staged[..REDRIVE_MAX_ATTEMPTS_PER_TICK] {
            assert!(store.get_pending_transfer(key).unwrap().is_none());
        }
        for key in &staged[REDRIVE_MAX_ATTEMPTS_PER_TICK..] {
            assert!(
                store.get_pending_transfer(key).unwrap().is_some(),
                "entries past the cap survive to the next tick",
            );
        }

        handle_redrive(REDRIVE_PARTITION, &store, &deps).await;
        assert_eq!(
            sink.transfers().len(),
            backlog,
            "tick 2 drained the remainder",
        );
        for key in &staged {
            assert!(store.get_pending_transfer(key).unwrap().is_none());
        }
    }

    const FORWARD_PARTITION: u16 = 5;

    fn forwarded_transfer() -> MergeStateTransfer {
        MergeStateTransfer {
            team_id: 7,
            old_person_uuid: Uuid::from_u128(0xA),
            new_person_uuid: Uuid::from_u128(0xC),
            merged_at_ms: 1,
            source_partition: 9,
            source_offset: 100,
            leaves: vec![],
            forward_hops: 1,
        }
    }

    #[tokio::test]
    async fn forward_produce_failure_holds_the_transfer_offset_until_redelivery_succeeds() {
        let forwarded = forwarded_transfer();

        // First attempt: the sink fails → nothing produced, offset not marked. A separate fresh sink
        // models the recovered attempt below.
        let failing_sink = CaptureTransferSink::failing_always();
        let failing = capture_deps(failing_sink.clone());
        forward_transfer(FORWARD_PARTITION, &failing, &forwarded, 80).await;
        assert!(
            failing_sink.transfers().is_empty(),
            "a failed forward produced nothing",
        );
        assert!(
            failing.transfer_tracker.committable_offsets().is_empty(),
            "a failed forward marks no offset",
        );

        // Redelivery against a working sink: produced once, offset marked once.
        let working_sink = CaptureTransferSink::new();
        let working = capture_deps(working_sink.clone());
        working
            .transfer_tracker
            .mark_dispatched(FORWARD_PARTITION as i32, 81);
        forward_transfer(FORWARD_PARTITION, &working, &forwarded, 80).await;
        assert_eq!(
            working_sink.transfers(),
            vec![forwarded],
            "the redelivery forwarded exactly once",
        );
        assert_eq!(
            working
                .transfer_tracker
                .committable_offsets()
                .get(&(FORWARD_PARTITION as i32)),
            Some(&81),
            "the transfer offset is marked only after the ack",
        );
    }

    /// A store-error hold must be sticky: a later success on the same partition must not leapfrog
    /// the held offset. `hold` pins `K` (the failed offset) and a subsequent `mark_processed` at
    /// `K' > K` must leave committable at `K`, not advance it.
    #[test]
    fn an_apply_store_error_hold_is_not_leapfrogged_by_a_later_successful_transfer() {
        const P: u16 = 6;
        let deps = capture_deps(CaptureTransferSink::new());
        // The partition processed transfers up to offset 40 this tenure, then saw 41 (fails) and 43.
        deps.transfer_tracker.mark_dispatched(P as i32, 44);
        mark_processed(&deps.transfer_tracker, P, 40);
        assert_eq!(
            deps.transfer_tracker.committable_offsets().get(&(P as i32)),
            Some(&41),
            "before the failure, committable is the next-offset 41",
        );

        // The apply store-error arm holds at the failed message's own offset K=41 (no +1).
        hold(&deps.transfer_tracker, P, 41);

        // A later transfer for the same partition applies cleanly and marks next-offset 44.
        mark_processed(&deps.transfer_tracker, P, 43);
        assert_eq!(
            deps.transfer_tracker.committable_offsets().get(&(P as i32)),
            Some(&41),
            "the later success must NOT advance committable past the held offset 41",
        );
    }
}
