//! App layer: the automatic reconcile-dispatch driver, dark by default. Ticked from the orchestrator
//! poll arm after `fill_claim_slots`, it discovers seeding/reconciling behavioral runs, transitions a
//! fully-confirmed run `seeding → reconciling`, produces the reconcile control tiles, and persists the
//! dispatch record (produce HWMs + marker-watch start positions + fence epoch) through the same store
//! path the CLI uses. Consumers/observers are PR-C — this producer never reads markers.
//!
//! Dispatch runs in a spawned task, never inline: producing `cohorts × COHORT_PARTITION_COUNT` control
//! tiles and awaiting their delivery acks can exceed the orchestrator's liveness deadline. An
//! in-flight set dedupes tasks on this replica; the CAS plus INV-3's ruling-fence semantics (a later
//! `record` sets the fence, the processor supersedes duplicate tiles) make cross-replica duplicates
//! safe.

use std::collections::HashSet;
use std::num::NonZeroUsize;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use common_types::cohort::TeamAllowlist;
use metrics::{counter, gauge};
use sqlx::PgPool;
use tokio::sync::Semaphore;
use tokio::task::JoinError;
use tracing::warn;

use cohort_core::partitioner::COHORT_PARTITION_COUNT;

use crate::config::Config;
use crate::domain::{
    CompletionPhase, DispatchEpoch, MarkerWatch, ProducedOffset, ReconcileHwms, ReconcileHwmsError,
    RunId,
};
use crate::kafka::producer::{CaptureOffsetsError, SeedTileProducer};
use crate::observability::metrics::{
    RECONCILE_CAS_LOST, RECONCILE_DISPATCHES, RECONCILE_DISPATCHES_IN_FLIGHT,
    RECONCILE_RECORD_INVALID, RUNS_RECONCILING,
};
use crate::store::completion::{
    cas_run_reconciling, confirm_reconciling, discover_completions,
    mark_run_observed_unreconcilable, runs_with_all_chunks_confirmed, CompletionStoreError,
    ReconcilingClaim,
};
use crate::store::runs::ReconcileRunError;

use super::reconcile_dispatch::{
    execute_reconcile_dispatch, prepare_reconcile_dispatch, CertifiedDispatch,
    CompletionRequirement, PrepareReconcileDispatchError, PreparedDispatch, ReconcileDispatchError,
    ReconcileDispatchReceipt, RegisterBackfillConfirmation,
};

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

/// Whether a spawned task starts a fresh dispatch (CAS out of `seeding`) or re-dispatches an
/// already-`reconciling` run (confirm claim) to heal a missing or stale dispatch record.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DispatchKind {
    Fresh,
    ReDispatch,
}

/// The owned dependencies a dispatch task needs, cheap to clone into a spawned task.
#[derive(Clone)]
struct DispatchContext {
    pool: PgPool,
    producer: SeedTileProducer,
    membership_topic: Arc<str>,
    max_inflight: NonZeroUsize,
    register_backfill: RegisterBackfillConfirmation,
}

pub struct CompletionDriver {
    context: DispatchContext,
    allowlist: TeamAllowlist,
    in_flight: Arc<Mutex<HashSet<RunId>>>,
    dispatch_slots: Arc<Semaphore>,
}

impl CompletionDriver {
    pub fn new(
        pool: PgPool,
        producer: SeedTileProducer,
        allowlist: TeamAllowlist,
        membership_topic: String,
        max_inflight: NonZeroUsize,
        max_concurrent_dispatches: NonZeroUsize,
        register_backfill: RegisterBackfillConfirmation,
    ) -> Self {
        Self {
            context: DispatchContext {
                pool,
                producer,
                membership_topic: Arc::from(membership_topic),
                max_inflight,
                register_backfill,
            },
            allowlist,
            in_flight: Arc::new(Mutex::new(HashSet::new())),
            dispatch_slots: Arc::new(Semaphore::new(max_concurrent_dispatches.get())),
        }
    }

