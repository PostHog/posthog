//! App layer: the automatic reconcile-dispatch driver, dark by default. Ticked from the orchestrator
//! poll arm after `fill_claim_slots`, it discovers seeding/reconciling behavioral runs, transitions a
//! fully-confirmed run `seeding → reconciling`, produces the reconcile control tiles, and persists the
//! dispatch record (produce HWMs + marker-watch start positions + fence epoch) through the same store
//! path the CLI uses. Its second, independently gated half publishes the marker-watch directives and
//! runs the per-run observation pass; either half alone is a valid configuration.
//!
//! Dispatch runs in a spawned task, never inline: producing `cohorts × COHORT_PARTITION_COUNT` control
//! tiles and awaiting their delivery acks can exceed the orchestrator's liveness deadline. An
//! in-flight set dedupes tasks on this replica; the CAS plus the ruling fence (a later `record` sets
//! the fence, the processor supersedes duplicate tiles) make cross-replica duplicates safe.
//!
//! A tick observes many runs, so the lag gauges are published once here from the worst reading of
//! the tick: they report fleet-wide and clear themselves once nothing lags. The observation pass's
//! two broker reads are likewise tick-scoped — see [`TickBrokerSnapshot`].

use std::collections::hash_map::Entry;
use std::collections::{HashMap, HashSet};
use std::num::NonZeroUsize;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use common_types::cohort::TeamAllowlist;
use metrics::{counter, gauge, histogram};
use sqlx::PgPool;
use tokio::sync::{watch, Semaphore};
use tokio::task::JoinError;
use tracing::{info, warn};

use cohort_core::partitioner::COHORT_PARTITION_COUNT;

use crate::config::Config;
use crate::domain::{
    CompletionPhase, DispatchEpoch, DispatchedReconcile, MarkerWatch, ObservationEnds,
    PartitionBitmap, ProducedOffset, ReconcileHwms, ReconcileHwmsError, RunId, SeedGroupCommits,
};
use crate::kafka::producer::{CaptureOffsetsError, SeedTileProducer};
use crate::observability::metrics::{
    RECONCILE_CAS_LOST, RECONCILE_DISPATCHES, RECONCILE_DISPATCHES_IN_FLIGHT,
    RECONCILE_LIVENESS_LAGGING_PARTITIONS, RECONCILE_MARKER_WATCH_LAG,
    RECONCILE_OBSERVATION_PASS_SECONDS, RECONCILE_OBSERVATION_STALLED_AGE_SECONDS,
    RECONCILE_OBSERVE_ERRORS, RECONCILE_RECORD_INVALID, RECONCILE_RUNS_UNDISPATCHED,
    RECONCILE_ZERO_MARKER_RUNS, RUNS_OBSERVED, RUNS_RECONCILING,
};
use crate::store::completion::{
    cas_run_reconciling, confirm_reconciling, discover_completions,
    mark_run_observed_unreconcilable, runs_with_all_chunks_confirmed, CompletionStoreError,
    DiscoveredCompletion, ObservationParticipation, ReconcilingClaim,
};
use crate::store::runs::ReconcileRunError;

use super::observe::{
    observe_run, CommittedOffsetSource, ObservationStore, ObserveError, ObserveStep, ObserveTarget,
    PgObservationStore, SourceError, TopicOffsetSource,
};
use super::reconcile_dispatch::{
    execute_reconcile_dispatch, prepare_reconcile_dispatch, CertifiedDispatch,
    CompletionRequirement, PrepareReconcileDispatchError, PreparedDispatch, ReconcileDispatchError,
    ReconcileDispatchReceipt, RegisterBackfillConfirmation,
};
use super::watch::{WatchDirective, WatchDirectives};

/// Timeout for the blocking Kafka metadata and watermark calls the dispatch makes.
const KAFKA_METADATA_TIMEOUT: Duration = Duration::from_secs(10);

/// Whether automatic dispatch is armed. `Enabled` carries the register-backfill attestation, so the
/// driver cannot be constructed without it.
#[derive(Debug, Clone, Copy)]
pub enum AutoDispatchPolicy {
    Disabled,
    Enabled(RegisterBackfillConfirmation),
}

