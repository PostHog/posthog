//! The single global marker-watch task — the seeder's second lifecycle component.
//!
//! One dedicated consumer tails the whole marker topic, folding every observed
//! `reconcile_complete` marker into the per-run [`MarkerLedger`] it names. Bits and the watcher's
//! resume positions are flushed through the fenced [`persist_marker_observations`] on a cadence
//! (every persist interval), a batch cap (every N consumed messages), or immediately when a cohort's
//! bitmap completes — whichever comes first. The driver publishes the set of runs to watch via a
//! [`watch`] channel, recomputed each tick from discovery; the task adds ledgers seeded from persisted
//! bits (so a resumed watcher continues the fold) and drops runs that leave the set. A lost dispatch
//! fence (a re-dispatch superseded us) or a truncated start offset (retention outran the watch
//! position) drops the run locally; re-dispatch is the recovery path.
//!
//! The broker plumbing lives behind the [`MarkerStream`] and [`MarkerFlush`] seams so the fold/flush
//! decision logic is tested with fakes — the rdkafka consumer follows proven prior art and gets no
//! broker integration test.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::time::Duration;

use async_trait::async_trait;
use cohort_core::filters::{CohortId, TeamId};
use lifecycle::Handle;
use metrics::counter;
use sqlx::PgPool;
use tokio::sync::watch;
use tracing::{info, warn};

use crate::domain::{
    DispatchEpoch, MarkerFold, MarkerLedger, NextOffset, PartitionBitmap, RunId, WatchPartition,
    WatchPositions,
};
use crate::kafka::markers::{MarkerWatcher, WatchError, WatchItem};
use crate::observability::metrics::{RECONCILE_MARKERS_OBSERVED, RECONCILE_WATCH_TRUNCATED};
use crate::store::completion::{persist_marker_observations, CompletionStoreError};

/// One run the driver wants watched: its identity, dispatch fence, watcher start offsets, and the bits
/// already persisted (so a resumed ledger continues rather than restarts).
#[derive(Debug, Clone)]
pub struct WatchDirective {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub epoch: DispatchEpoch,
    pub start: WatchPositions,
    pub seeded: Vec<(CohortId, PartitionBitmap)>,
}

/// The full set of runs to watch, republished each driver tick.
#[derive(Debug, Clone, Default)]
pub struct WatchDirectives {
    pub runs: Vec<WatchDirective>,
}

/// The marker-topic consumer seam. Real impl: [`MarkerWatcher`].
#[async_trait]
pub trait MarkerStream: Send {
    /// Re-assign the stream to read from `start` on every named partition. The watch state decides
    /// *when* a seek is needed; the stream just does it.
    async fn seek(&mut self, start: &WatchPositions) -> Result<(), WatchError>;
    /// Drop the assignment entirely. Called when the last watched run leaves, so an idle watcher
    /// stops fetching a high-volume topic nobody is folding.
    async fn unassign(&mut self) -> Result<(), WatchError>;
    /// Await the next classified record.
    async fn recv(&mut self) -> Result<WatchItem, WatchError>;
}

#[async_trait]
impl MarkerStream for MarkerWatcher {
    async fn seek(&mut self, start: &WatchPositions) -> Result<(), WatchError> {
        self.seek_to(start).await
    }

    async fn unassign(&mut self) -> Result<(), WatchError> {
        MarkerWatcher::unassign(self)
    }

    async fn recv(&mut self) -> Result<WatchItem, WatchError> {
        MarkerWatcher::next_item(self).await
    }
}

/// The fenced-persist seam. Real impl: [`PgMarkerFlush`].
#[async_trait]
pub trait MarkerFlush: Send {
    async fn persist(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        bits: &[(CohortId, PartitionBitmap)],
        positions: &WatchPositions,
    ) -> Result<(), CompletionStoreError>;
}

/// The real flush: the epoch-fenced OR-merge of bits plus the watcher positions.
pub struct PgMarkerFlush {
    pool: PgPool,
    marker_topic: String,
}

impl PgMarkerFlush {
    pub fn new(pool: PgPool, marker_topic: String) -> Self {
        Self { pool, marker_topic }
    }
}

#[async_trait]
impl MarkerFlush for PgMarkerFlush {
    async fn persist(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        bits: &[(CohortId, PartitionBitmap)],
        positions: &WatchPositions,
    ) -> Result<(), CompletionStoreError> {
        persist_marker_observations(
            &self.pool,
            run_id,
            epoch,
            bits,
            positions,
            &self.marker_topic,
        )
        .await
    }
}

