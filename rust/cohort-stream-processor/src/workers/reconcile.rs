//! In-memory reconcile work admitted by the seed consumer.
//!
//! The queue belongs to one partition worker. Its deferred offsets deliberately die with the
//! worker without completing; partition teardown then forgets the tracker tenure so Kafka replays
//! every unfinished reconcile from the beginning.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicI64, Ordering};
use std::sync::Arc;

use metrics::{counter, gauge};
use tracing::{debug, info, warn};

use cohort_core::clickhouse_timestamp_to_millis;
use cohort_core::filters::{CohortId, TeamId};
use cohort_core::seed::ReconcileTile;
#[cfg(test)]
use cohort_core::seed::RunId;

use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, RECONCILE_BITS_FIXED_TOTAL,
    RECONCILE_JOBS_COMPLETED_TOTAL, RECONCILE_JOBS_DISCARDED_TOTAL,
    RECONCILE_MARKERS_EMITTED_TOTAL, RECONCILE_QUEUE_DEPTH, RECONCILE_ROWS_EMITTED_TOTAL,
    RECONCILE_ROWS_SCANNED_TOTAL,
};
use crate::partitions::offset_tracker::{DeferredOffset, MarkOutcome, OffsetTracker};
use crate::producer::{
    ChangeOrigin, CohortMembershipChange, MembershipSink, ReconcileCompleteMarker,
};
use crate::stage2::Stage2State;
use crate::store::{
    ReadLane, Stage2CohortPrefix, Stage2DirtyKey, Stage2Key, StagedBatch, StoreHandle,
};
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::stage2_path::recompute_and_diff;
use crate::workers::worker::{
    count_by_status, first_cascades, produce_cascades, produce_membership,
};

/// Emit a `warn!` carrying the reconcile job identity (`team_id`, `cohort_id`, `run_id`) read from
/// `$tile`, so the drain warnings share one definition of those fields. Extra fields and the message
/// follow exactly as in a bare `warn!`: `warn_job!(tile, partition_id, error = %error, "…")`.
macro_rules! warn_job {
    ($tile:expr, $($rest:tt)*) => {
        warn!(
            team_id = $tile.team_id().0,
            cohort_id = $tile.cohort_id().0,
            run_id = %$tile.run_id().0,
            $($rest)*
        )
    };
}

/// Default number of Stage 2 rows one reconcile drain tick may scan.
pub const DEFAULT_RECONCILE_SCAN_PAGE: usize = 256;

/// Pod-wide count of admitted jobs still owned by partition queues.
#[derive(Debug, Default)]
pub struct ReconcileBacklog(AtomicI64);

impl ReconcileBacklog {
    pub fn len(&self) -> i64 {
        self.0.load(Ordering::Relaxed)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn add(&self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }

    fn done(&self, count: usize) {
        let count = i64::try_from(count).expect("an in-memory queue cannot exceed i64::MAX jobs");
        let updated = self
            .0
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
                current.checked_sub(count).filter(|next| *next >= 0)
            });
        debug_assert!(updated.is_ok(), "reconcile backlog ownership underflow");
    }
}

/// Runtime dependencies shared by every partition's reconcile queue.
#[derive(Debug, Clone)]
pub struct ReconcileDeps {
    pub enabled: bool,
    pub scan_page: usize,
    pub backlog: Arc<ReconcileBacklog>,
}