impl AutoDispatchPolicy {
    /// Resolve the policy from configuration. Arming automatic dispatch requires both the enable flag
    /// and the register-backfill attestation, and the seed partition count must match the shared
    /// cohort contract (dispatch produces to exactly [`COHORT_PARTITION_COUNT`] partitions).
    pub fn from_config(config: &Config) -> Result<Self, AutoDispatchPolicyError> {
        if !config.seeder_reconcile_auto_dispatch_enabled {
            return Ok(Self::Disabled);
        }
        if !config.seeder_confirm_register_backfilled {
            return Err(AutoDispatchPolicyError::MissingAttestation);
        }
        if config.cohort_partition_count != COHORT_PARTITION_COUNT {
            return Err(AutoDispatchPolicyError::PartitionCountMismatch {
                configured: config.cohort_partition_count,
            });
        }
        Ok(Self::Enabled(
            RegisterBackfillConfirmation::confirmed_by_env(),
        ))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum AutoDispatchPolicyError {
    #[error(
        "SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED requires SEEDER_CONFIRM_REGISTER_BACKFILLED to attest \
         that runs were seeded after membership-register writers deployed"
    )]
    MissingAttestation,
    #[error(
        "automatic reconcile dispatch requires COHORT_PARTITION_COUNT == {expected}, got {configured}",
        expected = COHORT_PARTITION_COUNT
    )]
    PartitionCountMismatch { configured: u32 },
}

/// Whether the reconcile observer (marker watcher + observation pass) is armed. A separate gate from
/// [`AutoDispatchPolicy`]: observation can run against CLI-dispatched runs without auto-dispatch, and
/// auto-dispatch can run without the observer (a two-step rollout).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ObservePolicy {
    Disabled,
    Enabled,
}

impl ObservePolicy {
    pub fn from_config(config: &Config) -> Result<Self, ObservePolicyError> {
        if !config.seeder_reconcile_observer_enabled {
            return Ok(Self::Disabled);
        }
        if config.cohort_partition_count != COHORT_PARTITION_COUNT {
            return Err(ObservePolicyError::PartitionCountMismatch {
                configured: config.cohort_partition_count,
            });
        }
        Ok(Self::Enabled)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ObservePolicyError {
    #[error(
        "the reconcile observer requires COHORT_PARTITION_COUNT == {expected}, got {configured}",
        expected = COHORT_PARTITION_COUNT
    )]
    PartitionCountMismatch { configured: u32 },
}

/// Whether a spawned task starts a fresh dispatch (CAS out of `seeding`) or re-dispatches an
/// already-`reconciling` run (confirm claim) to heal a missing or stale dispatch record.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DispatchKind {
    Fresh,
    ReDispatch,
}

/// The dispatch half's dependencies, cheap to clone into a spawned dispatch task.
#[derive(Clone)]
struct DispatchArm {
    pool: PgPool,
    producer: SeedTileProducer,
    membership_topic: Arc<str>,
    max_inflight: NonZeroUsize,
    /// Caps how many dispatch tasks this replica runs at once. Every task produces
    /// `cohorts × COHORT_PARTITION_COUNT` tiles through the producer the chunk pipeline shares, so
    /// unbounded fan-out would back the core seeding path off its own queue.
    dispatch_slots: Arc<Semaphore>,
    register_backfill: RegisterBackfillConfirmation,
}

/// The observation half's dependencies: the store seam, the two broker-read seams, and the channel
/// the driver republishes the watched-run set on each tick.
struct ObserveArm {
    store: Arc<dyn ObservationStore>,
    committed: Arc<dyn CommittedOffsetSource>,
    topic_ends: Arc<dyn TopicOffsetSource>,
    directives: watch::Sender<WatchDirectives>,
}

/// The completion driver, ticked from the orchestrator poll arm. It carries whichever halves are
/// armed: `dispatch` transitions confirmed runs into `reconciling` and produces reconcile tiles;
/// `observe` publishes marker-watch directives and runs the observation pass. Either half alone is a
/// valid configuration — construction requires at least one, encoded as the driver existing at all.
pub struct CompletionDriver {
    pool: PgPool,
    allowlist: TeamAllowlist,
    dispatch: Option<DispatchArm>,
    observe: Option<ObserveArm>,
    in_flight: Arc<Mutex<HashSet<RunId>>>,
    /// Runs already reported as carrying an unusable dispatch record, mapped to when this replica
    /// first saw them in that phase, so the warn and counter fire per broken record rather than per
    /// poll tick and the stalled gauge ages from the phase. Pruned each tick to the runs still in it.
    reported_undispatched: Mutex<HashMap<RunId, DateTime<Utc>>>,
}