/// One watched run's in-memory fold state. `positions` is this run's fold *coverage*: it starts at
/// the directive's dispatch-time start (so partitions with no traffic since the dispatch already
/// read as covered) and max-merges forward as the stream reads. Coverage is tracked per run so a
/// freshly added run cannot claim offsets the stream read before that run's ledger existed — its
/// settlement proof rests on this.
struct RunWatch {
    epoch: DispatchEpoch,
    positions: WatchPositions,
    ledger: MarkerLedger,
}

impl RunWatch {
    fn from_directive(directive: &WatchDirective) -> Self {
        Self {
            epoch: directive.epoch,
            positions: directive.start.clone(),
            ledger: MarkerLedger::new(
                directive.run_id,
                directive.team_id,
                directive.seeded.iter().copied(),
            ),
        }
    }
}

/// What the stream has read since coverage was last folded into the watched runs. Held once for the
/// whole task rather than advanced into every run per record: the watched-run set has no upper bound,
/// so per-record work must not scale with it.
#[derive(Default)]
struct StreamCoverage(BTreeMap<WatchPartition, NextOffset>);

impl StreamCoverage {
    fn advance(&mut self, partition: WatchPartition, next: NextOffset) {
        let slot = self.0.entry(partition).or_insert(next);
        if next > *slot {
            *slot = next;
        }
    }

    /// Raise a run's tracked partitions to what the stream has read. [`WatchPositions::advance`] drops
    /// partitions the run never captured, which is what keeps a run from claiming one it never read
    /// from the beginning.
    fn raise(&self, positions: &mut WatchPositions) {
        for (&partition, &next) in &self.0 {
            positions.advance(partition, next);
        }
    }

    fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    fn clear(&mut self) {
        self.0.clear();
    }
}

/// The fold/flush state machine, driven by the runner loop but callable directly in tests.
struct WatchState<S, F> {
    stream: S,
    flush: F,
    persist_max_batch: u64,
    stream_coverage: StreamCoverage,
    /// Heartbeat between per-run persists. `None` in tests, which drive the state machine directly.
    heartbeat: Option<Handle>,
    runs: HashMap<RunId, RunWatch>,
    messages_since_flush: u64,
    positions_advanced: bool,
    /// A cohort completed since the last flush, which triggers an immediate one. Aggregated on
    /// ingest because `should_flush` runs per record on a high-volume topic.
    completion_pending: bool,
    /// A seek is owed (a run was added or rebuilt, or the last seek failed transiently) but has not
    /// succeeded yet. Cleared only by a successful seek, so a broker blip is retried on the next
    /// directive publish instead of silently leaving the stream unassigned.
    seek_pending: bool,
    /// Dispatch epochs dropped because retention outran their watch start. PostgreSQL still
    /// classifies such a run `Reconciling`, so the driver republishes its directive every tick;
    /// without this the watcher would rebuild, re-seek, re-truncate and re-drop it forever — a
    /// watermark sweep per tick, and a truncation counter that measures ticks instead of events.
    /// Recovery is a re-dispatch, which mints a new epoch and is therefore not blocked.
    truncated: HashMap<RunId, DispatchEpoch>,
}

impl<S: MarkerStream, F: MarkerFlush> WatchState<S, F> {
    fn new(stream: S, flush: F, persist_max_batch: u64, heartbeat: Option<Handle>) -> Self {
        Self {
            stream,
            flush,
            persist_max_batch,
            stream_coverage: StreamCoverage::default(),
            heartbeat,
            runs: HashMap::new(),
            messages_since_flush: 0,
            positions_advanced: false,
            completion_pending: false,
            seek_pending: false,
            truncated: HashMap::new(),
        }
    }

    /// Fold one record: advance every watched run's coverage and route any marker to its ledger.
    /// While a seek is owed the stream still reads the pre-seek assignment, so advancing coverage or
    /// folding would claim reads a rewound run has not made — the owed seek rewinds and these
    /// records are re-read, so dropping them here loses nothing.
    fn ingest(&mut self, item: WatchItem) {
        if self.seek_pending {
            return;
        }
        self.stream_coverage
            .advance(item.partition, item.next_offset);
        self.positions_advanced = true;
        self.messages_since_flush += 1;
        if let Some(marker) = item.marker {
            let (fold, completed) = match self.runs.get_mut(&marker.run_id) {
                Some(run) => (
                    run.ledger.observe(&marker),
                    run.ledger.completed_since_flush(),
                ),
                None => (MarkerFold::Unwatched, false),
            };
            self.completion_pending |= completed;
            counter!(RECONCILE_MARKERS_OBSERVED, "fold" => fold.label()).increment(1);
        }
    }

