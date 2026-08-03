//! The driver's observation pass for one reconciling run, plus the app-owned seams the tests fake.
//!
//! Outcomes land before observed: every non-superseded participation gets a definitive outcome
//! write before `reconcile_observed_at` is stamped, which is this pass's last
//! write. The marker set is the completion *authority* (bitmaps decide complete vs short); the seed
//! group's committed offsets are *liveness only* (they gate whether we may even capture the membership
//! end-watermarks that a negative verdict's settlement proof requires). Hash attribution splits a
//! shortfall into terminal (the cohort diverged or was deleted — supersede) vs retryable (the hash
//! still matches — a gate-off or lossy fleet, error only). A [`CompletionStoreError::CompletionFenceLost`]
//! from any write means a re-dispatch superseded this pass; the caller stops observing the run.
//!
//! Three seams keep the pass testable without a broker or a database: [`CommittedOffsetSource`] and
//! [`TopicOffsetSource`] wrap the kafka layer, [`ObservationStore`] wraps the fenced store writes.
//!
//! Lag is reported through [`ObserveStep`]; the driver aggregates it across the tick's runs into
//! one fleet-wide gauge reading.

use std::collections::HashMap;
use std::time::Duration;

use async_trait::async_trait;
use cohort_core::filters::{CohortId, TeamId};
use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use metrics::counter;
use sqlx::PgPool;
use tracing::warn;

use crate::domain::{
    BehavioralShapeHash, DispatchEpoch, LivenessCheck, MarkerLedger, MarkerWatch, ObservationEnds,
    PartitionBitmap, ReconcileHwms, RunId, SeedGroupCommits, SettledVerdict,
};
use crate::kafka::committed::SeedGroupOffsetReader;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{
    RECONCILE_COHORTS_COMPLETED, RECONCILE_COHORTS_PARTIAL, RECONCILE_COHORTS_SHORTFALL,
};
use crate::store::completion::{
    load_current_behavioral_hashes, load_observation_participations, mark_participation_completed,
    mark_run_observed, persist_observation_ends, record_participation_partial,
    record_participation_shortfall, CompletionStoreError, CurrentBehavioralHash,
    ObservationParticipation,
};
use crate::store::{render_error_chain, RenderedError};

/// The dispatch record the observer needs, lifted from a `Reconciling(DispatchedReconcile)` phase.
#[derive(Debug, Clone)]
pub struct ObserveTarget {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub epoch: DispatchEpoch,
    pub hwms: ReconcileHwms,
    pub watch: MarkerWatch,
}

/// What one observation pass did — the driver's metric/logging surface and the tests' assertion point.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ObserveStep {
    /// Every active participation was already complete; observed with no liveness call.
    ObservedAllComplete,
    /// The seed group has not drained the reconcile records; the run holds for the next tick.
    LivenessLagging(usize),
    /// Liveness passed and the membership end-watermarks were captured; observation resumes next tick.
    EndsCaptured,
    /// Liveness passed earlier but the marker watcher has not read to the captured ends.
    MarkerLagging(usize),
    /// Settled against the marker set and observed.
    Settled(SettleSummary),
}

/// The per-cohort outcome tally of a settlement.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SettleSummary {
    pub completed: usize,
    /// Terminal supersede-by-reconcile (diverged / deleted).
    pub partial: usize,
    /// Retryable shortfall (hash still matches).
    pub shortfall: usize,
    /// Not a single marker was observed — a fleet-wide gate-off signal.
    pub zero_markers: bool,
}