    /// One driver pass: classify every discovered run and spawn dispatch tasks for the ones that need
    /// one. A discovery failure is logged and retried next tick; the dark path (driver absent) costs
    /// zero queries. Every read is per-tick, never per-run — the pass blocks the orchestrator's
    /// liveness heartbeat.
    pub async fn tick(&self) {
        let discovered = match discover_completions(&self.context.pool, &self.allowlist).await {
            Ok(discovered) => discovered,
            Err(error) => {
                warn!(error = %error, "completion discovery failed");
                return;
            }
        };

        let mut reconciling = 0_u64;
        let mut planned = Vec::new();
        for completion in discovered {
            match completion.phase {
                CompletionPhase::Observed | CompletionPhase::Reconciling(_) => {
                    reconciling += 1;
                }
                CompletionPhase::ReconcilingUndispatched(reason) => {
                    reconciling += 1;
                    // Count and warn only when a re-dispatch actually starts: the run keeps this
                    // phase until the in-flight task records one, so counting per tick would turn a
                    // single healing event into an unbounded rate.
                    if self.spawn_dispatch(completion.run_id, DispatchKind::ReDispatch) {
                        counter!(RECONCILE_RECORD_INVALID).increment(1);
                        warn!(
                            run_id = ?completion.run_id,
                            ?reason,
                            "reconciling run has no usable dispatch record; re-dispatching"
                        );
                    }
                }
                CompletionPhase::SeedingPlanned => planned.push(completion.run_id),
                CompletionPhase::SeedingUnplanned => {}
                CompletionPhase::SeedingAnomalous => {
                    warn!(
                        run_id = ?completion.run_id,
                        "seeding run carries reconcile columns; skipping until it is reconciled by hand"
                    );
                }
            }
        }
        gauge!(RUNS_RECONCILING).set(reconciling as f64);

        match runs_with_all_chunks_confirmed(&self.context.pool, &planned).await {
            Ok(confirmed) => {
                for run_id in confirmed {
                    let _spawned = self.spawn_dispatch(run_id, DispatchKind::Fresh);
                }
            }
            Err(error) => {
                warn!(error = %error, "reading chunk progress for dispatch failed");
            }
        }
    }

    /// Spawns a dispatch task unless one is already in flight for this run on this replica or the
    /// driver is at its concurrency budget. Returns whether a task actually started, so callers can
    /// attribute per-event signals to the event rather than to every poll tick that observes the
    /// same pending state.
    ///
    /// Every task produces `cohorts × COHORT_PARTITION_COUNT` tiles through the producer the chunk
    /// pipeline shares, so unbounded fan-out would back the core seeding path off its own queue. A
    /// run that misses the budget keeps its phase and is picked up on a later tick.
    fn spawn_dispatch(&self, run_id: RunId, kind: DispatchKind) -> bool {
        let Ok(permit) = Arc::clone(&self.dispatch_slots).try_acquire_owned() else {
            return false;
        };
        if !lock_in_flight(&self.in_flight).insert(run_id) {
            return false;
        }
        let context = self.context.clone();
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
        true
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
        lock_in_flight(&self.in_flight).remove(&self.run_id);
        gauge!(RECONCILE_DISPATCHES_IN_FLIGHT).decrement(1.0);
    }
}

/// The set stays structurally valid across a panic between lock and mutation, so a poisoned lock is
/// recoverable rather than fatal.
fn lock_in_flight(in_flight: &Mutex<HashSet<RunId>>) -> std::sync::MutexGuard<'_, HashSet<RunId>> {
    in_flight
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// One dispatch attempt. Every failure path logs and leaves the run in a state the next tick retries:
/// a lost CAS leaves the run untouched; a run with no participation left to reconcile is marked
/// observed so Django can terminalize it; a post-CAS `Incomplete` reverts to `seeding`; a
/// produce/record failure leaves the run `reconciling` with no record, which the next tick sees as
/// `ReconcilingUndispatched` and re-dispatches. On shutdown mid-dispatch the same recovery converges
/// per the crash-recovery matrix.
async fn run_dispatch(context: &DispatchContext, run_id: RunId, kind: DispatchKind) {
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
    context: &DispatchContext,
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
}