impl CompletionDriver {
    /// Base driver with neither half armed. `main` adds the halves the config enables.
    pub fn new(pool: PgPool, allowlist: TeamAllowlist) -> Self {
        Self {
            pool,
            allowlist,
            dispatch: None,
            observe: None,
            in_flight: Arc::new(Mutex::new(HashSet::new())),
            reported_undispatched: Mutex::new(HashMap::new()),
        }
    }

    /// Arm automatic reconcile dispatch.
    pub fn with_dispatch(
        mut self,
        producer: SeedTileProducer,
        membership_topic: String,
        max_inflight: NonZeroUsize,
        max_concurrent_dispatches: NonZeroUsize,
        register_backfill: RegisterBackfillConfirmation,
    ) -> Self {
        self.dispatch = Some(DispatchArm {
            pool: self.pool.clone(),
            producer,
            membership_topic: Arc::from(membership_topic),
            max_inflight,
            dispatch_slots: Arc::new(Semaphore::new(max_concurrent_dispatches.get())),
            register_backfill,
        });
        self
    }

    /// Arm the reconcile observer, publishing directives on `directives` for the marker-watch task.
    /// The store seam is built over the driver's own pool.
    pub fn with_observe(
        mut self,
        committed: Arc<dyn CommittedOffsetSource>,
        topic_ends: Arc<dyn TopicOffsetSource>,
        directives: watch::Sender<WatchDirectives>,
    ) -> Self {
        self.observe = Some(ObserveArm {
            store: Arc::new(PgObservationStore::new(self.pool.clone())),
            committed,
            topic_ends,
            directives,
        });
        self
    }