impl Default for ReconcileDeps {
    fn default() -> Self {
        Self {
            enabled: false,
            scan_page: DEFAULT_RECONCILE_SCAN_PAGE,
            backlog: Arc::new(ReconcileBacklog::default()),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ScanPhase {
    Scanning { cursor: Option<Vec<u8>> },
    DrainingDirty { cursor: Option<Vec<u8>> },
    MarkerReady,
}

#[derive(Debug)]
struct ReconcileJob {
    tile: ReconcileTile,
    offset: DeferredOffset,
    dirty_tracking: Option<crate::store::Stage2DirtyTrackingGuard>,
    phase: ScanPhase,
    rows_scanned: u64,
    bits_fixed: u64,
}

pub(crate) enum SupersedeOutcome {
    NoQueuedJob,
    Replaced(DeferredOffset),
    RetainedNewerOrEqual,
}

/// FIFO reconcile work for one partition worker.
pub(crate) struct ReconcileQueue {
    jobs: VecDeque<ReconcileJob>,
    backlog: Arc<ReconcileBacklog>,
    partition_label: Arc<str>,
    handle: StoreHandle,
}

impl ReconcileQueue {
    pub(crate) fn new(
        partition_id: u16,
        backlog: Arc<ReconcileBacklog>,
        handle: StoreHandle,
    ) -> Self {
        let queue = Self {
            jobs: VecDeque::new(),
            backlog,
            partition_label: Arc::from(partition_id.to_string()),
            handle,
        };
        queue.record_depth();
        queue
    }

    pub(crate) fn enqueue(&mut self, tile: ReconcileTile, offset: DeferredOffset) {
        self.jobs.push_back(ReconcileJob {
            tile,
            offset,
            dirty_tracking: None,
            phase: ScanPhase::Scanning { cursor: None },
            rows_scanned: 0,
            bits_fixed: 0,
        });
        self.backlog.add();
        self.record_depth();
    }

    /// Start dirty capture only for the queue head, immediately before its first scan. Mutations
    /// while a job waits behind another snapshot are covered by its future full scan and need no
    /// per-person metadata.
    fn activate_front_tracking(&mut self, prefix: Stage2CohortPrefix) {
        if self
            .jobs
            .front()
            .is_some_and(|job| job.dirty_tracking.is_none())
        {
            let tracking = self.handle.track_stage2_dirty(prefix);
            self.jobs
                .front_mut()
                .expect("the queue head was present before acquiring its tracking lease")
                .dirty_tracking = Some(tracking);
        }
    }

    /// Replace a queued job only when the incoming Kafka offset is newer. A follower rewind may
    /// replay an older job while a newer run is still queued; that replay must never evict the newer
    /// snapshot.
    pub(crate) fn supersede_if_newer(
        &mut self,
        team_id: TeamId,
        cohort_id: CohortId,
        incoming_offset: i64,
    ) -> SupersedeOutcome {
        let Some(position) = self
            .jobs
            .iter()
            .position(|job| job.tile.team_id() == team_id && job.tile.cohort_id() == cohort_id)
        else {
            return SupersedeOutcome::NoQueuedJob;
        };
        if incoming_offset <= self.jobs[position].offset.offset() {
            return SupersedeOutcome::RetainedNewerOrEqual;
        }
        let job = self
            .jobs
            .remove(position)
            .expect("position came from the same queue");
        self.backlog.done(1);
        self.record_depth();
        SupersedeOutcome::Replaced(job.offset)
    }

    fn front(&self) -> Option<&ReconcileJob> {
        self.jobs.front()
    }

    fn front_mut(&mut self) -> Option<&mut ReconcileJob> {
        self.jobs.front_mut()
    }

    fn finish_front(&mut self) -> Option<ReconcileJob> {
        let job = self.jobs.pop_front()?;
        self.backlog.done(1);
        self.record_depth();
        Some(job)
    }

    fn record_depth(&self) {
        gauge!(RECONCILE_QUEUE_DEPTH, "partition" => self.partition_label.clone())
            .set(self.jobs.len() as f64);
    }

    #[cfg(test)]
    pub(crate) fn len(&self) -> usize {
        self.jobs.len()
    }

    #[cfg(test)]
    pub(crate) fn front_run_id(&self) -> Option<RunId> {
        self.jobs.front().map(|job| job.tile.run_id())
    }
}

impl Drop for ReconcileQueue {
    fn drop(&mut self) {
        self.backlog.done(self.jobs.len());
        gauge!(RECONCILE_QUEUE_DEPTH, "partition" => self.partition_label.clone()).set(0.0);
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReconcileRetryReason {
    CatalogNotLoaded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReconcileDiscardReason {
    TeamAbsent,
    CohortAbsent,
    NotEmitting,
    HashMismatch,
    HashUnknown,
}

impl ReconcileDiscardReason {
    const fn as_str(self) -> &'static str {
        match self {
            Self::TeamAbsent => "team_absent",
            Self::CohortAbsent => "cohort_absent",
            Self::NotEmitting => "not_emitting",
            Self::HashMismatch => "hash_mismatch",
            Self::HashUnknown => "hash_unknown",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReconcileGuard {
    Proceed,
    Retry(ReconcileRetryReason),
    Discard(ReconcileDiscardReason),
}

fn evaluate_guard(
    catalog_loaded: bool,
    filters: Option<&TeamFilters>,
    tile: &ReconcileTile,
) -> ReconcileGuard {
    if !catalog_loaded {
        return ReconcileGuard::Retry(ReconcileRetryReason::CatalogNotLoaded);
    }
    let Some(filters) = filters else {
        return ReconcileGuard::Discard(ReconcileDiscardReason::TeamAbsent);
    };
    if !filters.cohorts.contains_key(&tile.cohort_id()) {
        return ReconcileGuard::Discard(ReconcileDiscardReason::CohortAbsent);
    }
    let Some(eligibility) = filters.eligibility.get(&tile.cohort_id()) else {
        return ReconcileGuard::Discard(ReconcileDiscardReason::CohortAbsent);
    };
    if !eligibility.registers_membership() {
        return ReconcileGuard::Discard(ReconcileDiscardReason::NotEmitting);
    }
    // An absent hash means the cohort has no behavioral leaves (the loader omits person-only
    // cohorts, which the person-property backfill heals separately) or the run was superseded. Either
    // way this is the intended fail-closed skip, observable via the `hash_unknown` discard counter.
    let Some(actual_hash) = filters.behavioral_shape_hashes.get(&tile.cohort_id()) else {
        return ReconcileGuard::Discard(ReconcileDiscardReason::HashUnknown);
    };
    if actual_hash != tile.filters_hash() {
        return ReconcileGuard::Discard(ReconcileDiscardReason::HashMismatch);
    }
    ReconcileGuard::Proceed
}

/// Advance at most one scan page for the queue head. Guard-discarded jobs are drained in the same
/// tick; a successfully completed job stops the tick so the next queued snapshot gets its own page
/// budget.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn handle_reconcile_drain(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    last_updated: &str,
) {
    loop {
        let Some(job) = queue.front() else {
            return;
        };
        let tile = job.tile.clone();
        let phase = job.phase.clone();
        let source_offset = job.offset.offset();

        // Read the release-published loaded flag before the ArcSwap. On the first refresh, that
        // ordering prevents observing `loaded = true` alongside the pre-refresh empty snapshot.
        let catalog_loaded = catalog.is_loaded();
        let catalog_snapshot = catalog.load_full();
        let filters = catalog_snapshot.team(tile.team_id()).map(Arc::as_ref);
        match evaluate_guard(catalog_loaded, filters, &tile) {
            ReconcileGuard::Retry(ReconcileRetryReason::CatalogNotLoaded) => {
                debug!(
                    partition_id,
                    team_id = tile.team_id().0,
                    cohort_id = tile.cohort_id().0,
                    run_id = %tile.run_id().0,
                    "reconcile drain waiting for the first filter catalog load",
                );
                return;
            }
            ReconcileGuard::Discard(reason) => {
                let discarded = queue
                    .finish_front()
                    .expect("the guarded queue head is still present");
                complete_offset(
                    &merge.seed_tracker,
                    partition_id,
                    discarded.offset,
                    "discarded reconcile",
                );
                counter!(RECONCILE_JOBS_DISCARDED_TOTAL, "reason" => reason.as_str()).increment(1);
                warn_job!(
                    tile,
                    partition_id,
                    reason = reason.as_str(),
                    "discarding reconcile job without a completion marker",
                );
                continue;
            }
            ReconcileGuard::Proceed => {}
        }

        let filters = filters.expect("the proceed guard proved the team exists");
        let tree = filters
            .cohorts
            .get(&tile.cohort_id())
            .expect("the proceed guard proved the cohort exists");
        // Only flipped bits of a full-tree cohort cascade to referrers; single-leaf fixes never do.
        let cascades_flips = filters
            .eligibility
            .get(&tile.cohort_id())
            .copied()
            .expect("the proceed guard proved eligibility exists")
            .writes_cf_stage2();

        let prefix = Stage2CohortPrefix {
            partition_id,
            team_id: tile.team_id().0 as u64,
            cohort_id: tile.cohort_id().0 as u64,
        };
        queue.activate_front_tracking(prefix);

        let step = match phase {
            ScanPhase::Scanning { cursor } => {
                drain_scanning(
                    partition_id,
                    handle,
                    sink,
                    merge,
                    queue,
                    &tile,
                    filters,
                    tree,
                    cascades_flips,
                    prefix,
                    source_offset,
                    cursor,
                    last_updated,
                )
                .await
            }
            ScanPhase::DrainingDirty { cursor } => {
                drain_dirty(
                    partition_id,
                    handle,
                    sink,
                    merge,
                    queue,
                    &tile,
                    filters,
                    tree,
                    cascades_flips,
                    prefix,
                    source_offset,
                    cursor,
                    last_updated,
                )
                .await
            }
            ScanPhase::MarkerReady => {
                drain_marker(
                    partition_id,
                    handle,
                    sink,
                    merge,
                    queue,
                    &tile,
                    prefix,
                    last_updated,
                )
                .await
            }
        };
        match step {
            DrainStep::Reenter => continue,
            DrainStep::Yield => return,
        }
    }
}

/// Whether the drain loop should re-enter against the head's newly transitioned phase
/// ([`DrainStep::Reenter`]) or yield the tick because its work budget is spent ([`DrainStep::Yield`]).
enum DrainStep {
    Reenter,
    Yield,
}

/// Scan one Stage 2 page for the cohort and emit its current membership. An empty page hands off to
/// dirty verification; a settled non-empty page is the tick's whole budget.
#[allow(clippy::too_many_arguments)]
async fn drain_scanning(
    partition_id: u16,
    handle: &StoreHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    tile: &ReconcileTile,
    filters: &TeamFilters,
    tree: &crate::filters::tree::CohortTree,
    cascades_flips: bool,
    prefix: Stage2CohortPrefix,
    source_offset: i64,
    cursor: Option<Vec<u8>>,
    last_updated: &str,
) -> DrainStep {
    let page = match handle
        .scan_stage2_cohort(prefix, cursor, merge.reconcile.scan_page)
        .await
    {
        Ok(page) => page,
        Err(error) => {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile Stage 2 scan failed; retrying this page on the next tick",
            );
            return DrainStep::Yield;
        }
    };
    if page.is_empty() {
        queue
            .front_mut()
            .expect("the scanned queue head is still present")
            .phase = ScanPhase::DrainingDirty { cursor: None };
        return DrainStep::Reenter;
    }

    let dirty_to_clear: Vec<Stage2DirtyKey> =
        page.iter().copied().map(Stage2DirtyKey::new).collect();
    let Some(progress) = settle_reconcile_page(
        partition_id,
        handle,
        sink,
        merge,
        tile,
        filters,
        tree,
        cascades_flips,
        &page,
        &dirty_to_clear,
        source_offset,
        last_updated,
    )
    .await
    else {
        return DrainStep::Yield;
    };

    let short_page = page.len() < merge.reconcile.scan_page;
    let next_cursor = page
        .last()
        .expect("a non-empty page has a final key")
        .encode()
        .to_vec();
    let job = queue
        .front_mut()
        .expect("the advanced queue head is still present");
    job.rows_scanned = job.rows_scanned.saturating_add(progress.rows_scanned);
    job.bits_fixed = job.bits_fixed.saturating_add(progress.bits_fixed);
    job.phase = if short_page {
        ScanPhase::DrainingDirty { cursor: None }
    } else {
        ScanPhase::Scanning {
            cursor: Some(next_cursor),
        }
    };
    // One non-empty settlement page is the tick's work budget. Even a short final main page leaves
    // dirty verification for the next tick, so mutations behind the cursor cannot silently double the
    // configured per-tick ceiling.
    DrainStep::Yield
}

/// Re-settle rows mutated behind the main scan, verifying from the cohort prefix until the dirty set
/// is empty before advancing to the marker.
#[allow(clippy::too_many_arguments)]
async fn drain_dirty(
    partition_id: u16,
    handle: &StoreHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    tile: &ReconcileTile,
    filters: &TeamFilters,
    tree: &crate::filters::tree::CohortTree,
    cascades_flips: bool,
    prefix: Stage2CohortPrefix,
    source_offset: i64,
    cursor: Option<Vec<u8>>,
    last_updated: &str,
) -> DrainStep {
    let page = match handle
        .scan_stage2_dirty(prefix, cursor.clone(), merge.reconcile.scan_page)
        .await
    {
        Ok(page) => page,
        Err(error) => {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile dirty scan failed; retrying this page on the next tick",
            );
            return DrainStep::Yield;
        }
    };
    if page.is_empty() {
        let job = queue
            .front_mut()
            .expect("the dirty-scanning queue head is still present");
        if cursor.is_some() {
            // Verify once more from the prefix so a marker inserted behind the cursor
            // between ticks cannot be missed.
            job.phase = ScanPhase::DrainingDirty { cursor: None };
        } else {
            job.phase = ScanPhase::MarkerReady;
        }
        return DrainStep::Reenter;
    }

    let stage2_keys: Vec<Stage2Key> = page.iter().map(|dirty| dirty.stage2_key()).collect();
    let current_rows = match handle
        .multi_get_stage2(stage2_keys.clone(), ReadLane::Maintenance)
        .await
    {
        Ok(rows) => rows,
        Err(error) => {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile dirty-row read failed; retrying this page on the next tick",
            );
            return DrainStep::Yield;
        }
    };
    let existing_keys: Vec<Stage2Key> = stage2_keys
        .into_iter()
        .zip(current_rows)
        .filter_map(|(key, value)| value.is_some().then_some(key))
        .collect();
    let Some(progress) = settle_reconcile_page(
        partition_id,
        handle,
        sink,
        merge,
        tile,
        filters,
        tree,
        cascades_flips,
        &existing_keys,
        &page,
        source_offset,
        last_updated,
    )
    .await
    else {
        return DrainStep::Yield;
    };

    let short_page = page.len() < merge.reconcile.scan_page;
    let next_cursor = page
        .last()
        .expect("a non-empty dirty page has a final key")
        .encode()
        .to_vec();
    let job = queue
        .front_mut()
        .expect("the advanced dirty queue head is still present");
    job.rows_scanned = job.rows_scanned.saturating_add(progress.rows_scanned);
    job.bits_fixed = job.bits_fixed.saturating_add(progress.bits_fixed);
    job.phase = ScanPhase::DrainingDirty {
        cursor: Some(next_cursor.clone()),
    };

    // A full page does not prove exhaustion, so first look strictly after it. This is
    // verification only: if another page exists, the next tick settles it.
    if !short_page {
        match handle.scan_stage2_dirty(prefix, Some(next_cursor), 1).await {
            Ok(remaining) if !remaining.is_empty() => return DrainStep::Yield,
            Ok(_) => {}
            Err(error) => {
                warn_job!(
                    tile,
                    partition_id,
                    error = %error,
                    "reconcile dirty tail verification failed; retrying next tick",
                );
                return DrainStep::Yield;
            }
        }
    }

    // Verify once from the prefix to catch work inserted behind an earlier cursor. The
    // worker owns this partition serially, so an empty result immediately after the
    // settlement closes the hot-single-key case even when page size is one. Never
    // settle a second nonempty page in this tick.
    queue
        .front_mut()
        .expect("the verified dirty queue head is still present")
        .phase = ScanPhase::DrainingDirty { cursor: None };
    match handle.scan_stage2_dirty(prefix, None, 1).await {
        Ok(remaining) if !remaining.is_empty() => DrainStep::Yield,
        Ok(_) => {
            queue
                .front_mut()
                .expect("the verified dirty queue head is still present")
                .phase = ScanPhase::MarkerReady;
            DrainStep::Reenter
        }
        Err(error) => {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile dirty prefix verification failed; retrying next tick",
            );
            DrainStep::Yield
        }
    }
}

/// Emit the per-partition completion marker once the dirty set is drained. A failed marker produce
/// retries the marker only; work dirtied while the marker was pending is settled before the retry.
#[allow(clippy::too_many_arguments)]
async fn drain_marker(
    partition_id: u16,
    handle: &StoreHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    tile: &ReconcileTile,
    prefix: Stage2CohortPrefix,
    last_updated: &str,
) -> DrainStep {
    // A marker produce may have failed on a prior tick. Recheck the dirty prefix before
    // every retry so newly arrived work is settled first without rescanning the cohort.
    let pending_dirty = match handle.scan_stage2_dirty(prefix, None, 1).await {
        Ok(page) => page,
        Err(error) => {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile dirty verification failed before marker; retrying on the next tick",
            );
            return DrainStep::Yield;
        }
    };
    if !pending_dirty.is_empty() {
        queue
            .front_mut()
            .expect("the marker-ready queue head is still present")
            .phase = ScanPhase::DrainingDirty { cursor: None };
        return DrainStep::Reenter;
    }
    let marker = ReconcileCompleteMarker::new(
        tile.team_id(),
        tile.cohort_id(),
        partition_id,
        tile.run_id(),
        last_updated.to_string(),
    );
    let acks = sink.produce_markers(vec![marker]).await;
    // Exactly one marker went in, so anything but a single successful ack is a produce failure.
    let failed_acks = acks.iter().filter(|ack| ack.is_err()).count();
    if acks.len() != 1 || failed_acks > 0 {
        warn_job!(
            tile,
            partition_id,
            ack_count = acks.len(),
            failed_acks,
            "reconcile completion-marker produce failed; rechecking dirty work before retry",
        );
        return DrainStep::Yield;
    }

    counter!(RECONCILE_MARKERS_EMITTED_TOTAL).increment(1);
    let completed = queue
        .finish_front()
        .expect("the marker-producing queue head is still present");
    complete_offset(
        &merge.seed_tracker,
        partition_id,
        completed.offset,
        "completed reconcile",
    );
    counter!(RECONCILE_JOBS_COMPLETED_TOTAL).increment(1);
    info!(
        partition_id,
        team_id = tile.team_id().0,
        cohort_id = tile.cohort_id().0,
        run_id = %tile.run_id().0,
        rows_scanned = completed.rows_scanned,
        bits_fixed = completed.bits_fixed,
        "reconcile job completed",
    );
    DrainStep::Yield
}

struct PageProgress {
    rows_scanned: u64,
    bits_fixed: u64,
}

/// Emit one current reconcile page, then atomically commit any corrected bits and clear the exact
/// dirty markers covered by that evaluation. Returning `None` leaves the queue phase unchanged so
/// the same page is retried on the next tick.
#[allow(clippy::too_many_arguments)]
async fn settle_reconcile_page(
    partition_id: u16,
    handle: &StoreHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    tile: &ReconcileTile,
    filters: &TeamFilters,
    tree: &crate::filters::tree::CohortTree,
    cascades_flips: bool,
    page: &[Stage2Key],
    dirty_to_clear: &[Stage2DirtyKey],
    source_offset: i64,
    last_updated: &str,
) -> Option<PageProgress> {
    let evaluated_at_ms = clickhouse_timestamp_to_millis(last_updated)
        .expect("worker-generated last_updated timestamps always parse");
    let mut changes = Vec::with_capacity(page.len());
    let mut cascade_changes = Vec::new();
    let mut writes: Vec<(Stage2Key, Stage2State)> = Vec::new();
    let mut fixed_entered = 0u64;
    let mut fixed_left = 0u64;
    for key in page {
        let diff = match recompute_and_diff(
            partition_id,
            key.person_id,
            tree,
            filters,
            handle,
            ReadLane::Maintenance,
        )
        .await
        {
            Ok(diff) => diff,
            Err(error) => {
                warn_job!(
                    tile,
                    partition_id,
                    person_id = %key.person_id,
                    error = %error,
                    "reconcile recompute failed; retrying this page on the next tick",
                );
                return None;
            }
        };
        let change = CohortMembershipChange {
            team_id: tile.team_id().0,
            cohort_id: tile.cohort_id().0,
            person_id: key.person_id.to_string(),
            last_updated: last_updated.to_string(),
            status: diff.status(),
            origin: Some(ChangeOrigin::Reconcile),
            run_id: Some(tile.run_id()),
        };
        if diff.requires_write() {
            writes.push((
                diff.stage2_key,
                Stage2State {
                    in_cohort: diff.new_bit,
                    last_evaluated_at_ms: evaluated_at_ms,
                },
            ));
        }
        if diff.flipped() {
            if diff.new_bit {
                fixed_entered += 1;
            } else {
                fixed_left += 1;
            }
            if cascades_flips {
                cascade_changes.push(change.clone());
            }
        }
        changes.push(change);
    }

    let cascades = first_cascades(merge, &cascade_changes, source_offset);
    let (entered, left) = count_by_status(&changes);
    let membership_errors = if changes.is_empty() {
        0
    } else {
        produce_membership(sink, changes).await
    };
    if membership_errors > 0 {
        warn_job!(
            tile,
            partition_id,
            errors = membership_errors,
            "reconcile membership produce failed; retrying this page on the next tick",
        );
        return None;
    }

    let cascade_errors = produce_cascades(merge, cascades).await;
    if cascade_errors > 0 {
        warn_job!(
            tile,
            partition_id,
            errors = cascade_errors,
            "reconcile cascade produce failed; retrying this page on the next tick",
        );
        return None;
    }

    let mut staged = StagedBatch::default();
    for (key, state) in &writes {
        staged.put_stage2(key, &state.encode());
    }
    // These deletes are deliberately staged after the puts. A fix marks its row dirty through the
    // normal typed write path, then this page-clear consumes that marker in the same atomic batch.
    for dirty in dirty_to_clear {
        staged.delete_stage2_dirty(dirty);
    }
    if !staged.is_empty() {
        if let Err(error) = handle.commit(staged).await {
            warn_job!(
                tile,
                partition_id,
                error = %error,
                "reconcile Stage 2 settlement failed; retrying this page on the next tick",
            );
            return None;
        }
    }
    // Count only durably-settled pages: membership produce, cascade produce, and commit have all
    // succeeded here. Any earlier failure returns `None` above and retries the whole page, so
    // incrementing here keeps a retry from double-counting.
    counter!(RECONCILE_ROWS_SCANNED_TOTAL).increment(page.len() as u64);
    if entered > 0 {
        counter!(RECONCILE_ROWS_EMITTED_TOTAL, "status" => "entered").increment(entered);
    }
    if left > 0 {
        counter!(RECONCILE_ROWS_EMITTED_TOTAL, "status" => "left").increment(left);
    }
    if fixed_entered > 0 {
        counter!(RECONCILE_BITS_FIXED_TOTAL, "direction" => "entered").increment(fixed_entered);
    }
    if fixed_left > 0 {
        counter!(RECONCILE_BITS_FIXED_TOTAL, "direction" => "left").increment(fixed_left);
    }

    Some(PageProgress {
        rows_scanned: page.len() as u64,
        bits_fixed: fixed_entered + fixed_left,
    })
}

fn complete_offset(
    tracker: &OffsetTracker,
    partition_id: u16,
    offset: DeferredOffset,
    operation: &'static str,
) {
    match tracker.complete_deferred(offset) {
        Some(MarkOutcome::WithinDispatch) => {}
        Some(MarkOutcome::CappedAheadOfDispatch) => {
            counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
            warn!(
                partition_id,
                operation, "reconcile completion exceeded the seed dispatch ceiling",
            );
        }
        None => warn!(
            partition_id,
            operation, "reconcile completion belonged to an expired seed-tracker tenure",
        ),
    }
}

#[cfg(test)]
#[allow(clippy::disallowed_methods)]
mod tests {
    use std::sync::atomic::AtomicBool;

    use async_trait::async_trait;
    use chrono_tz::UTC;
    use common_kafka::kafka_producer::KafkaProduceError;
    use serde_json::{json, Value};
    use tempfile::TempDir;
    use uuid::Uuid;

    use cohort_core::seed::BehavioralShapeHash;
    use cohort_core::{CohortEligibility, ExcludedReason, FilterCatalog, LeafStateKey};

    use crate::filters::tree::{CohortTree, FilterNode};
    use crate::filters::{BoolOp, TeamFiltersBuilder};
    use crate::partitions::offset_tracker::OffsetTracker;
    use crate::producer::{CaptureCascadeSink, CaptureSink, MembershipStatus};
    use crate::stage1::person_record::{MatchedSet, PersonRecord};
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::stage2::state::Stage2Ownership;
    use crate::store::{
        Behavioral, BehavioralKey, CohortStore, OffloadConfig, OffloadMode, PersonRecordKey,
        PersonRecords, StoreConfig,
    };

    use super::*;

    const TEAM: i32 = 7;
    const COHORT: i32 = 1;
    const PARTITION: u16 = 0;
    const BEHAVIORAL_HASH: [u8; 16] = *b"0123456789abcdef";
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const SHAPE_HASH: &str = "shape-v1";
    const TS: &str = "2026-05-26 12:34:56.789123";

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn store_handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
    }

    fn behavioral_leaf() -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": 7, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn catalog(single_leaf: bool) -> (CatalogHandle, LeafStateKey) {
        let values = if single_leaf {
            vec![behavioral_leaf()]
        } else {
            vec![behavioral_leaf(), person_leaf()]
        };
        let cohort = json!({ "properties": { "type": "AND", "values": values } });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(COHORT), TeamId(TEAM), &cohort)
            .unwrap();
        builder.set_behavioral_shape_hash(
            CohortId(COHORT),
            BehavioralShapeHash::parse(SHAPE_HASH).unwrap(),
        );
        let filters = builder.freeze(UTC);
        let lsk = filters.by_condition_to_lsk[&BEHAVIORAL_HASH][0];
        (
            CatalogHandle::from_catalog(FilterCatalog::from_teams([(TeamId(TEAM), filters)])),
            lsk,
        )
    }

    struct DrainShell {
        _dir: TempDir,
        store: CohortStore,
        handle: StoreHandle,
        catalog: CatalogHandle,
        sink: Arc<dyn MembershipSink>,
        deps: MergeWorkerDeps,
        queue: ReconcileQueue,
        lsk: LeafStateKey,
    }

    impl DrainShell {
        fn new(
            single_leaf: bool,
            sink: Arc<dyn MembershipSink>,
            cascade_sink: CaptureCascadeSink,
            scan_page: usize,
        ) -> Self {
            let (_dir, store) = temp_store();
            let handle = store_handle(&store);
            let (catalog, lsk) = catalog(single_leaf);
            let mut deps = Arc::try_unwrap(MergeWorkerDeps::capture())
                .unwrap_or_else(|_| panic!("test owns the only dependency Arc"));
            deps.reconcile.enabled = true;
            deps.reconcile.scan_page = scan_page;
            deps.cascade.enabled = true;
            deps.cascade_sink = Arc::new(cascade_sink);
            let queue =
                ReconcileQueue::new(PARTITION, deps.reconcile.backlog.clone(), handle.clone());
            Self {
                _dir,
                store,
                handle,
                catalog,
                sink,
                deps,
                queue,
                lsk,
            }
        }

        fn write_current(&self, person: Uuid, behavioral: bool, person_match: bool, prior: bool) {
            if behavioral {
                let key = BehavioralKey::new(PARTITION, TEAM as u64, person, self.lsk);
                let state = Stage1State::BehavioralSingle {
                    has_match: true,
                    last_event_at_ms: 1_700_000_000_000,
                    earliest_eviction_at_ms: i64::MAX,
                };
                let record = StatefulRecord::new(state, AppliedOffsets::default());
                self.store
                    .write_batch(|batch| batch.put::<Behavioral>(&key, &record.encode()))
                    .unwrap();
            }
            if person_match {
                let key = PersonRecordKey::new(PARTITION, TEAM as u64, person);
                let mut record = PersonRecord::absent();
                record.matched = MatchedSet::from_iter([PERSON_HASH]);
                self.store
                    .write_batch(|batch| batch.put::<PersonRecords>(&key, &record.encode()))
                    .unwrap();
            }
            let key = Stage2Key {
                partition_id: PARTITION,
                team_id: TEAM as u64,
                cohort_id: COHORT as u64,
                person_id: person,
            };
            let state = Stage2State {
                in_cohort: prior,
                last_evaluated_at_ms: 1,
            };
            self.store
                .write_batch(|batch| batch.put_stage2(&key, &state.encode()))
                .unwrap();
        }

        fn stage2_bit(&self, person: Uuid) -> bool {
            let key = Stage2Key {
                partition_id: PARTITION,
                team_id: TEAM as u64,
                cohort_id: COHORT as u64,
                person_id: person,
            };
            Stage2State::decode(&self.store.get_stage2(&key).unwrap().unwrap())
                .unwrap()
                .in_cohort
        }

        fn enqueue(&mut self, tile: ReconcileTile, offset: i64) {
            self.deps
                .seed_tracker
                .mark_dispatched(PARTITION as i32, offset + 1);
            if self.committable().is_none() {
                assert_eq!(
                    self.deps
                        .seed_tracker
                        .mark_processed(PARTITION as i32, offset),
                    MarkOutcome::WithinDispatch,
                );
            }
            let deferred = self.deps.seed_tracker.defer(PARTITION as i32, offset);
            self.queue.enqueue(tile, deferred);
        }

        /// Admit a newer run over a queued job exactly as `admit_reconcile` does: supersede, hand the
        /// superseded floor to `replace_deferred`, then enqueue the replacement at the new offset.
        fn supersede(&mut self, tile: ReconcileTile, offset: i64) {
            self.deps
                .seed_tracker
                .mark_dispatched(PARTITION as i32, offset + 1);
            let SupersedeOutcome::Replaced(superseded) =
                self.queue
                    .supersede_if_newer(tile.team_id(), tile.cohort_id(), offset)
            else {
                panic!("a newer run must supersede the queued job");
            };
            let (replacement, _) = self
                .deps
                .seed_tracker
                .replace_deferred(superseded, offset)
                .expect("the superseded reconcile retains its deferred offset");
            self.queue.enqueue(tile, replacement);
        }

        async fn tick(&mut self) {
            handle_reconcile_drain(
                PARTITION,
                &self.handle,
                &self.catalog,
                &self.sink,
                &self.deps,
                &mut self.queue,
                TS,
            )
            .await;
        }

        fn committable(&self) -> Option<i64> {
            self.deps
                .seed_tracker
                .committable_offsets()
                .get(&(PARTITION as i32))
                .copied()
        }
    }

    fn tile(team_id: i32, cohort_id: i32, run_id: u128) -> ReconcileTile {
        ReconcileTile::new(
            TeamId(team_id),
            CohortId(cohort_id),
            BehavioralShapeHash::parse(SHAPE_HASH).unwrap(),
            RunId(Uuid::from_u128(run_id)),
        )
    }

    #[test]
    fn queue_tracks_backlog_and_drop_releases_only_the_backlog_count() {
        let (_dir, store) = temp_store();
        let tracker = OffsetTracker::new();
        let backlog = Arc::new(ReconcileBacklog::default());
        tracker.mark_dispatched(3, 11);

        {
            let mut queue = ReconcileQueue::new(3, backlog.clone(), store_handle(&store));
            queue.enqueue(tile(1, 7, 1), tracker.defer(3, 10));
            assert_eq!(queue.len(), 1);
            assert_eq!(backlog.len(), 1);
        }

        assert!(backlog.is_empty());
        assert_eq!(
            tracker.mark_processed(3, 11),
            crate::partitions::offset_tracker::MarkOutcome::WithinDispatch,
        );
        assert_eq!(
            tracker.committable_offsets().get(&3),
            Some(&10),
            "dropping a queued job does not complete its deferred offset",
        );
    }

    #[test]
    fn only_the_active_queue_head_tracks_dirty_people() {
        let (_dir, store) = temp_store();
        let tracker = OffsetTracker::new();
        let backlog = Arc::new(ReconcileBacklog::default());
        tracker.mark_dispatched(PARTITION as i32, 12);
        let mut queue = ReconcileQueue::new(PARTITION, backlog, store_handle(&store));
        queue.enqueue(tile(TEAM, COHORT, 1), tracker.defer(PARTITION as i32, 10));
        queue.enqueue(
            tile(TEAM, COHORT + 1, 2),
            tracker.defer(PARTITION as i32, 11),
        );
        let head_prefix = Stage2CohortPrefix {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: COHORT as u64,
        };
        let waiting_prefix = Stage2CohortPrefix {
            cohort_id: (COHORT + 1) as u64,
            ..head_prefix
        };

        // Enqueue alone captures nothing: a future full scan covers these writes.
        for (prefix, person) in [(head_prefix, 1), (waiting_prefix, 2)] {
            let key = Stage2Key {
                partition_id: prefix.partition_id,
                team_id: prefix.team_id,
                cohort_id: prefix.cohort_id,
                person_id: Uuid::from_u128(person),
            };
            store
                .write_batch(|batch| batch.put_stage2(&key, b"before"))
                .unwrap();
            assert!(store
                .scan_stage2_dirty(prefix, None, 10)
                .unwrap()
                .is_empty());
        }

        queue.activate_front_tracking(head_prefix);
        for (prefix, person) in [(head_prefix, 3), (waiting_prefix, 4)] {
            let key = Stage2Key {
                partition_id: prefix.partition_id,
                team_id: prefix.team_id,
                cohort_id: prefix.cohort_id,
                person_id: Uuid::from_u128(person),
            };
            store
                .write_batch(|batch| batch.put_stage2(&key, b"during"))
                .unwrap();
        }

        assert_eq!(
            store
                .scan_stage2_dirty(head_prefix, None, 10)
                .unwrap()
                .len(),
            1
        );
        assert!(store
            .scan_stage2_dirty(waiting_prefix, None, 10)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn supersede_matches_team_and_cohort_and_preserves_other_jobs() {
        let (_dir, store) = temp_store();
        let tracker = OffsetTracker::new();
        let backlog = Arc::new(ReconcileBacklog::default());
        tracker.mark_dispatched(3, 14);
        let mut queue = ReconcileQueue::new(3, backlog.clone(), store_handle(&store));
        queue.enqueue(tile(1, 7, 1), tracker.defer(3, 10));
        queue.enqueue(tile(1, 8, 2), tracker.defer(3, 11));
        queue.enqueue(tile(2, 7, 3), tracker.defer(3, 12));

        let SupersedeOutcome::Replaced(superseded) =
            queue.supersede_if_newer(TeamId(1), CohortId(7), 13)
        else {
            panic!("the newer run should supersede team 1 cohort 7");
        };

        assert_eq!(queue.len(), 2);
        assert_eq!(queue.front_run_id(), Some(RunId(Uuid::from_u128(2))));
        assert_eq!(backlog.len(), 2);
        assert_eq!(
            tracker.complete_deferred(superseded),
            Some(crate::partitions::offset_tracker::MarkOutcome::WithinDispatch),
        );
        assert!(matches!(
            queue.supersede_if_newer(TeamId(2), CohortId(7), 12),
            SupersedeOutcome::RetainedNewerOrEqual,
        ));
    }

    #[test]
    fn older_or_duplicate_replay_never_evicts_the_queued_run() {
        let (_dir, store) = temp_store();
        let tracker = OffsetTracker::new();
        let backlog = Arc::new(ReconcileBacklog::default());
        tracker.mark_dispatched(3, 20);
        let mut queue = ReconcileQueue::new(3, backlog.clone(), store_handle(&store));
        queue.enqueue(tile(1, 7, 2), tracker.defer(3, 15));

        for replayed_offset in [10, 15] {
            assert!(matches!(
                queue.supersede_if_newer(TeamId(1), CohortId(7), replayed_offset),
                SupersedeOutcome::RetainedNewerOrEqual,
            ));
            assert_eq!(queue.front_run_id(), Some(RunId(Uuid::from_u128(2))));
            assert_eq!(backlog.len(), 1);
            assert_eq!(tracker.committable_offsets().get(&3), None);
        }
    }

    #[tokio::test]
    async fn superseding_a_mid_drain_run_reemits_under_the_new_run_and_releases_its_offset() {
        let sink = CaptureSink::new();
        // A one-row page over three people keeps run A mid-scan (active dirty lease, cursor set) when
        // the newer run arrives.
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), CaptureCascadeSink::new(), 1);
        let people = [Uuid::from_u128(1), Uuid::from_u128(2), Uuid::from_u128(3)];
        for person in people {
            shell.write_current(person, true, false, true);
        }
        shell.enqueue(tile(TEAM, COHORT, 100), 5);

        shell.tick().await;
        assert_eq!(
            sink.changes().len(),
            1,
            "run A emitted one page before being superseded",
        );
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::Scanning { cursor: Some(_) }),
        ));

        shell.supersede(tile(TEAM, COHORT, 200), 7);
        assert_eq!(shell.queue.len(), 1);
        assert_eq!(
            shell.queue.front_run_id(),
            Some(RunId(Uuid::from_u128(200)))
        );

        for _ in 0..16 {
            if shell.queue.front().is_none() {
                break;
            }
            shell.tick().await;
        }
        assert!(shell.queue.front().is_none());
        assert!(shell.deps.reconcile.backlog.is_empty());

        let markers = sink.markers();
        assert_eq!(
            markers.len(),
            1,
            "the superseded run never emits its own marker"
        );
        assert_eq!(markers[0].run_id(), RunId(Uuid::from_u128(200)));

        let reemitted: std::collections::HashSet<String> = sink
            .changes()
            .iter()
            .filter(|change| change.run_id == Some(RunId(Uuid::from_u128(200))))
            .map(|change| change.person_id.clone())
            .collect();
        assert_eq!(
            reemitted,
            people
                .iter()
                .map(Uuid::to_string)
                .collect::<std::collections::HashSet<_>>(),
            "run B re-emits the full current membership",
        );

        assert_eq!(
            shell.committable(),
            Some(8),
            "the deferred floor releases only after run B completes",
        );
    }

    fn guard_filters(eligibility: Option<CohortEligibility>, hash: Option<&str>) -> TeamFilters {
        let mut filters = TeamFilters::default();
        filters.cohorts.insert(
            CohortId(COHORT),
            CohortTree {
                cohort_id: CohortId(COHORT),
                team_id: TeamId(TEAM),
                root: FilterNode::Group {
                    op: BoolOp::And,
                    children: Vec::new(),
                },
            },
        );
        if let Some(eligibility) = eligibility {
            filters.eligibility.insert(CohortId(COHORT), eligibility);
        }
        if let Some(hash) = hash {
            filters
                .behavioral_shape_hashes
                .insert(CohortId(COHORT), BehavioralShapeHash::parse(hash).unwrap());
        }
        filters
    }

    #[test]
    fn drain_guard_classifies_every_retry_discard_and_proceed_state() {
        let reconcile = tile(TEAM, COHORT, 1);

        assert_eq!(
            evaluate_guard(false, None, &reconcile),
            ReconcileGuard::Retry(ReconcileRetryReason::CatalogNotLoaded),
        );
        assert_eq!(
            evaluate_guard(true, None, &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::TeamAbsent),
        );
        assert_eq!(
            evaluate_guard(true, Some(&TeamFilters::default()), &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::CohortAbsent),
        );

        let missing_eligibility = guard_filters(None, Some(SHAPE_HASH));
        assert_eq!(
            evaluate_guard(true, Some(&missing_eligibility), &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::CohortAbsent),
        );
        let excluded = guard_filters(
            Some(CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf)),
            Some(SHAPE_HASH),
        );
        assert_eq!(
            evaluate_guard(true, Some(&excluded), &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::NotEmitting),
        );
        let hash_unknown = guard_filters(Some(CohortEligibility::Stage2Composable), None);
        assert_eq!(
            evaluate_guard(true, Some(&hash_unknown), &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::HashUnknown),
        );
        let hash_mismatch =
            guard_filters(Some(CohortEligibility::Stage2Composable), Some("shape-v2"));
        assert_eq!(
            evaluate_guard(true, Some(&hash_mismatch), &reconcile),
            ReconcileGuard::Discard(ReconcileDiscardReason::HashMismatch),
        );

        for eligibility in [
            CohortEligibility::SingleLeaf(LeafStateKey(BEHAVIORAL_HASH)),
            CohortEligibility::Stage2Composable,
            CohortEligibility::Stage2ComposableRef,
        ] {
            let filters = guard_filters(Some(eligibility), Some(SHAPE_HASH));
            assert_eq!(
                evaluate_guard(true, Some(&filters), &reconcile),
                ReconcileGuard::Proceed,
                "{eligibility:?} registers membership",
            );
        }
    }

    #[tokio::test]
    async fn drain_emits_the_full_snapshot_fixes_only_flips_and_paginates() {
        let sink = CaptureSink::new();
        let cascades = CaptureCascadeSink::new();
        let mut shell = DrainShell::new(false, Arc::new(sink.clone()), cascades.clone(), 2);
        let alice = Uuid::from_u128(1);
        let bob = Uuid::from_u128(2);
        let charlie = Uuid::from_u128(3);
        shell.write_current(alice, true, true, false);
        shell.write_current(bob, false, false, true);
        shell.write_current(charlie, true, true, true);
        shell.enqueue(tile(TEAM, COHORT, 11), 5);

        shell.tick().await;

        assert_eq!(sink.changes().len(), 2, "one bounded page was emitted");
        assert!(sink.markers().is_empty());
        assert_eq!(shell.committable(), Some(5));
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::Scanning {
                cursor: Some(_),
                ..
            }),
        ));

        shell.tick().await;

        let changes = sink.changes();
        assert_eq!(changes.len(), 3, "unchanged rows are emitted too");
        assert_eq!(
            changes
                .iter()
                .map(|change| change.status)
                .collect::<Vec<_>>(),
            vec![
                MembershipStatus::Entered,
                MembershipStatus::Left,
                MembershipStatus::Entered,
            ],
        );
        assert!(changes.iter().all(|change| {
            change.origin == Some(ChangeOrigin::Reconcile)
                && change.run_id == Some(RunId(Uuid::from_u128(11)))
        }));
        assert!(shell.stage2_bit(alice));
        assert!(!shell.stage2_bit(bob));
        assert!(shell.stage2_bit(charlie));

        let cascade_messages = cascades.messages();
        assert_eq!(cascade_messages.len(), 2, "only flipped bits cascade");
        assert_eq!(cascade_messages[0].change.person_id, alice.to_string());
        assert_eq!(cascade_messages[1].change.person_id, bob.to_string());
        shell.tick().await;
        assert_eq!(sink.markers().len(), 1);
        assert!(shell.queue.front().is_none());
        assert!(shell.deps.reconcile.backlog.is_empty());
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn noop_reconcile_claims_a_transferred_fallback() {
        let sink = CaptureSink::new();
        let cascades = CaptureCascadeSink::new();
        let mut shell = DrainShell::new(false, Arc::new(sink.clone()), cascades.clone(), 2);
        let person = Uuid::from_u128(1);
        let key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: COHORT as u64,
            person_id: person,
        };
        let fallback = Stage2State {
            in_cohort: false,
            last_evaluated_at_ms: 1,
        };
        shell
            .store
            .write_batch(|batch| {
                batch.put_stage2(&key, &fallback.encode_transferred_fallback());
            })
            .unwrap();
        shell.enqueue(tile(TEAM, COHORT, 12), 5);

        shell.tick().await;

        let bytes = shell.store.get_stage2(&key).unwrap().unwrap();
        let (state, ownership) = Stage2State::decode_with_ownership(&bytes).unwrap();
        assert!(!state.in_cohort);
        assert_eq!(ownership, Stage2Ownership::Local);
        assert_eq!(
            sink.changes().len(),
            1,
            "the full snapshot still emits the row"
        );
        assert_eq!(sink.changes()[0].status, MembershipStatus::Left);
        assert!(
            cascades.messages().is_empty(),
            "ownership settlement is not a flip"
        );
    }

    #[tokio::test]
    async fn paged_scan_drains_a_row_inserted_behind_its_cursor_without_restarting() {
        let sink = CaptureSink::new();
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), CaptureCascadeSink::new(), 1);
        let later_key = Uuid::from_u128(2);
        let inserted_behind_cursor = Uuid::from_u128(1);
        shell.write_current(later_key, true, false, true);
        shell.enqueue(tile(TEAM, COHORT, 111), 5);

        shell.tick().await;
        assert_eq!(sink.changes().len(), 1);
        assert_eq!(sink.changes()[0].person_id, later_key.to_string());
        assert!(sink.markers().is_empty());

        shell.write_current(inserted_behind_cursor, true, false, true);
        shell.tick().await;

        assert_eq!(
            sink.changes()[1].person_id,
            inserted_behind_cursor.to_string(),
            "the dirty-person pass catches a row inserted behind the main cursor",
        );
        assert_eq!(
            sink.changes()
                .iter()
                .map(|change| change.person_id.clone())
                .collect::<Vec<_>>(),
            vec![later_key.to_string(), inserted_behind_cursor.to_string(),],
            "the main cohort page is not rescanned because another person changed",
        );
        assert_eq!(sink.markers().len(), 1);
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn repeatedly_mutated_hot_person_does_not_restart_main_scan() {
        let sink = CaptureSink::new();
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), CaptureCascadeSink::new(), 1);
        let hot = Uuid::from_u128(10);
        let second = Uuid::from_u128(20);
        let third = Uuid::from_u128(30);
        for person in [hot, second, third] {
            shell.write_current(person, true, false, true);
        }
        shell.enqueue(tile(TEAM, COHORT, 112), 5);

        for expected in [hot, second, third] {
            shell.tick().await;
            assert_eq!(
                sink.changes().last().unwrap().person_id,
                expected.to_string(),
                "the main cursor advances despite a mutation behind it",
            );
            shell.write_current(hot, true, false, true);
        }

        shell.tick().await;
        assert_eq!(sink.changes().last().unwrap().person_id, hot.to_string());
        assert_eq!(
            sink.markers().len(),
            1,
            "the job completes in the same tick that settles the full hot-person page",
        );
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn deleted_dirty_row_is_cleared_without_being_resurrected_or_emitted_again() {
        let sink = CaptureSink::new();
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), CaptureCascadeSink::new(), 1);
        let alice = Uuid::from_u128(1);
        let bob = Uuid::from_u128(2);
        shell.write_current(alice, true, false, true);
        shell.write_current(bob, true, false, true);
        shell.enqueue(tile(TEAM, COHORT, 113), 5);

        shell.tick().await;
        let deleted_key = Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM as u64,
            cohort_id: COHORT as u64,
            person_id: alice,
        };
        shell
            .store
            .write_batch(|batch| batch.delete_stage2(&deleted_key))
            .unwrap();

        shell.tick().await;
        shell.tick().await;
        shell.tick().await;

        assert_eq!(
            sink.changes()
                .iter()
                .map(|change| change.person_id.clone())
                .collect::<Vec<_>>(),
            vec![alice.to_string(), bob.to_string()],
            "the tombstoned scan row is not evaluated or emitted from its dirty marker",
        );
        assert!(shell.store.get_stage2(&deleted_key).unwrap().is_none());
        assert_eq!(sink.markers().len(), 1);
    }

    #[tokio::test]
    async fn single_leaf_fix_never_cascades() {
        let sink = CaptureSink::new();
        let cascades = CaptureCascadeSink::new();
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), cascades.clone(), 8);
        let alice = Uuid::from_u128(1);
        shell.write_current(alice, true, false, false);
        shell.enqueue(tile(TEAM, COHORT, 12), 5);

        shell.tick().await;

        assert_eq!(sink.changes().len(), 1);
        assert_eq!(sink.changes()[0].status, MembershipStatus::Entered);
        assert!(shell.stage2_bit(alice));
        assert!(cascades.messages().is_empty());
        shell.tick().await;
        assert_eq!(sink.markers().len(), 1);
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn discard_continues_to_a_zero_row_job_and_emits_only_its_marker() {
        let sink = CaptureSink::new();
        let mut shell =
            DrainShell::new(false, Arc::new(sink.clone()), CaptureCascadeSink::new(), 8);
        shell.enqueue(tile(999, COHORT, 1), 5);
        shell.enqueue(tile(TEAM, COHORT, 2), 6);

        shell.tick().await;

        assert!(sink.changes().is_empty());
        let markers = sink.markers();
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].run_id(), RunId(Uuid::from_u128(2)));
        assert!(shell.queue.front().is_none());
        assert!(shell.deps.reconcile.backlog.is_empty());
        assert_eq!(shell.committable(), Some(7));
    }

    #[tokio::test]
    async fn membership_failure_retries_the_same_page_without_advancing() {
        let sink = CaptureSink::failing_first(1);
        let mut shell = DrainShell::new(true, Arc::new(sink.clone()), CaptureCascadeSink::new(), 8);
        let alice = Uuid::from_u128(1);
        shell.write_current(alice, true, false, false);
        shell.enqueue(tile(TEAM, COHORT, 13), 5);

        shell.tick().await;

        assert!(sink.changes().is_empty());
        assert!(sink.markers().is_empty());
        assert!(!shell.stage2_bit(alice));
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::Scanning { cursor: None }),
        ));

        shell.tick().await;

        assert_eq!(sink.changes().len(), 1);
        assert!(shell.stage2_bit(alice));
        shell.tick().await;
        assert_eq!(sink.markers().len(), 1);
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn cascade_failure_retries_before_committing_or_advancing() {
        let sink = CaptureSink::new();
        let cascades = CaptureCascadeSink::failing_first(1);
        let mut shell = DrainShell::new(false, Arc::new(sink.clone()), cascades.clone(), 8);
        let alice = Uuid::from_u128(1);
        shell.write_current(alice, true, true, false);
        shell.enqueue(tile(TEAM, COHORT, 14), 5);

        shell.tick().await;

        assert_eq!(sink.changes().len(), 1, "the membership leg acked");
        assert!(sink.markers().is_empty());
        assert!(!shell.stage2_bit(alice));
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::Scanning { cursor: None }),
        ));

        shell.tick().await;

        assert_eq!(sink.changes().len(), 2, "the page was emitted again");
        assert_eq!(cascades.messages().len(), 1);
        assert!(shell.stage2_bit(alice));
        shell.tick().await;
        assert_eq!(sink.markers().len(), 1);
        assert_eq!(shell.committable(), Some(6));
    }

    struct FailFirstMarkerSink {
        capture: CaptureSink,
        fail_marker: AtomicBool,
    }

    impl FailFirstMarkerSink {
        fn new() -> Self {
            Self {
                capture: CaptureSink::new(),
                fail_marker: AtomicBool::new(true),
            }
        }
    }

    #[async_trait]
    impl MembershipSink for FailFirstMarkerSink {
        async fn produce(
            &self,
            changes: Vec<CohortMembershipChange>,
        ) -> Vec<Result<(), KafkaProduceError>> {
            self.capture.produce(changes).await
        }

        async fn produce_markers(
            &self,
            markers: Vec<ReconcileCompleteMarker>,
        ) -> Vec<Result<(), KafkaProduceError>> {
            if self.fail_marker.swap(false, Ordering::SeqCst) {
                return markers
                    .into_iter()
                    .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
                    .collect();
            }
            self.capture.produce_markers(markers).await
        }
    }

    #[tokio::test]
    async fn marker_failure_retries_only_the_marker_phase() {
        let sink = Arc::new(FailFirstMarkerSink::new());
        let mut shell = DrainShell::new(true, sink.clone(), CaptureCascadeSink::new(), 8);
        let alice = Uuid::from_u128(1);
        shell.write_current(alice, true, false, false);
        shell.enqueue(tile(TEAM, COHORT, 15), 5);

        shell.tick().await;
        shell.tick().await;

        assert_eq!(sink.capture.changes().len(), 1);
        assert!(sink.capture.markers().is_empty());
        assert!(shell.stage2_bit(alice), "the page committed before marker");
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::MarkerReady),
        ));
        assert_eq!(shell.committable(), Some(5));

        shell.tick().await;

        assert_eq!(
            sink.capture.changes().len(),
            1,
            "the page was not rescanned"
        );
        assert_eq!(sink.capture.markers().len(), 1);
        assert!(shell.queue.front().is_none());
        assert_eq!(shell.committable(), Some(6));
    }

    #[tokio::test]
    async fn marker_retry_drains_new_dirty_work_without_rescanning_clean_rows() {
        let sink = Arc::new(FailFirstMarkerSink::new());
        let mut shell = DrainShell::new(true, sink.clone(), CaptureCascadeSink::new(), 8);
        let alice = Uuid::from_u128(2);
        let bob = Uuid::from_u128(1);
        shell.write_current(alice, true, false, true);
        shell.enqueue(tile(TEAM, COHORT, 16), 5);

        shell.tick().await;
        shell.tick().await;
        assert_eq!(sink.capture.changes().len(), 1);
        assert!(sink.capture.markers().is_empty());
        assert!(matches!(
            shell.queue.front().map(|job| &job.phase),
            Some(ScanPhase::MarkerReady),
        ));

        shell.write_current(bob, true, false, true);
        shell.tick().await;

        assert_eq!(
            sink.capture
                .changes()
                .iter()
                .map(|change| change.person_id.clone())
                .collect::<Vec<_>>(),
            vec![alice.to_string(), bob.to_string()],
            "a failed marker drains only the person that changed while the marker was pending",
        );
        assert_eq!(sink.capture.markers().len(), 1);
        assert_eq!(shell.committable(), Some(6));
    }
}