/// Run the observation pass. Returns the step reached; the caller maps a lost fence to an info log.
/// `participations` is passed in rather than read here so one tick reads a run's rows once and both
/// the watch directive and this pass see the same snapshot.
pub async fn observe_run(
    store: &dyn ObservationStore,
    committed: &dyn CommittedOffsetSource,
    topic_ends: &dyn TopicOffsetSource,
    target: &ObserveTarget,
    participations: &[ObservationParticipation],
) -> Result<ObserveStep, ObserveError> {
    let active: Vec<&ObservationParticipation> = participations
        .iter()
        .filter(|participation| participation.superseded_at.is_none())
        .collect();

    // 1. Early success: every active participation is already complete. No liveness needed — the
    //    marker authority is already satisfied. (Vacuously true when everything is superseded: the
    //    supersessions are the definitive outcomes, so the run is observable.)
    if active
        .iter()
        .all(|p| p.bits.is_complete() || p.reconcile_completed_at.is_some())
    {
        for participation in &active {
            store
                .mark_completed(target.run_id, target.epoch, participation.cohort_id)
                .await?;
        }
        store.mark_observed(target.run_id, target.epoch).await?;
        counter!(RECONCILE_COHORTS_COMPLETED).increment(active.len() as u64);
        return Ok(ObserveStep::ObservedAllComplete);
    }

    // 2. Some participation is short — a negative verdict needs both liveness and a settlement proof.
    let proof = match &target.watch.ends {
        None => {
            let commits = committed
                .committed()
                .await
                .map_err(ObserveError::Committed)?;
            match target.hwms.lagging(&commits) {
                LivenessCheck::Lagging(partitions) => {
                    return Ok(ObserveStep::LivenessLagging(partitions.len()));
                }
                LivenessCheck::Passed => {
                    let ends = topic_ends
                        .observation_ends()
                        .await
                        .map_err(ObserveError::TopicEnds)?;
                    store
                        .persist_ends(target.run_id, target.epoch, &ends)
                        .await?;
                    return Ok(ObserveStep::EndsCaptured);
                }
            }
        }
        Some(ends) => match ends.caught_up(&target.watch.positions) {
            None => {
                return Ok(ObserveStep::MarkerLagging(
                    ends.behind(&target.watch.positions),
                ))
            }
            Some(proof) => proof,
        },
    };

    // 3. The proof is in hand: settle against the persisted marker bits.
    let ledger = MarkerLedger::new(
        target.run_id,
        target.team_id,
        active.iter().map(|p| (p.cohort_id, p.bits)),
    );
    let summary = apply_verdict(store, target, &active, ledger.settle(proof)).await?;
    store.mark_observed(target.run_id, target.epoch).await?;
    Ok(ObserveStep::Settled(summary))
}

async fn apply_verdict(
    store: &dyn ObservationStore,
    target: &ObserveTarget,
    active: &[&ObservationParticipation],
    verdict: SettledVerdict,
) -> Result<SettleSummary, ObserveError> {
    match verdict {
        SettledVerdict::AllComplete => {
            for participation in active {
                store
                    .mark_completed(target.run_id, target.epoch, participation.cohort_id)
                    .await?;
            }
            counter!(RECONCILE_COHORTS_COMPLETED).increment(active.len() as u64);
            Ok(SettleSummary {
                completed: active.len(),
                ..SettleSummary::default()
            })
        }
        SettledVerdict::Partial {
            complete,
            incomplete,
        } => {
            for cohort_id in &complete {
                store
                    .mark_completed(target.run_id, target.epoch, *cohort_id)
                    .await?;
            }
            counter!(RECONCILE_COHORTS_COMPLETED).increment(complete.len() as u64);
            let (partial, shortfall) =
                attribute_incomplete(store, target, active, &incomplete).await?;
            Ok(SettleSummary {
                completed: complete.len(),
                partial,
                shortfall,
                zero_markers: false,
            })
        }
        SettledVerdict::NoMarkers => {
            warn!(
                run_id = ?target.run_id,
                team_id = target.team_id.0,
                "zero reconcile markers observed for a settled run — the processor reconcile gate is likely off fleet-wide"
            );
            let incomplete: Vec<(CohortId, PartitionBitmap)> =
                active.iter().map(|p| (p.cohort_id, p.bits)).collect();
            let (partial, shortfall) =
                attribute_incomplete(store, target, active, &incomplete).await?;
            Ok(SettleSummary {
                completed: 0,
                partial,
                shortfall,
                zero_markers: true,
            })
        }
    }
}