    /// One driver pass: classify every discovered run, dispatch the ones that need it (dispatch arm),
    /// and observe the reconciling ones (observe arm). A discovery failure is logged and retried next
    /// tick; the dark path (driver absent) costs zero queries.
    pub async fn tick(&self) {
        let discovered = match discover_completions(&self.pool, &self.allowlist).await {
            Ok(discovered) => discovered,
            Err(error) => {
                warn!(error = %error, "completion discovery failed");
                return;
            }
        };

        let now = Utc::now();
        let mut reconciling = 0_u64;
        let mut oldest_stalled: Option<DateTime<Utc>> = None;
        let mut directives = Vec::new();
        let mut undispatched = HashSet::new();
        // Collected across the loop and resolved with one batched chunk-ledger read below, so the
        // pass never issues a query per planned run.
        let mut planned = Vec::new();
        // Worst lag seen this tick, published once below so the gauges read fleet-wide and clear
        // themselves when nothing is lagging.
        let mut liveness_lagging = 0_usize;
        let mut marker_lag = 0_usize;
        let mut observation_elapsed = Duration::ZERO;
        let broker = self.observe.as_ref().map(TickBrokerSnapshot::new);

        for completion in discovered {
            match &completion.phase {
                CompletionPhase::Observed => {
                    reconciling += 1;
                }
                CompletionPhase::Reconciling(dispatched) => {
                    reconciling += 1;
                    // Age from the dispatch, not the run's creation: a run that legitimately spent
                    // days seeding would otherwise read as stalled-by-days the instant it dispatches.
                    track_oldest(&mut oldest_stalled, dispatched.epoch.as_datetime());
                    if let (Some(observe), Some(broker)) = (&self.observe, &broker) {
                        let started = Instant::now();
                        // One read per run per tick, shared by the watch directive and the pass.
                        match observe.store.load_participations(completion.run_id).await {
                            Ok(participations) => {
                                directives.push(build_directive(
                                    &completion,
                                    dispatched,
                                    &participations,
                                ));
                                let outcome = self
                                    .observe_reconciling(
                                        observe,
                                        broker,
                                        &completion,
                                        dispatched,
                                        &participations,
                                    )
                                    .await;
                                liveness_lagging = liveness_lagging.max(outcome.liveness_lagging);
                                marker_lag = marker_lag.max(outcome.marker_lag);
                            }
                            Err(error) => {
                                warn!(error = %error, run_id = ?completion.run_id, "loading participations for the observation pass failed");
                            }
                        }
                        observation_elapsed += started.elapsed();
                    }
                }
                CompletionPhase::ReconcilingUndispatched(reason) => {
                    reconciling += 1;
                    undispatched.insert(completion.run_id);
                    // A run holds this phase until a re-dispatch records — across a whole
                    // observe-only rollout window, if auto-dispatch is off. Count and warn once per
                    // stretch so the signal measures broken dispatch records rather than how many
                    // ticks have looked at the same one.
                    let (first_sighting, since) = {
                        let mut reported = lock_recoverable(&self.reported_undispatched);
                        match reported.entry(completion.run_id) {
                            Entry::Occupied(entry) => (false, *entry.get()),
                            Entry::Vacant(entry) => (true, *entry.insert(now)),
                        }
                    };
                    // Age from the phase, not the run: days of legitimate seeding would otherwise
                    // read as stalled the instant the dispatch record breaks.
                    track_oldest(&mut oldest_stalled, since);
                    if first_sighting {
                        counter!(RECONCILE_RECORD_INVALID).increment(1);
                    }
                    // Only the dispatch arm can heal an undispatched run; observe-only leaves it for a
                    // CLI re-dispatch.
                    if self.dispatch.is_some() {
                        if first_sighting {
                            warn!(
                                run_id = ?completion.run_id,
                                ?reason,
                                "reconciling run has no usable dispatch record; re-dispatching"
                            );
                        }
                        self.spawn_dispatch(completion.run_id, DispatchKind::ReDispatch);
                    } else if first_sighting {
                        warn!(
                            run_id = ?completion.run_id,
                            ?reason,
                            "reconciling run has no usable dispatch record; re-dispatch required (auto-dispatch off)"
                        );
                    }
                }
                CompletionPhase::SeedingPlanned => {
                    // Only the dispatch arm consumes these, so observe-only skips the batch read.
                    if self.dispatch.is_some() {
                        planned.push(completion.run_id);
                    }
                }
                CompletionPhase::SeedingUnplanned => {}
                CompletionPhase::SeedingAnomalous => {
                    warn!(
                        run_id = ?completion.run_id,
                        "seeding run carries reconcile columns; skipping until it is reconciled by hand"
                    );
                }
            }
        }

        // Forget runs that have left the phase, so a later relapse counts as a fresh event.
        lock_recoverable(&self.reported_undispatched)
            .retain(|run_id, _| undispatched.contains(run_id));

        gauge!(RUNS_RECONCILING).set(reconciling as f64);
        // A standing count: the first-sighting counter goes flat while runs stay stranded.
        gauge!(RECONCILE_RUNS_UNDISPATCHED).set(undispatched.len() as f64);

        match runs_with_all_chunks_confirmed(&self.pool, &planned).await {
            Ok(confirmed) => {
                for run_id in confirmed {
                    self.spawn_dispatch(run_id, DispatchKind::Fresh);
                }
            }
            Err(error) => {
                warn!(error = %error, "reading chunk progress for dispatch failed");
            }
        }

        if let Some(observe) = &self.observe {
            // send_replace never fails even if the watch task is gone; a dead task is caught by its own
            // lifecycle deadline.
            observe
                .directives
                .send_replace(WatchDirectives { runs: directives });
            gauge!(RECONCILE_LIVENESS_LAGGING_PARTITIONS).set(liveness_lagging as f64);
            gauge!(RECONCILE_MARKER_WATCH_LAG).set(marker_lag as f64);
            let stalled_age = oldest_stalled
                .map(|since| (now - since).num_seconds().max(0) as f64)
                .unwrap_or(0.0);
            gauge!(RECONCILE_OBSERVATION_STALLED_AGE_SECONDS).set(stalled_age);
            // The pass runs inline on the orchestrator's liveness path; this leads the deadline.
            histogram!(RECONCILE_OBSERVATION_PASS_SECONDS)
                .record(observation_elapsed.as_secs_f64());
        }
    }