    fn should_flush(&self) -> bool {
        self.messages_since_flush >= self.persist_max_batch || self.completion_pending
    }

    /// Fold the stream's reads into every watched run and reset. Every reader of `positions` calls
    /// this first, and it must run before a run joins the set — a run may only ever claim offsets the
    /// stream read while it was already watched.
    fn materialize_coverage(&mut self) {
        if self.stream_coverage.is_empty() {
            return;
        }
        for run in self.runs.values_mut() {
            self.stream_coverage.raise(&mut run.positions);
        }
        self.stream_coverage.clear();
    }

    /// Reconcile the watched-run set with a fresh directive snapshot, then re-seek if the set changed.
    /// A run removed from the set (it left `reconciling`) is flushed once and dropped; a run whose
    /// epoch changed (a re-dispatch) is rebuilt from the fresh directive.
    ///
    /// A seek happens only when a run was added or rebuilt (or a previous seek is still owed). An
    /// added run's start can sit below the stream's current read position — markers there were
    /// consumed before its ledger existed — so the seek rewinds to the minimum start across all
    /// watched runs; re-reading is safe because bit folds and position advances are idempotent.
    /// Steady-state republishes (same runs, same epochs) never re-seek.
    async fn apply_directives(&mut self, directives: &WatchDirectives) {
        // Before the set changes, so a run inserted below starts at its dispatch position rather than
        // inheriting reads the stream made before its ledger existed.
        self.materialize_coverage();
        let incoming: HashSet<RunId> = directives.runs.iter().map(|d| d.run_id).collect();
        let removed: Vec<RunId> = self
            .runs
            .keys()
            .copied()
            .filter(|run_id| !incoming.contains(run_id))
            .collect();
        let removed_any = !removed.is_empty();
        for run_id in removed {
            let _ = self.flush_run(run_id).await;
            self.runs.remove(&run_id);
        }
        // A run the driver stopped publishing can be re-added cleanly, so its tombstone goes too.
        self.truncated.retain(|run_id, _| incoming.contains(run_id));

        for directive in &directives.runs {
            if self.truncated.get(&directive.run_id) == Some(&directive.epoch) {
                continue;
            }
            let rebuild = self
                .runs
                .get(&directive.run_id)
                .is_none_or(|existing| existing.epoch != directive.epoch);
            if rebuild {
                self.truncated.remove(&directive.run_id);
                self.runs
                    .insert(directive.run_id, RunWatch::from_directive(directive));
                self.seek_pending = true;
            }
        }

        // Losing the last watched run must release the assignment, not just stop folding.
        if removed_any && self.runs.is_empty() {
            self.seek_pending = true;
        }

        if self.seek_pending {
            self.reassign().await;
        }
    }

    /// Owe a seek and try to satisfy it now. A recv error can park a partition — an offset out of
    /// range under `auto.offset.reset = error` leaves it dark — and nothing else would reassign
    /// until the watched-run set happens to change.
    async fn request_seek(&mut self) {
        self.seek_pending = true;
        self.reassign().await;
    }

    /// Seek the stream to the minimum start across all watched runs. A truncated start drops every
    /// run whose coverage sits below the log's low watermark and retries with the raised floor.
    async fn reassign(&mut self) {
        self.materialize_coverage();
        loop {
            if self.runs.is_empty() {
                // Stays owed until it lands, like the seek below: nothing else revisits an
                // idle-but-still-assigned consumer.
                match self.stream.unassign().await {
                    Ok(()) => self.seek_pending = false,
                    Err(error) => {
                        warn!(error = %error, "unassigning the idle marker watcher failed; retrying next directive")
                    }
                }
                return;
            }
            let start = min_start(self.runs.values());
            if start.is_empty() {
                self.seek_pending = false;
                return;
            }
            match self.stream.seek(&start).await {
                Ok(()) => {
                    self.seek_pending = false;
                    return;
                }
                Err(WatchError::Truncated {
                    partition,
                    requested,
                    low,
                }) => {
                    let partition = WatchPartition::new(partition);
                    // Drop against the log's low watermark, not just the rejected start: every run
                    // below it is equally unreadable, so one pass clears them all instead of one
                    // watermark round-trip per coverage level.
                    let floor = NextOffset::from_high_watermark(low);
                    let dropped: Vec<RunId> = self
                        .runs
                        .iter()
                        .filter(|(_, run)| {
                            run.positions
                                .get(partition)
                                .is_some_and(|coverage| coverage < floor)
                        })
                        .map(|(run_id, _)| *run_id)
                        .collect();
                    if dropped.is_empty() {
                        warn!(
                            partition = partition.get(),
                            requested,
                            low,
                            "marker watch reported truncation but no run sits below the low watermark"
                        );
                        return;
                    }
                    for run_id in dropped {
                        counter!(RECONCILE_WATCH_TRUNCATED).increment(1);
                        warn!(
                            run_id = ?run_id,
                            partition = partition.get(),
                            low,
                            "marker topic truncated past this run's watch start; dropping (re-dispatch to recover)"
                        );
                        if let Some(run) = self.runs.remove(&run_id) {
                            self.truncated.insert(run_id, run.epoch);
                        }
                    }
                }
                Err(error) => {
                    warn!(error = %error, "assigning the marker watcher failed; retrying next directive");
                    return;
                }
            }
        }
    }