/// Split each short cohort into a terminal supersede (hash diverged / cohort deleted / indeterminate)
/// or a retryable shortfall (hash still matches the pinned one).
async fn attribute_incomplete(
    store: &dyn ObservationStore,
    target: &ObserveTarget,
    active: &[&ObservationParticipation],
    incomplete: &[(CohortId, PartitionBitmap)],
) -> Result<(usize, usize), ObserveError> {
    let cohort_ids: Vec<CohortId> = incomplete.iter().map(|(cohort_id, _)| *cohort_id).collect();
    let current = store
        .load_current_hashes(target.team_id, &cohort_ids)
        .await?;
    let pinned: HashMap<CohortId, &BehavioralShapeHash> = active
        .iter()
        .map(|p| (p.cohort_id, &p.behavioral_filters_shape_hash))
        .collect();

    let mut partial = 0;
    let mut shortfall = 0;
    for (cohort_id, bitmap) in incomplete {
        let missing = render_missing(*bitmap);
        let hash_matches = match current.get(cohort_id) {
            Some(CurrentBehavioralHash::Present(current_hash)) => pinned
                .get(cohort_id)
                .is_some_and(|pinned_hash| *pinned_hash == current_hash),
            // Deleted / Indeterminate / absent row all read as diverged: terminal.
            _ => false,
        };
        if hash_matches {
            let error = RenderedError::from_message(format!("reconcile shortfall: {missing}"));
            store
                .record_shortfall(target.run_id, target.epoch, *cohort_id, &error)
                .await?;
            shortfall += 1;
            counter!(RECONCILE_COHORTS_SHORTFALL).increment(1);
        } else {
            let error = RenderedError::from_message(format!(
                "reconcile superseded by a cohort change: {missing}"
            ));
            store
                .record_partial(target.run_id, target.epoch, *cohort_id, &error)
                .await?;
            partial += 1;
            counter!(RECONCILE_COHORTS_PARTIAL).increment(1);
        }
    }
    Ok((partial, shortfall))
}

fn render_missing(bitmap: PartitionBitmap) -> String {
    let missing = bitmap.missing();
    let names: Vec<String> = missing.iter().map(|p| p.get().to_string()).collect();
    format!(
        "{}/{COHORT_PARTITION_COUNT} partitions still missing: {}",
        names.len(),
        names.join(",")
    )
}

/// The seed group's committed offsets — the reconcile liveness signal.
#[async_trait]
pub trait CommittedOffsetSource: Send + Sync {
    async fn committed(&self) -> Result<SeedGroupCommits, SourceError>;
}

/// The membership topic's current end-watermarks — captured at the liveness pass to bound the marker
/// set of this dispatch.
#[async_trait]
pub trait TopicOffsetSource: Send + Sync {
    async fn observation_ends(&self) -> Result<ObservationEnds, SourceError>;
}

/// The observation pass's store surface: the fenced writes plus the two reads it folds over. The
/// real impl delegates to `store::completion`; `sqlx` stays confined below this seam.
#[async_trait]
pub trait ObservationStore: Send + Sync {
    async fn load_participations(
        &self,
        run_id: RunId,
    ) -> Result<Vec<ObservationParticipation>, CompletionStoreError>;
    async fn load_current_hashes(
        &self,
        team_id: TeamId,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, CurrentBehavioralHash>, CompletionStoreError>;
    async fn persist_ends(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        ends: &ObservationEnds,
    ) -> Result<(), CompletionStoreError>;
    async fn mark_completed(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
    ) -> Result<(), CompletionStoreError>;
    async fn record_partial(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
        error: &RenderedError,
    ) -> Result<(), CompletionStoreError>;
    async fn record_shortfall(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
        error: &RenderedError,
    ) -> Result<(), CompletionStoreError>;
    async fn mark_observed(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
    ) -> Result<(), CompletionStoreError>;
}

/// The real observation store over the seeder's pool.
pub struct PgObservationStore {
    pool: PgPool,
}

impl PgObservationStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl ObservationStore for PgObservationStore {
    async fn load_participations(
        &self,
        run_id: RunId,
    ) -> Result<Vec<ObservationParticipation>, CompletionStoreError> {
        load_observation_participations(&self.pool, run_id).await
    }