    /// Run the observation pass for one reconciling run, returning what the tick's aggregate gauges
    /// need. Per-run counters are emitted here, where the step is known.
    async fn observe_reconciling(
        &self,
        observe: &ObserveArm,
        broker: &TickBrokerSnapshot<'_>,
        completion: &DiscoveredCompletion,
        dispatched: &DispatchedReconcile,
        participations: &[ObservationParticipation],
    ) -> ObserveOutcome {
        let target = ObserveTarget {
            run_id: completion.run_id,
            team_id: completion.team_id,
            epoch: dispatched.epoch,
            hwms: dispatched.hwms.clone(),
            watch: dispatched.watch.clone(),
        };
        match observe_run(
            observe.store.as_ref(),
            broker,
            broker,
            &target,
            participations,
        )
        .await
        {
            Ok(ObserveStep::Settled(summary)) => {
                if summary.completed + summary.partial + summary.shortfall > 0
                    || summary.zero_markers
                {
                    counter!(RUNS_OBSERVED).increment(1);
                }
                if summary.zero_markers {
                    // A counter, not a gauge: a settled run is `Observed` on the next tick, so a
                    // fleet-wide gate-off would be a single-tick blip most scrapes would miss.
                    counter!(RECONCILE_ZERO_MARKER_RUNS).increment(1);
                }
                ObserveOutcome::default()
            }
            Ok(ObserveStep::ObservedAllComplete) => {
                counter!(RUNS_OBSERVED).increment(1);
                ObserveOutcome::default()
            }
            Ok(ObserveStep::LivenessLagging(partitions)) => ObserveOutcome {
                liveness_lagging: partitions,
                ..ObserveOutcome::default()
            },
            Ok(ObserveStep::MarkerLagging(lag)) => ObserveOutcome {
                marker_lag: lag,
                ..ObserveOutcome::default()
            },
            Ok(ObserveStep::EndsCaptured) => ObserveOutcome::default(),
            Err(ObserveError::Store(CompletionStoreError::CompletionFenceLost {
                operation,
                ..
            })) => {
                info!(
                    run_id = ?completion.run_id,
                    %operation,
                    "observation lost the dispatch fence; a re-dispatch superseded this pass"
                );
                ObserveOutcome::default()
            }
            Err(error) => {
                // The default outcome reads as healthy on both lag gauges, so a failed pass needs
                // its own signal to tell "nothing is lagging" from "we could not tell".
                counter!(RECONCILE_OBSERVE_ERRORS).increment(1);
                warn!(error = %error, run_id = ?completion.run_id, "observing the reconciling run failed");
                ObserveOutcome::default()
            }
        }
    }

    /// Spawns a dispatch task unless the dispatch arm is disarmed, one is already in flight for this
    /// run on this replica, or the arm is at its concurrency budget. A run that misses the budget
    /// keeps its phase and is picked up on a later tick.
    fn spawn_dispatch(&self, run_id: RunId, kind: DispatchKind) {
        let Some(dispatch) = &self.dispatch else {
            return;
        };
        let Ok(permit) = Arc::clone(&dispatch.dispatch_slots).try_acquire_owned() else {
            return;
        };
        if !lock_recoverable(&self.in_flight).insert(run_id) {
            return;
        }
        let context = dispatch.clone();
        let guard = InFlightGuard::enter(Arc::clone(&self.in_flight), run_id);
        let dispatch = tokio::spawn(async move {
            let _permit = permit;
            let _guard = guard;
            run_dispatch(&context, run_id, kind).await;
        });
        // `run_dispatch` reports its own failures, so a `JoinError` is a panic. Dropping the handle
        // would make a deterministic one — a poison row, say — an invisible per-tick respawn loop.
        tokio::spawn(async move {
            if let Err(error) = dispatch.await {
                counter!(RECONCILE_DISPATCHES, "outcome" => "panicked").increment(1);
                warn!(error = %error, run_id = ?run_id, "reconcile dispatch task panicked");
            }
        });
    }
}

/// What one run's observation pass contributed to the tick's aggregate gauges.
#[derive(Debug, Clone, Copy, Default)]
struct ObserveOutcome {
    liveness_lagging: usize,
    marker_lag: usize,
}

/// Memoizes the two broker reads for one tick, failures included. Both ask about the cluster, not
/// about a run, so every run in a tick shares one answer — and the tick runs inside the orchestrator's
/// liveness budget, where one call per run against a slow broker costs the reconciling-run count
/// times the offsets timeout.
struct TickBrokerSnapshot<'a> {
    committed_source: &'a dyn CommittedOffsetSource,
    ends_source: &'a dyn TopicOffsetSource,
    commits: tokio::sync::Mutex<Option<Result<SeedGroupCommits, SourceError>>>,
    ends: tokio::sync::Mutex<Option<Result<ObservationEnds, SourceError>>>,
}

impl<'a> TickBrokerSnapshot<'a> {
    fn new(observe: &'a ObserveArm) -> Self {
        Self {
            committed_source: observe.committed.as_ref(),
            ends_source: observe.topic_ends.as_ref(),
            commits: tokio::sync::Mutex::new(None),
            ends: tokio::sync::Mutex::new(None),
        }
    }
}

