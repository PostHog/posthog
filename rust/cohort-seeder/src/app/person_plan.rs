//! App layer: the one-shot person planning scan, spawned off the orchestrator's poll loop so the
//! ClickHouse boundary stream never runs inside the liveness deadline. Depends on `clickhouse`,
//! `store`, `domain`, and its `app` siblings.
//!
//! Planning is claimed cluster-wide (a per-run advisory lock) before ClickHouse is touched, so R
//! replicas never run R copies of the full-table boundary aggregation; a failed attempt reports
//! [`PersonPlanAttempt::Failed`] so the orchestrator backs the run off instead of re-issuing the
//! scan on the next poll tick.

use std::num::NonZeroU64;

use metrics::counter;
use sqlx::PgPool;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::clickhouse::person_scanner::{PersonScanError, PersonScanner};
use crate::domain::{tile_ranges, PinnedPersonRun, RunId};
use crate::observability::metrics::{
    MetricTimer, CHUNKS_PLANNED, PERSON_BOUNDARIES_PLANNED, PERSON_PLANNING_DURATION_SECONDS,
    RUNS_PLANNING_STAMPED,
};
use crate::store::chunks::{PgChunkStore, PlanOutcome};
use crate::store::completion::{mark_chunks_planned, PlanningStampOutcome};
use crate::store::runs::{fail_run, RunKind};
use crate::store::RenderedError;

use std::sync::Arc;

/// A person run whose chunks do not exist yet, handed from `prepare` to the orchestrator's
/// planning slot. Coverage travels along so the planner can withhold the stamp.
pub(super) struct PersonPlanRequest {
    pub(super) run: Arc<PinnedPersonRun>,
    pub(super) coverage_complete: bool,
}

/// How one planning attempt ended, for the orchestrator's backoff bookkeeping. Only `Failed`
/// triggers a backoff — a lost claim, a shutdown, or a completed plan needs no cool-down.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PersonPlanAttempt {
    Done,
    Failed,
}

/// Plan one person run: claim → boundary scan → range tiling → all-or-nothing insert → planning
/// stamp. Failures are logged and left for a backed-off retry, except a deterministic tiling
/// overflow, which fails the run. Returns the run id so the orchestrator can release its
/// planning-in-flight slot.
pub(super) async fn plan_person_run(
    pool: PgPool,
    store: PgChunkStore,
    scanner: PersonScanner,
    persons_per_chunk: NonZeroU64,
    request: PersonPlanRequest,
    shutdown: CancellationToken,
) -> (RunId, PersonPlanAttempt) {
    let run_id = request.run.run_id;
    let claim = match store.try_claim_person_planning(run_id).await {
        Ok(Some(claim)) => claim,
        // Another replica is planning this run; its outcome surfaces on a later poll.
        Ok(None) => return (run_id, PersonPlanAttempt::Done),
        Err(error) => {
            warn!(?run_id, error = %error, "claiming the person planning slot failed");
            return (run_id, PersonPlanAttempt::Failed);
        }
    };
    let attempt = plan_claimed_run(
        &pool,
        &store,
        &scanner,
        persons_per_chunk,
        request,
        &shutdown,
    )
    .await;
    claim.release().await;
    (run_id, attempt)
}

async fn plan_claimed_run(
    pool: &PgPool,
    store: &PgChunkStore,
    scanner: &PersonScanner,
    persons_per_chunk: NonZeroU64,
    request: PersonPlanRequest,
    shutdown: &CancellationToken,
) -> PersonPlanAttempt {
    let run = request.run;
    let run_id = run.run_id;
    // Failed attempts are exactly the durations worth watching, so the timer records every exit.
    let timer = MetricTimer::start(PERSON_PLANNING_DURATION_SECONDS);

    let boundaries = match scanner
        .boundaries(run.team_id, run.scan_since, persons_per_chunk, shutdown)
        .await
    {
        Ok(boundaries) => boundaries,
        Err(PersonScanError::Cancelled) => return PersonPlanAttempt::Done,
        Err(error) => {
            warn!(?run_id, error = %error, "person boundary scan failed");
            return PersonPlanAttempt::Failed;
        }
    };
    counter!(PERSON_BOUNDARIES_PLANNED).increment(boundaries.len() as u64);
    let ranges = match tile_ranges(&boundaries) {
        Ok(ranges) => ranges,
        Err(error) => {
            // Unreachable while the boundary keeper saturates at the ceiling; deterministic, so
            // retrying would tile the same overflow forever.
            if let Err(failure) = fail_run(pool, run_id, &RenderedError::render(&error)).await {
                warn!(?run_id, error = %failure, "failing over-tiled person run did not apply");
            }
            return PersonPlanAttempt::Done;
        }
    };
    match store.plan_person_chunks(run_id, &ranges).await {
        Ok(PlanOutcome::Planned { inserted }) => {
            counter!(CHUNKS_PLANNED, "kind" => RunKind::PersonProperty.as_str())
                .increment(inserted);
            info!(
                ?run_id,
                chunks = inserted,
                horizon_days = run.horizon_days,
                elapsed_secs = timer.elapsed().as_secs_f64(),
                "person chunks planned"
            );
        }
        // Chunks already exist (a prior attempt landed them): leave the stamp to the next prepare
        // tick, which re-derives coverage from the database instead of this attempt's snapshot.
        Ok(PlanOutcome::AlreadyPlanned) => return PersonPlanAttempt::Done,
        Ok(PlanOutcome::RunNotSeeding) => return PersonPlanAttempt::Done,
        Err(error) => {
            warn!(?run_id, error = %error, "person chunk planning failed");
            return PersonPlanAttempt::Failed;
        }
    }

    // Without the proof an uncovered cohort could stamp readiness on zero seeded persons.
    if request.coverage_complete {
        match mark_chunks_planned(pool, run_id, RunKind::PersonProperty).await {
            Ok(PlanningStampOutcome::Stamped) => {
                counter!(RUNS_PLANNING_STAMPED, "kind" => RunKind::PersonProperty.as_str())
                    .increment(1);
            }
            Ok(PlanningStampOutcome::Skipped) => {}
            Err(error) => {
                warn!(?run_id, error = %error, "stamping the person planning proof failed");
            }
        }
    }
    PersonPlanAttempt::Done
}