    /// Flush every watched run's dirty bits and the current positions, then reset the flush accounting.
    async fn flush(&mut self) {
        self.materialize_coverage();
        let run_ids: Vec<RunId> = self.runs.keys().copied().collect();
        let mut all_persisted = true;
        for run_id in run_ids {
            all_persisted &= self.flush_run(run_id).await;
            // One round trip per run, all of it before the runner loop's own heartbeat: a large
            // watched set must slow flushes down, not spend the whole liveness budget.
            if let Some(handle) = &self.heartbeat {
                handle.report_healthy();
            }
        }
        self.messages_since_flush = 0;
        // A failed persist holds both retry flags. For a run whose bits are clean but whose coverage
        // moved, `positions_advanced` is the only thing `flush_run`'s guard retries on, and an idle
        // topic never sets it again.
        self.positions_advanced = !all_persisted;
        self.completion_pending = self
            .runs
            .values()
            .any(|run| run.ledger.completed_since_flush());
    }

    /// Persist one run's dirty bits and the watcher positions under its dispatch fence. A lost fence
    /// drops the run (a re-dispatch superseded it); a transient error keeps the bits dirty for retry.
    /// Returns whether the run has nothing left owed — `false` only on a transient error, so the
    /// caller knows to keep the retry flag set.
    async fn flush_run(&mut self, run_id: RunId) -> bool {
        let Some(run) = self.runs.get(&run_id) else {
            return true;
        };
        // Nothing to persist if neither the bits nor the positions moved since the last flush.
        if !run.ledger.has_dirty() && !self.positions_advanced {
            return true;
        }
        let epoch = run.epoch;
        let dirty = run.ledger.dirty_bitmaps();
        let positions = run.positions.clone();
        match self.flush.persist(run_id, epoch, &dirty, &positions).await {
            Ok(()) => {
                if let Some(run) = self.runs.get_mut(&run_id) {
                    run.ledger.clear_dirty();
                }
                true
            }
            Err(CompletionStoreError::CompletionFenceLost { .. }) => {
                info!(
                    run_id = ?run_id,
                    "marker watch lost the dispatch fence; dropping run (a re-dispatch superseded it)"
                );
                self.runs.remove(&run_id);
                true
            }
            Err(error) => {
                warn!(run_id = ?run_id, error = %error, "persisting marker observations failed; will retry");
                false
            }
        }
    }
}

/// The per-partition minimum fold coverage across all watched runs — where the stream must read from
/// so every run's ledger sees everything it has not yet covered. Using coverage (not the original
/// dispatch starts) keeps a late-added run's rewind from re-reading ranges established runs already
/// folded and persisted.
fn min_start<'a>(runs: impl Iterator<Item = &'a RunWatch>) -> WatchPositions {
    let mut min = WatchPositions::new();
    for run in runs {
        for (partition, next) in run.positions.iter() {
            match min.get(partition) {
                Some(current) if current <= next => {}
                _ => min.insert(partition, next),
            }
        }
    }
    min
}

/// The lifecycle-registered runner around a [`WatchState`].
pub struct MarkerWatchTask<S, F> {
    state: WatchState<S, F>,
    directives: watch::Receiver<WatchDirectives>,
    handle: Handle,
    persist_interval: Duration,
}

impl<S: MarkerStream, F: MarkerFlush> MarkerWatchTask<S, F> {
    pub fn new(
        stream: S,
        flush: F,
        directives: watch::Receiver<WatchDirectives>,
        handle: Handle,
        persist_interval: Duration,
        persist_max_batch: u64,
    ) -> Self {
        Self {
            state: WatchState::new(stream, flush, persist_max_batch, Some(handle.clone())),
            directives,
            handle,
            persist_interval,
        }
    }