#[async_trait]
impl CommittedOffsetSource for TickBrokerSnapshot<'_> {
    async fn committed(&self) -> Result<SeedGroupCommits, SourceError> {
        let mut cached = self.commits.lock().await;
        if cached.is_none() {
            *cached = Some(self.committed_source.committed().await);
        }
        cached.as_ref().expect("filled above").clone()
    }
}

#[async_trait]
impl TopicOffsetSource for TickBrokerSnapshot<'_> {
    async fn observation_ends(&self) -> Result<ObservationEnds, SourceError> {
        let mut cached = self.ends.lock().await;
        if cached.is_none() {
            *cached = Some(self.ends_source.observation_ends().await);
        }
        cached.as_ref().expect("filled above").clone()
    }
}

/// Build a watch directive for one reconciling run from its dispatch record and persisted bits, so
/// the watcher resumes the fold rather than restarting it.
fn build_directive(
    completion: &DiscoveredCompletion,
    dispatched: &DispatchedReconcile,
    participations: &[ObservationParticipation],
) -> WatchDirective {
    let seeded: Vec<(_, PartitionBitmap)> = participations
        .iter()
        .filter(|participation| participation.superseded_at.is_none())
        .map(|participation| (participation.cohort_id, participation.bits))
        .collect();
    WatchDirective {
        run_id: completion.run_id,
        team_id: completion.team_id,
        epoch: dispatched.epoch,
        start: dispatched.watch.positions.clone(),
        seeded,
    }
}

/// Track the oldest not-yet-observed reconciling run for the stalled-observation pager gauge.
/// `since` is when the run entered its current phase, never when it was created.
fn track_oldest(oldest: &mut Option<DateTime<Utc>>, since: DateTime<Utc>) {
    match oldest {
        Some(current) if *current <= since => {}
        _ => *oldest = Some(since),
    }
}

/// Releases the run's in-flight entry and gauge slot when its dispatch task ends — including on
/// panic. A leaked entry would dedupe the run away on this replica until restart.
struct InFlightGuard {
    in_flight: Arc<Mutex<HashSet<RunId>>>,
    run_id: RunId,
}

impl InFlightGuard {
    fn enter(in_flight: Arc<Mutex<HashSet<RunId>>>, run_id: RunId) -> Self {
        gauge!(RECONCILE_DISPATCHES_IN_FLIGHT).increment(1.0);
        Self { in_flight, run_id }
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        lock_recoverable(&self.in_flight).remove(&self.run_id);
        gauge!(RECONCILE_DISPATCHES_IN_FLIGHT).decrement(1.0);
    }
}