    async fn load_current_hashes(
        &self,
        team_id: TeamId,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, CurrentBehavioralHash>, CompletionStoreError> {
        load_current_behavioral_hashes(&self.pool, team_id, cohort_ids).await
    }

    async fn persist_ends(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        ends: &ObservationEnds,
    ) -> Result<(), CompletionStoreError> {
        persist_observation_ends(&self.pool, run_id, epoch, ends).await
    }

    async fn mark_completed(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
    ) -> Result<(), CompletionStoreError> {
        mark_participation_completed(&self.pool, run_id, epoch, cohort_id).await
    }

    async fn record_partial(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
        error: &RenderedError,
    ) -> Result<(), CompletionStoreError> {
        record_participation_partial(&self.pool, run_id, epoch, cohort_id, error).await
    }

    async fn record_shortfall(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
        cohort_id: CohortId,
        error: &RenderedError,
    ) -> Result<(), CompletionStoreError> {
        record_participation_shortfall(&self.pool, run_id, epoch, cohort_id, error).await
    }

    async fn mark_observed(
        &self,
        run_id: RunId,
        epoch: DispatchEpoch,
    ) -> Result<(), CompletionStoreError> {
        mark_run_observed(&self.pool, run_id, epoch).await
    }
}

/// An opaque broker-read failure. Broker plumbing lives in the kafka layer, so this carries only the
/// rendered message across the seam.
#[derive(Debug, Clone, thiserror::Error)]
#[error("{0}")]
pub struct SourceError(String);

impl SourceError {
    pub fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ObserveError {
    #[error("reading the seed group's committed offsets")]
    Committed(#[source] SourceError),
    #[error("capturing the membership end watermarks")]
    TopicEnds(#[source] SourceError),
    #[error(transparent)]
    Store(#[from] CompletionStoreError),
}

/// The real committed-offset seam: the seed-group offset reader.
pub struct KafkaCommittedOffsets(SeedGroupOffsetReader);

impl KafkaCommittedOffsets {
    pub fn new(reader: SeedGroupOffsetReader) -> Self {
        Self(reader)
    }
}

#[async_trait]
impl CommittedOffsetSource for KafkaCommittedOffsets {
    async fn committed(&self) -> Result<SeedGroupCommits, SourceError> {
        self.0
            .committed()
            .await
            .map_err(|error| SourceError::new(render_error_chain(&error)))
    }
}

/// The real topic-offset seam: the seed producer's client fetches the membership topic's watermarks.
pub struct KafkaTopicOffsets {
    producer: SeedTileProducer,
    topic: String,
    timeout: Duration,
}

impl KafkaTopicOffsets {
    pub fn new(producer: SeedTileProducer, topic: String, timeout: Duration) -> Self {
        Self {
            producer,
            topic,
            timeout,
        }
    }
}

#[async_trait]
impl TopicOffsetSource for KafkaTopicOffsets {
    async fn observation_ends(&self) -> Result<ObservationEnds, SourceError> {
        let producer = self.producer.clone();
        let topic = self.topic.clone();
        let timeout = self.timeout;
        let positions =
            tokio::task::spawn_blocking(move || producer.capture_topic_offsets(&topic, timeout))
                .await
                .map_err(|error| {
                    SourceError::new(format!("join membership watermark task: {error}"))
                })?
                .map_err(|error| SourceError::new(render_error_chain(&error)))?;
        Ok(ObservationEnds::from_positions(&positions))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;

    use uuid::Uuid;

    use crate::domain::{
        CommittedOffset, MarkerPartition, MembershipPartition, NextOffset, ProducedOffset,
        SeedPartition, WatchPositions,
    };
    use crate::store::completion::CompletionOperation;

    fn run_id() -> RunId {
        RunId(Uuid::from_u128(7))
    }

    fn epoch() -> DispatchEpoch {
        use chrono::TimeZone;
        DispatchEpoch::from_dispatched_at(chrono::Utc.timestamp_opt(1_700_000_000, 0).unwrap())
    }

    fn hash(value: &str) -> BehavioralShapeHash {
        BehavioralShapeHash::parse(value).unwrap()
    }

    fn full_hwms() -> ReconcileHwms {
        let offsets: BTreeMap<SeedPartition, ProducedOffset> =
            SeedPartition::all(COHORT_PARTITION_COUNT)
                .unwrap()
                .map(|partition| (partition, ProducedOffset::new(100)))
                .collect();
        ReconcileHwms::new(offsets).unwrap()
    }

    fn commits(delta: i64) -> SeedGroupCommits {
        let mut commits = SeedGroupCommits::new();
        for partition in SeedPartition::all(COHORT_PARTITION_COUNT).unwrap() {
            commits.insert(partition, CommittedOffset::new(100 + delta));
        }
        commits
    }

    fn participation(cohort: i32, bits: PartitionBitmap) -> ObservationParticipation {
        ObservationParticipation {
            cohort_id: CohortId(cohort),
            behavioral_filters_shape_hash: hash("pinned"),
            bits,
            reconcile_completed_at: None,
            superseded_at: None,
            stamped_at: None,
        }
    }

    fn complete_bits() -> PartitionBitmap {
        PartitionBitmap::from_bits(-1).unwrap()
    }

    fn one_short_bits() -> PartitionBitmap {
        let mut bitmap = PartitionBitmap::default();
        for index in 1..COHORT_PARTITION_COUNT {
            bitmap.set(MarkerPartition::new(index).unwrap());
        }
        bitmap
    }

    fn target(ends: Option<ObservationEnds>) -> ObserveTarget {
        ObserveTarget {
            run_id: run_id(),
            team_id: TeamId(2),
            epoch: epoch(),
            hwms: full_hwms(),
            watch: MarkerWatch {
                positions: watched_positions(),
                ends,
            },
        }
    }

    /// Where the watcher has read to. Past [`caught_up_ends`], short of [`pending_ends`].
    fn watched_positions() -> WatchPositions {
        let mut positions = WatchPositions::new();
        positions.insert(
            MembershipPartition::new(0),
            NextOffset::from_high_watermark(10),
        );
        positions
    }

    /// Ends the watcher's positions already satisfy, so settlement is reachable.
    fn caught_up_ends() -> ObservationEnds {
        let mut ends = ObservationEnds::new();
        ends.insert(
            MembershipPartition::new(0),
            NextOffset::from_high_watermark(10),
        );
        ends
    }

    fn pending_ends() -> ObservationEnds {
        let mut ends = ObservationEnds::new();
        ends.insert(
            MembershipPartition::new(0),
            NextOffset::from_high_watermark(20),
        );
        ends
    }

    #[derive(Default)]
    struct FakeCommittedOffsets {
        commits: Mutex<Option<SeedGroupCommits>>,
        calls: AtomicUsize,
    }

    impl FakeCommittedOffsets {
        fn returning(commits: SeedGroupCommits) -> Self {
            Self {
                commits: Mutex::new(Some(commits)),
                calls: AtomicUsize::new(0),
            }
        }

        fn calls(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl CommittedOffsetSource for FakeCommittedOffsets {
        async fn committed(&self) -> Result<SeedGroupCommits, SourceError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.commits
                .lock()
                .unwrap()
                .clone()
                .ok_or_else(|| SourceError::new("no scripted commits"))
        }
    }

    #[derive(Default)]
    struct FakeTopicOffsets {
        calls: AtomicUsize,
    }

    #[async_trait]
    impl TopicOffsetSource for FakeTopicOffsets {
        async fn observation_ends(&self) -> Result<ObservationEnds, SourceError> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(pending_ends())
        }
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum StoreCall {
        Completed(CohortId),
        Partial(CohortId),
        Shortfall(CohortId),
        PersistEnds(ObservationEnds),
        Observed,
    }

    #[derive(Default)]
    struct FakeStore {
        participations: Vec<ObservationParticipation>,
        current: HashMap<CohortId, CurrentBehavioralHash>,
        calls: Mutex<Vec<StoreCall>>,
        fence_lost_on_completed: bool,
    }

    impl FakeStore {
        fn calls(&self) -> Vec<StoreCall> {
            self.calls.lock().unwrap().clone()
        }

        fn observed(&self) -> bool {
            self.calls().contains(&StoreCall::Observed)
        }
    }

    #[async_trait]
    impl ObservationStore for FakeStore {
        async fn load_participations(
            &self,
            _run_id: RunId,
        ) -> Result<Vec<ObservationParticipation>, CompletionStoreError> {
            Ok(self.participations.clone())
        }

        async fn load_current_hashes(
            &self,
            _team_id: TeamId,
            cohort_ids: &[CohortId],
        ) -> Result<HashMap<CohortId, CurrentBehavioralHash>, CompletionStoreError> {
            Ok(cohort_ids
                .iter()
                .filter_map(|cohort_id| {
                    self.current
                        .get(cohort_id)
                        .map(|state| (*cohort_id, state.clone()))
                })
                .collect())
        }

        async fn persist_ends(
            &self,
            _run_id: RunId,
            _epoch: DispatchEpoch,
            ends: &ObservationEnds,
        ) -> Result<(), CompletionStoreError> {
            self.calls
                .lock()
                .unwrap()
                .push(StoreCall::PersistEnds(ends.clone()));
            Ok(())
        }

        async fn mark_completed(
            &self,
            run_id: RunId,
            _epoch: DispatchEpoch,
            cohort_id: CohortId,
        ) -> Result<(), CompletionStoreError> {
            if self.fence_lost_on_completed {
                return Err(CompletionStoreError::CompletionFenceLost {
                    run_id,
                    operation: CompletionOperation::MarkCompleted,
                });
            }
            self.calls
                .lock()
                .unwrap()
                .push(StoreCall::Completed(cohort_id));
            Ok(())
        }

        async fn record_partial(
            &self,
            _run_id: RunId,
            _epoch: DispatchEpoch,
            cohort_id: CohortId,
            _error: &RenderedError,
        ) -> Result<(), CompletionStoreError> {
            self.calls
                .lock()
                .unwrap()
                .push(StoreCall::Partial(cohort_id));
            Ok(())
        }

        async fn record_shortfall(
            &self,
            _run_id: RunId,
            _epoch: DispatchEpoch,
            cohort_id: CohortId,
            _error: &RenderedError,
        ) -> Result<(), CompletionStoreError> {
            self.calls
                .lock()
                .unwrap()
                .push(StoreCall::Shortfall(cohort_id));
            Ok(())
        }

        async fn mark_observed(
            &self,
            _run_id: RunId,
            _epoch: DispatchEpoch,
        ) -> Result<(), CompletionStoreError> {
            self.calls.lock().unwrap().push(StoreCall::Observed);
            Ok(())
        }
    }

    #[tokio::test]
    async fn all_complete_early_exits_without_any_liveness_call() {
        let store = FakeStore {
            participations: vec![
                participation(10, complete_bits()),
                participation(11, complete_bits()),
            ],
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::default();
        let ends = FakeTopicOffsets::default();

        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(None),
            &store.participations,
        )
        .await
        .unwrap();

        assert_eq!(step, ObserveStep::ObservedAllComplete);
        assert_eq!(committed.calls(), 0, "no liveness read on the early exit");
        assert_eq!(ends.calls.load(Ordering::SeqCst), 0);
        assert_eq!(
            store.calls(),
            vec![
                StoreCall::Completed(CohortId(10)),
                StoreCall::Completed(CohortId(11)),
                StoreCall::Observed,
            ],
            "outcomes land before observed"
        );
    }

    #[tokio::test]
    async fn lagging_liveness_holds_the_run_without_persisting_ends() {
        let store = FakeStore {
            participations: vec![participation(10, PartitionBitmap::default())],
            ..FakeStore::default()
        };
        // committed == produced ⇒ still lagging (the +1 contract).
        let committed = FakeCommittedOffsets::returning(commits(0));
        let ends = FakeTopicOffsets::default();

        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(None),
            &store.participations,
        )
        .await
        .unwrap();

        assert_eq!(
            step,
            ObserveStep::LivenessLagging(COHORT_PARTITION_COUNT as usize)
        );
        assert_eq!(
            ends.calls.load(Ordering::SeqCst),
            0,
            "no ends captured while lagging"
        );
        assert!(store.calls().is_empty(), "a held run writes nothing");
    }

    #[tokio::test]
    async fn ends_are_captured_once_then_liveness_is_skipped() {
        let store = FakeStore {
            participations: vec![participation(10, PartitionBitmap::default())],
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::returning(commits(1));
        let ends = FakeTopicOffsets::default();

        // First pass: liveness passes, ends are captured and persisted.
        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(None),
            &store.participations,
        )
        .await
        .unwrap();
        assert_eq!(step, ObserveStep::EndsCaptured);
        assert_eq!(committed.calls(), 1);
        assert_eq!(ends.calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            store.calls(),
            vec![StoreCall::PersistEnds(pending_ends())],
            "the captured ends are persisted verbatim"
        );

        // Second pass with ends present but positions behind: liveness is not re-read.
        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(Some(pending_ends())),
            &store.participations,
        )
        .await
        .unwrap();
        assert_eq!(step, ObserveStep::MarkerLagging(1));
        assert_eq!(committed.calls(), 1, "ends present skips the liveness read");
        assert!(!store.observed());
    }

    #[tokio::test]
    async fn zero_markers_settles_to_shortfalls_and_observes() {
        let store = FakeStore {
            participations: vec![
                participation(10, PartitionBitmap::default()),
                participation(11, PartitionBitmap::default()),
            ],
            current: HashMap::from([
                (CohortId(10), CurrentBehavioralHash::Present(hash("pinned"))),
                (CohortId(11), CurrentBehavioralHash::Present(hash("pinned"))),
            ]),
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::default();
        let ends = FakeTopicOffsets::default();

        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(Some(caught_up_ends())),
            &store.participations,
        )
        .await
        .unwrap();

        assert_eq!(
            step,
            ObserveStep::Settled(SettleSummary {
                completed: 0,
                partial: 0,
                shortfall: 2,
                zero_markers: true,
            })
        );
        assert_eq!(
            store.calls(),
            vec![
                StoreCall::Shortfall(CohortId(10)),
                StoreCall::Shortfall(CohortId(11)),
                StoreCall::Observed,
            ],
            "matching hashes are retryable shortfalls, and observed lands last"
        );
    }

    #[tokio::test]
    async fn hash_attribution_splits_diverged_deleted_indeterminate_and_matching() {
        let store = FakeStore {
            participations: vec![
                participation(10, complete_bits()),  // complete
                participation(11, one_short_bits()), // diverged ⇒ partial
                participation(12, one_short_bits()), // matching ⇒ shortfall
                participation(13, one_short_bits()), // deleted ⇒ partial
                participation(14, one_short_bits()), // indeterminate ⇒ partial
                participation(15, one_short_bits()), // absent row ⇒ partial
            ],
            current: HashMap::from([
                (
                    CohortId(11),
                    CurrentBehavioralHash::Present(hash("diverged")),
                ),
                (CohortId(12), CurrentBehavioralHash::Present(hash("pinned"))),
                (CohortId(13), CurrentBehavioralHash::Deleted),
                (CohortId(14), CurrentBehavioralHash::Indeterminate),
            ]),
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::default();
        let ends = FakeTopicOffsets::default();

        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(Some(caught_up_ends())),
            &store.participations,
        )
        .await
        .unwrap();

        assert_eq!(
            step,
            ObserveStep::Settled(SettleSummary {
                completed: 1,
                partial: 4,
                shortfall: 1,
                zero_markers: false,
            })
        );
        let calls = store.calls();
        assert_eq!(calls.first(), Some(&StoreCall::Completed(CohortId(10))));
        assert!(calls.contains(&StoreCall::Partial(CohortId(11))));
        assert!(calls.contains(&StoreCall::Shortfall(CohortId(12))));
        assert!(calls.contains(&StoreCall::Partial(CohortId(13))));
        assert!(calls.contains(&StoreCall::Partial(CohortId(14))));
        assert!(calls.contains(&StoreCall::Partial(CohortId(15))));
        assert_eq!(
            calls.last(),
            Some(&StoreCall::Observed),
            "observed lands last"
        );
    }

    #[tokio::test]
    async fn superseded_participations_are_excluded_and_all_superseded_observes() {
        let mut superseded = participation(10, PartitionBitmap::default());
        superseded.superseded_at = Some(chrono::Utc::now());
        let store = FakeStore {
            participations: vec![superseded],
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::default();
        let ends = FakeTopicOffsets::default();

        let step = observe_run(
            &store,
            &committed,
            &ends,
            &target(None),
            &store.participations,
        )
        .await
        .unwrap();

        assert_eq!(step, ObserveStep::ObservedAllComplete);
        assert_eq!(
            store.calls(),
            vec![StoreCall::Observed],
            "supersessions are already definitive outcomes; only observed is stamped"
        );
    }

    #[tokio::test]
    async fn fence_loss_mid_pass_stops_cleanly_without_observing() {
        let store = FakeStore {
            participations: vec![participation(10, complete_bits())],
            fence_lost_on_completed: true,
            ..FakeStore::default()
        };
        let committed = FakeCommittedOffsets::default();
        let ends = FakeTopicOffsets::default();

        let error = observe_run(
            &store,
            &committed,
            &ends,
            &target(None),
            &store.participations,
        )
        .await
        .unwrap_err();

        assert!(matches!(
            error,
            ObserveError::Store(CompletionStoreError::CompletionFenceLost { .. })
        ));
        assert!(
            !store.observed(),
            "a lost fence never reaches the observed stamp"
        );
    }
}