    /// Drive the fold loop until shutdown, then final-flush. A second lifecycle component: it reports
    /// liveness on progress and drains on the shutdown token.
    pub async fn run(mut self) {
        let _scope = self.handle.process_scope();
        let shutdown = self.handle.shutdown_token();
        let mut flush_tick = tokio::time::interval(self.persist_interval);
        flush_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        self.handle.report_healthy();

        let initial = self.directives.borrow_and_update().clone();
        self.state.apply_directives(&initial).await;

        info!("marker watch task starting");
        loop {
            tokio::select! {
                biased;
                _ = shutdown.cancelled() => break,
                changed = self.directives.changed() => {
                    if changed.is_err() {
                        break;
                    }
                    let directives = self.directives.borrow_and_update().clone();
                    self.state.apply_directives(&directives).await;
                    self.handle.report_healthy();
                }
                item = self.state.stream.recv() => {
                    match item {
                        Ok(item) => {
                            self.state.ingest(item);
                            if self.state.should_flush() {
                                self.state.flush().await;
                            }
                            self.handle.report_healthy();
                        }
                        Err(error) => {
                            warn!(error = %error, "receiving from the marker topic failed; backing off");
                            self.state.request_seek().await;
                            self.handle.report_healthy();
                            tokio::time::sleep(RECV_BACKOFF).await;
                        }
                    }
                }
                _ = flush_tick.tick() => {
                    self.state.flush().await;
                    self.handle.report_healthy();
                }
            }
        }

        self.state.flush().await;
        info!("marker watch task stopped");
    }
}

/// Backoff after a broker recv failure so a hard error does not spin the loop.
const RECV_BACKOFF: Duration = Duration::from_millis(500);