/// The driver's run sets stay structurally valid across a panic between lock and mutation, so a
/// poisoned lock is recoverable rather than fatal.
fn lock_recoverable<T>(value: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    value
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// One dispatch attempt. Every failure path logs and leaves the run in a state the next tick retries:
/// a lost CAS leaves the run untouched; a run with no participation left to reconcile is marked
/// observed so Django can terminalize it; a post-CAS `Incomplete` reverts to `seeding`; a
/// produce/record failure leaves the run `reconciling` with no record, which the next tick sees as
/// `ReconcilingUndispatched` and re-dispatches. On shutdown mid-dispatch the same recovery converges
/// per the crash-recovery matrix.
async fn run_dispatch(context: &DispatchArm, run_id: RunId, kind: DispatchKind) {
    let claim = match acquire_claim(context, run_id, kind).await {
        Ok(Some(claim)) => claim,
        Ok(None) => {
            counter!(RECONCILE_CAS_LOST).increment(1);
            counter!(RECONCILE_DISPATCHES, "outcome" => "cas_lost").increment(1);
            return;
        }
        Err(error) => {
            warn!(error = %error, run_id = ?run_id, "acquiring the reconciling claim failed");
            return;
        }
    };

    let certified = match prepare_reconcile_dispatch(
        &context.pool,
        run_id,
        CompletionRequirement::Complete,
        context.register_backfill,
    )
    .await
    {
        Ok(PreparedDispatch::Certified(certified)) => certified,
        Ok(PreparedDispatch::Uncertified(_)) => {
            warn!(run_id = ?run_id, "dispatch was not certified under Complete; leaving reconciling");
            counter!(RECONCILE_DISPATCHES, "outcome" => "prepare_failed").increment(1);
            return;
        }
        Err(PrepareReconcileDispatchError::Run(ReconcileRunError::NoActiveParticipations(_))) => {
            // Every participation was superseded while the run seeded. There is nothing to
            // dispatch and no outcome to write, so stamp the observation ourselves — Django's
            // finalizer only discovers runs carrying `reconcile_observed_at`, and without it the
            // run would classify as `ReconcilingUndispatched` and re-spawn this no-op forever.
            warn!(run_id = ?run_id, "no active participations; marking observed for Django to terminalize");
            if let Err(error) = mark_run_observed_unreconcilable(&context.pool, run_id).await {
                warn!(error = %error, run_id = ?run_id, "marking an unreconcilable run observed failed");
            }
            counter!(RECONCILE_DISPATCHES, "outcome" => "no_participations").increment(1);
            return;
        }
        Err(PrepareReconcileDispatchError::Incomplete {
            remaining_chunks, ..
        }) => {
            warn!(
                run_id = ?run_id,
                remaining_chunks,
                "chunks reappeared after the CAS; reverting to seeding"
            );
            if let Err(error) = claim.revert(&context.pool).await {
                warn!(error = %error, run_id = ?run_id, "reverting the reconciling CAS failed");
            }
            counter!(RECONCILE_DISPATCHES, "outcome" => "revert").increment(1);
            return;
        }
        Err(error) => {
            warn!(error = %error, run_id = ?run_id, "preparing reconcile dispatch failed; leaving reconciling");
            counter!(RECONCILE_DISPATCHES, "outcome" => "prepare_failed").increment(1);
            return;
        }
    };

    match dispatch_and_record(
        &context.pool,
        &context.producer,
        &context.membership_topic,
        context.max_inflight,
        KAFKA_METADATA_TIMEOUT,
        certified,
        claim,
    )
    .await
    {
        Ok(_) => {
            counter!(RECONCILE_DISPATCHES, "outcome" => "dispatched").increment(1);
        }
        Err(error) => {
            let outcome = error.outcome();
            warn!(error = %error, run_id = ?run_id, "reconcile dispatch failed; leaving reconciling for re-dispatch");
            counter!(RECONCILE_DISPATCHES, "outcome" => outcome).increment(1);
        }
    }
}

async fn acquire_claim(
    context: &DispatchArm,
    run_id: RunId,
    kind: DispatchKind,
) -> Result<Option<ReconcilingClaim>, CompletionStoreError> {
    match kind {
        DispatchKind::Fresh => cas_run_reconciling(&context.pool, run_id).await,
        DispatchKind::ReDispatch => confirm_reconciling(&context.pool, run_id).await,
    }
}

/// The persisted result of a dispatch: the per-partition produce receipt and the fence epoch.
#[derive(Debug)]
pub struct RecordedDispatch {
    pub receipt: ReconcileDispatchReceipt,
    pub epoch: DispatchEpoch,
}

/// Capture the marker-watch start positions, produce the reconcile control tiles, and atomically
/// record the dispatch. Requires both a [`CertifiedDispatch`] (completion proven) and a
/// [`ReconcilingClaim`] (CAS proven), so persistence is unreachable without both proofs. Positions are
/// captured BEFORE producing, so every marker of this dispatch lands at or above them.
pub async fn dispatch_and_record(
    pool: &PgPool,
    producer: &SeedTileProducer,
    membership_topic: &str,
    max_inflight: NonZeroUsize,
    metadata_timeout: Duration,
    certified: CertifiedDispatch,
    claim: ReconcilingClaim,
) -> Result<RecordedDispatch, DispatchRecordError> {
    let positions = {
        let producer = producer.clone();
        let topic = membership_topic.to_string();
        tokio::task::spawn_blocking(move || {
            producer.capture_topic_offsets(&topic, metadata_timeout)
        })
        .await
        .map_err(DispatchRecordError::CaptureTask)?
        .map_err(DispatchRecordError::CaptureOffsets)?
    };

    let receipt = execute_reconcile_dispatch(
        certified.into_prepared(),
        producer,
        max_inflight,
        metadata_timeout,
    )
    .await
    .map_err(DispatchRecordError::Execute)?;

    let hwms = ReconcileHwms::try_from(&receipt).map_err(DispatchRecordError::Hwms)?;
    let watch = MarkerWatch {
        positions,
        ends: None,
    };
    let epoch = claim
        .record(pool, &hwms, &watch)
        .await
        .map_err(DispatchRecordError::Record)?;

    Ok(RecordedDispatch { receipt, epoch })
}

impl TryFrom<&ReconcileDispatchReceipt> for ReconcileHwms {
    type Error = ReconcileHwmsError;

    fn try_from(receipt: &ReconcileDispatchReceipt) -> Result<Self, Self::Error> {
        let offsets = receipt
            .offsets()
            .map(|(partition, offset)| (partition, ProducedOffset::new(offset)))
            .collect();
        ReconcileHwms::new(offsets)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum DispatchRecordError {
    #[error("joining the offset-capture task")]
    CaptureTask(#[source] JoinError),
    #[error("capturing the membership topic start positions")]
    CaptureOffsets(#[source] CaptureOffsetsError),
    #[error("producing the reconcile control tiles")]
    Execute(#[source] ReconcileDispatchError),
    #[error("building the reconcile produce high-water marks")]
    Hwms(#[source] ReconcileHwmsError),
    #[error("recording the dispatch")]
    Record(#[source] CompletionStoreError),
}

impl DispatchRecordError {
    fn outcome(&self) -> &'static str {
        match self {
            Self::CaptureTask(_) | Self::CaptureOffsets(_) | Self::Execute(_) | Self::Hwms(_) => {
                "produce_failed"
            }
            Self::Record(_) => "record_failed",
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envconfig::Envconfig;

    use super::*;

    fn config_with(overrides: &[(&str, &str)]) -> Config {
        let env: HashMap<String, String> = overrides
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect();
        Config::init_from_hashmap(&env).unwrap()
    }

    #[test]
    fn policy_is_disabled_by_default_and_ignores_a_bare_attestation() {
        assert!(matches!(
            AutoDispatchPolicy::from_config(&config_with(&[])).unwrap(),
            AutoDispatchPolicy::Disabled
        ));
        assert!(matches!(
            AutoDispatchPolicy::from_config(&config_with(&[(
                "SEEDER_CONFIRM_REGISTER_BACKFILLED",
                "true"
            )]))
            .unwrap(),
            AutoDispatchPolicy::Disabled
        ));
    }

    #[test]
    fn enabling_without_attestation_is_a_startup_error() {
        assert_eq!(
            AutoDispatchPolicy::from_config(&config_with(&[(
                "SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED",
                "true"
            )]))
            .unwrap_err(),
            AutoDispatchPolicyError::MissingAttestation
        );
    }

    #[test]
    fn enabling_with_attestation_arms_dispatch() {
        assert!(matches!(
            AutoDispatchPolicy::from_config(&config_with(&[
                ("SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED", "true"),
                ("SEEDER_CONFIRM_REGISTER_BACKFILLED", "true"),
            ]))
            .unwrap(),
            AutoDispatchPolicy::Enabled(_)
        ));
    }

    #[test]
    fn enabling_with_a_noncontract_partition_count_is_a_startup_error() {
        assert_eq!(
            AutoDispatchPolicy::from_config(&config_with(&[
                ("SEEDER_RECONCILE_AUTO_DISPATCH_ENABLED", "true"),
                ("SEEDER_CONFIRM_REGISTER_BACKFILLED", "true"),
                ("COHORT_PARTITION_COUNT", "8"),
            ]))
            .unwrap_err(),
            AutoDispatchPolicyError::PartitionCountMismatch { configured: 8 }
        );
    }

    #[test]
    fn observer_policy_is_a_gate_independent_of_auto_dispatch() {
        assert_eq!(
            ObservePolicy::from_config(&config_with(&[])).unwrap(),
            ObservePolicy::Disabled
        );
        // The observer arms without the dispatch flags: the two gates are independent.
        assert_eq!(
            ObservePolicy::from_config(&config_with(&[(
                "SEEDER_RECONCILE_OBSERVER_ENABLED",
                "true"
            )]))
            .unwrap(),
            ObservePolicy::Enabled
        );
        assert_eq!(
            ObservePolicy::from_config(&config_with(&[
                ("SEEDER_RECONCILE_OBSERVER_ENABLED", "true"),
                ("COHORT_PARTITION_COUNT", "8"),
            ]))
            .unwrap_err(),
            ObservePolicyError::PartitionCountMismatch { configured: 8 }
        );
    }
}