/// The watch task heartbeats at least once per flush tick (default 5 s), so a minute of silence means
/// the loop is stuck, not idle.
pub const MARKER_WATCH_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::VecDeque;
    use std::sync::Mutex;

    use cohort_core::partitioner::COHORT_PARTITION_COUNT;
    use uuid::Uuid;

    use crate::domain::{MarkerPartition, ObservedMarker};
    use crate::store::completion::CompletionOperation;

    fn run(seed: u128) -> RunId {
        RunId(Uuid::from_u128(seed))
    }

    fn start_at(partition: i32, offset: i64) -> WatchPositions {
        let mut positions = WatchPositions::new();
        positions.insert(
            WatchPartition::new(partition),
            NextOffset::from_high_watermark(offset),
        );
        positions
    }

    fn directive(
        run_id: RunId,
        epoch_secs: i64,
        start: WatchPositions,
        cohorts: &[i32],
    ) -> WatchDirective {
        WatchDirective {
            run_id,
            team_id: TeamId(2),
            epoch: epoch(epoch_secs),
            start,
            seeded: cohorts
                .iter()
                .map(|&cohort| (CohortId(cohort), PartitionBitmap::default()))
                .collect(),
        }
    }

    fn epoch(secs: i64) -> DispatchEpoch {
        use chrono::TimeZone;
        DispatchEpoch::from_dispatched_at(chrono::Utc.timestamp_opt(secs, 0).unwrap())
    }

    fn marker_item(partition: i32, offset: i64, run_id: RunId, cohort: i32, bit: u32) -> WatchItem {
        WatchItem {
            partition: WatchPartition::new(partition),
            next_offset: NextOffset::from_high_watermark(offset),
            marker: Some(ObservedMarker {
                team_id: TeamId(2),
                cohort_id: CohortId(cohort),
                partition: MarkerPartition::new(bit).unwrap(),
                run_id,
            }),
        }
    }

    #[derive(Default)]
    struct FakeStream {
        seek_result: Mutex<Option<WatchError>>,
        unassign_result: Mutex<Option<WatchError>>,
        seeks: Vec<WatchPositions>,
        unassigns: usize,
    }

    #[async_trait]
    impl MarkerStream for FakeStream {
        async fn seek(&mut self, start: &WatchPositions) -> Result<(), WatchError> {
            match self.seek_result.lock().unwrap().take() {
                Some(error) => Err(error),
                None => {
                    self.seeks.push(start.clone());
                    Ok(())
                }
            }
        }

        async fn unassign(&mut self) -> Result<(), WatchError> {
            self.unassigns += 1;
            match self.unassign_result.lock().unwrap().take() {
                Some(error) => Err(error),
                None => Ok(()),
            }
        }

        async fn recv(&mut self) -> Result<WatchItem, WatchError> {
            std::future::pending().await
        }
    }

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct FlushCall {
        run_id: RunId,
        bits: Vec<(CohortId, PartitionBitmap)>,
        positions: WatchPositions,
    }

    #[derive(Default)]
    struct FakeFlush {
        calls: Mutex<Vec<FlushCall>>,
        fence_lost: Mutex<VecDeque<RunId>>,
        transient: Mutex<VecDeque<RunId>>,
    }

    impl FakeFlush {
        fn lose_fence(&self, run_id: RunId) {
            self.fence_lost.lock().unwrap().push_back(run_id);
        }

        fn fail_once(&self, run_id: RunId) {
            self.transient.lock().unwrap().push_back(run_id);
        }

        fn calls(&self) -> Vec<FlushCall> {
            self.calls.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl MarkerFlush for FakeFlush {
        async fn persist(
            &self,
            run_id: RunId,
            _epoch: DispatchEpoch,
            bits: &[(CohortId, PartitionBitmap)],
            positions: &WatchPositions,
        ) -> Result<(), CompletionStoreError> {
            if self
                .fence_lost
                .lock()
                .unwrap()
                .front()
                .is_some_and(|lost| *lost == run_id)
            {
                self.fence_lost.lock().unwrap().pop_front();
                return Err(CompletionStoreError::CompletionFenceLost {
                    run_id,
                    operation: CompletionOperation::PersistObservations,
                });
            }
            if self
                .transient
                .lock()
                .unwrap()
                .front()
                .is_some_and(|failing| *failing == run_id)
            {
                self.transient.lock().unwrap().pop_front();
                return Err(CompletionStoreError::Pg(sqlx::Error::PoolClosed));
            }
            self.calls.lock().unwrap().push(FlushCall {
                run_id,
                bits: bits.to_vec(),
                positions: positions.clone(),
            });
            Ok(())
        }
    }

    fn make_state(flush: FakeFlush, max_batch: u64) -> WatchState<FakeStream, FakeFlush> {
        WatchState::new(FakeStream::default(), flush, max_batch, None)
    }

    #[tokio::test]
    async fn batch_cap_and_completion_trigger_flushes() {
        let run_id = run(1);
        let mut state = make_state(FakeFlush::default(), 3);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;

        // Two non-marker rows: below the batch cap, no flush.
        for offset in 1..=2 {
            state.ingest(WatchItem {
                partition: WatchPartition::new(0),
                next_offset: NextOffset::from_high_watermark(offset),
                marker: None,
            });
        }
        assert!(
            !state.should_flush(),
            "two of three messages does not flush"
        );

        // The third crosses the batch cap.
        state.ingest(marker_item(0, 3, run_id, 10, 0));
        assert!(state.should_flush(), "the batch cap triggers a flush");

        // Completing a cohort triggers a flush regardless of the batch cap.
        let mut fresh = make_state(FakeFlush::default(), 10_000);
        fresh
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;
        for bit in 0..COHORT_PARTITION_COUNT {
            fresh.ingest(marker_item(0, i64::from(bit) + 1, run_id, 10, bit));
        }
        assert!(
            fresh.should_flush(),
            "a completed cohort triggers an immediate flush"
        );
    }

    #[tokio::test]
    async fn flush_persists_dirty_bits_then_clears_them() {
        let run_id = run(1);
        let flush = FakeFlush::default();
        let mut state = make_state(flush, 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;

        state.ingest(marker_item(0, 1, run_id, 10, 5));
        state.flush().await;
        let first = state.flush.calls();
        assert_eq!(first.len(), 1);
        assert_eq!(first[0].run_id, run_id);
        assert_eq!(first[0].bits.len(), 1, "the dirty cohort is persisted");

        // A second flush with no new bits and no advanced positions is a no-op.
        state.flush().await;
        assert_eq!(
            state.flush.calls().len(),
            1,
            "a clean run is not re-flushed"
        );
    }

    #[tokio::test]
    async fn a_failed_persist_is_retried_without_new_traffic() {
        // Coverage advanced but the bits are already clean, so `positions_advanced` is the only
        // thing that gets this run flushed again. Clearing it after a failed persist would strand
        // the run's positions below its captured ends forever on an idle topic.
        let run_id = run(1);
        let flush = FakeFlush::default();
        flush.fail_once(run_id);
        let mut state = make_state(flush, 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;

        state.ingest(WatchItem {
            partition: WatchPartition::new(0),
            next_offset: NextOffset::from_high_watermark(1),
            marker: None,
        });
        state.flush().await;
        assert!(state.flush.calls().is_empty(), "the persist failed");

        state.flush().await;
        assert_eq!(
            state.flush.calls().len(),
            1,
            "the next flush retries without waiting for new traffic"
        );
    }

    #[tokio::test]
    async fn a_run_joining_late_does_not_inherit_earlier_reads() {
        // Coverage is folded in from one shared stream position, so the fold has to land before a run
        // joins. A run that inherited reads made before its ledger existed could settle without ever
        // having seen its own markers.
        let early = run(1);
        let late = run(2);
        let mut state = make_state(FakeFlush::default(), 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(early, 100, start_at(0, 0), &[10])],
            })
            .await;

        for offset in 1..=100 {
            state.ingest(WatchItem {
                partition: WatchPartition::new(0),
                next_offset: NextOffset::from_high_watermark(offset),
                marker: None,
            });
        }

        state
            .apply_directives(&WatchDirectives {
                runs: vec![
                    directive(early, 100, start_at(0, 0), &[10]),
                    directive(late, 100, start_at(0, 50), &[11]),
                ],
            })
            .await;
        state.flush().await;

        let calls = state.flush.calls();
        let persisted = |run_id| {
            calls
                .iter()
                .filter(|call| call.run_id == run_id)
                .next_back()
                .and_then(|call| call.positions.get(WatchPartition::new(0)))
        };
        assert_eq!(
            persisted(early),
            Some(NextOffset::from_high_watermark(100)),
            "the run watched throughout keeps every read the stream made"
        );
        assert_eq!(
            persisted(late),
            Some(NextOffset::from_high_watermark(50)),
            "a run that joined after those reads stays at its dispatch start"
        );
    }

    #[tokio::test]
    async fn lost_fence_drops_the_run() {
        let run_id = run(1);
        let flush = FakeFlush::default();
        flush.lose_fence(run_id);
        let mut state = make_state(flush, 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;

        state.ingest(marker_item(0, 1, run_id, 10, 5));
        state.flush().await;
        assert!(
            !state.runs.contains_key(&run_id),
            "a lost dispatch fence drops the run locally"
        );
        assert!(
            state.flush.calls().is_empty(),
            "the lost-fence flush persisted nothing"
        );
    }

    #[tokio::test]
    async fn truncated_start_drops_the_run_and_tombstones_its_epoch() {
        let early = run(1);
        let later = run(2);
        let mut state = make_state(FakeFlush::default(), 10_000);
        let truncated = || WatchError::Truncated {
            partition: 0,
            requested: 5,
            low: 20,
        };
        *state.stream.seek_result.lock().unwrap() = Some(truncated());
        let published = WatchDirectives {
            runs: vec![
                directive(early, 100, start_at(0, 5), &[10]),
                directive(later, 100, start_at(0, 50), &[11]),
            ],
        };

        state.apply_directives(&published).await;

        assert!(
            !state.runs.contains_key(&early),
            "the run below the low watermark is dropped"
        );
        assert!(
            state.runs.contains_key(&later),
            "a run above the low watermark keeps being watched"
        );

        // The driver republishes the dropped run every tick (PostgreSQL still calls it reconciling).
        // Re-adding it would re-seek, re-truncate and re-drop it forever.
        state.stream.seeks.clear();
        *state.stream.seek_result.lock().unwrap() = Some(truncated());
        state.apply_directives(&published).await;
        assert!(!state.runs.contains_key(&early));
        assert!(
            state.stream.seeks.is_empty(),
            "a tombstoned run must not provoke another seek"
        );

        // A re-dispatch mints a fresh epoch, which is the documented recovery.
        *state.stream.seek_result.lock().unwrap() = None;
        state
            .apply_directives(&WatchDirectives {
                runs: vec![
                    directive(early, 200, start_at(0, 50), &[10]),
                    directive(later, 100, start_at(0, 50), &[11]),
                ],
            })
            .await;
        assert!(
            state.runs.contains_key(&early),
            "a re-dispatched epoch is watched again"
        );
    }

    #[tokio::test]
    async fn seeks_happen_only_when_a_run_is_added_or_rebuilt() {
        let run_a = run(1);
        let run_b = run(2);
        let mut state = make_state(FakeFlush::default(), 10_000);

        // Adding a run seeks once.
        let first = WatchDirectives {
            runs: vec![directive(run_a, 100, start_at(0, 100), &[10])],
        };
        state.apply_directives(&first).await;
        assert_eq!(state.stream.seeks.len(), 1);

        // A steady-state republish of the same set does not re-seek.
        state.apply_directives(&first).await;
        assert_eq!(
            state.stream.seeks.len(),
            1,
            "unchanged set must not re-seek"
        );

        // Adding a second run re-seeks to the minimum start across runs, so markers consumed before
        // its ledger existed are re-read.
        state
            .apply_directives(&WatchDirectives {
                runs: vec![
                    directive(run_a, 100, start_at(0, 100), &[10]),
                    directive(run_b, 100, start_at(0, 50), &[11]),
                ],
            })
            .await;
        assert_eq!(state.stream.seeks.len(), 2);
        assert_eq!(
            state.stream.seeks[1].get(WatchPartition::new(0)),
            Some(NextOffset::from_high_watermark(50)),
            "the seek rewinds to the earliest watched start"
        );

        // Losing the last run releases the assignment instead of leaving the consumer fetching a
        // high-volume topic for nobody.
        state.apply_directives(&WatchDirectives::default()).await;
        assert!(state.runs.is_empty());
        assert_eq!(state.stream.unassigns, 1);
        assert_eq!(state.stream.seeks.len(), 2, "an idle watcher does not seek");
    }

    #[tokio::test]
    async fn a_failed_unassign_stays_owed_and_retries() {
        // Nothing re-triggers the release once the set is already empty, so clearing the owed work
        // on a failed unassign would leak the assignment until a new run is dispatched.
        let run_id = run(1);
        let mut state = make_state(FakeFlush::default(), 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;

        *state.stream.unassign_result.lock().unwrap() =
            Some(WatchError::Consumer(rdkafka::error::KafkaError::Canceled));
        state.apply_directives(&WatchDirectives::default()).await;
        assert_eq!(state.stream.unassigns, 1);
        assert!(state.seek_pending, "a failed unassign stays owed");

        // A steady-state republish of the still-empty set retries it.
        state.apply_directives(&WatchDirectives::default()).await;
        assert_eq!(state.stream.unassigns, 2);
        assert!(!state.seek_pending, "the retry cleared the owed release");
    }

    #[tokio::test]
    async fn flush_persists_start_coverage_for_idle_partitions() {
        // The directive's start covers two partitions; traffic arrives on only one. The flush must
        // still persist the idle partition at its dispatch start, or an idle marker partition
        // would hold `caught_up` (and every negative-verdict settlement) open forever.
        let run_id = run(1);
        let mut start = start_at(0, 10);
        start.insert(WatchPartition::new(1), NextOffset::from_high_watermark(7));
        let mut state = make_state(FakeFlush::default(), 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start, &[10])],
            })
            .await;

        state.ingest(marker_item(0, 11, run_id, 10, 5));
        state.flush().await;

        let calls = state.flush.calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(
            calls[0].positions.get(WatchPartition::new(0)),
            Some(NextOffset::from_high_watermark(11)),
            "the read partition advances to the ingested record's next offset"
        );
        assert_eq!(
            calls[0].positions.get(WatchPartition::new(1)),
            Some(NextOffset::from_high_watermark(7)),
            "the idle partition stays covered at its dispatch start"
        );
    }

    #[tokio::test]
    async fn records_while_a_seek_is_owed_are_dropped_not_claimed() {
        // A transient seek failure leaves the stream on its pre-seek assignment. Folding or
        // advancing coverage from those records would claim reads the rewound run never made.
        let run_id = run(1);
        let mut state = make_state(FakeFlush::default(), 10_000);
        *state.stream.seek_result.lock().unwrap() =
            Some(WatchError::Consumer(rdkafka::error::KafkaError::Canceled));
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 10), &[10])],
            })
            .await;
        assert!(state.seek_pending, "the failed seek stays owed");

        state.ingest(marker_item(0, 500, run_id, 10, 5));
        assert!(
            !state.runs[&run_id].ledger.has_dirty(),
            "a record read on the stale assignment is not folded"
        );
        assert_eq!(
            state.runs[&run_id].positions.get(WatchPartition::new(0)),
            Some(NextOffset::from_high_watermark(10)),
            "coverage stays at the dispatch start until the seek lands"
        );

        // The next directive publish retries the seek; once it lands, records count again.
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 10), &[10])],
            })
            .await;
        assert!(!state.seek_pending);
        state.ingest(marker_item(0, 11, run_id, 10, 5));
        assert!(state.runs[&run_id].ledger.has_dirty());
    }

    #[tokio::test]
    async fn re_dispatch_epoch_change_rebuilds_the_ledger() {
        let run_id = run(1);
        let mut state = make_state(FakeFlush::default(), 10_000);
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 100, start_at(0, 0), &[10])],
            })
            .await;
        state.ingest(marker_item(0, 1, run_id, 10, 5));
        assert!(state.runs[&run_id].ledger.has_dirty());

        // A fresh epoch (re-dispatch) rebuilds the fold from the fresh directive's seeded bits.
        state
            .apply_directives(&WatchDirectives {
                runs: vec![directive(run_id, 200, start_at(0, 0), &[10])],
            })
            .await;
        assert!(
            !state.runs[&run_id].ledger.has_dirty(),
            "a re-dispatch resets the in-memory fold"
        );
    }
}
