//! App layer: the one-shot person planning scan, spawned off the orchestrator's poll loop so the
//! ClickHouse boundary stream never runs inside the liveness deadline. Depends on `clickhouse`,
//! `store`, `domain`, and its `app` siblings.

use std::num::NonZeroU64;
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use sqlx::PgPool;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::clickhouse::person_scanner::{PersonScanError, PersonScanner};
use crate::domain::{tile_ranges, PinnedPersonRun, RunId, RunKind};
use crate::observability::metrics::{
    CHUNKS_PLANNED, PERSON_BOUNDARIES_PLANNED, PERSON_PLANNING_DURATION_SECONDS,
    RUNS_PLANNING_STAMPED,
};
use crate::store::chunks::{PgChunkStore, PlanOutcome};
use crate::store::completion::{mark_chunks_planned, PlanningStampOutcome};
use crate::store::runs::fail_run;
use crate::store::RenderedError;

/// A person run whose chunks do not exist yet, handed from `prepare` to the orchestrator's
/// planning slot. Coverage travels along so the planner can withhold the stamp.
pub(super) struct PersonPlanRequest {
    pub(super) run: Arc<PinnedPersonRun>,
    pub(super) coverage_complete: bool,
}

/// Plan one person run: boundary scan → range tiling → all-or-nothing insert → planning stamp.
/// Every failure is logged and left for the next poll to retry, except a deterministic tiling
/// overflow, which fails the run. Returns the run id so the orchestrator can release its
/// planning-in-flight slot.
pub(super) async fn plan_person_run(
    pool: PgPool,
    store: PgChunkStore,
    scanner: PersonScanner,
    persons_per_chunk: NonZeroU64,
    request: PersonPlanRequest,
    shutdown: CancellationToken,
) -> RunId {
    let run = request.run;
    let run_id = run.run_id;
    let started_at = Instant::now();

    let boundaries = match scanner
        .boundaries(run.team_id, run.scan_since, persons_per_chunk, &shutdown)
        .await
    {
        Ok(boundaries) => boundaries,
        Err(PersonScanError::Cancelled) => return run_id,
        Err(error) => {
            warn!(?run_id, error = %error, "person boundary scan failed");
            return run_id;
        }
    };
    counter!(PERSON_BOUNDARIES_PLANNED).increment(boundaries.len() as u64);
    let ranges = match tile_ranges(&boundaries) {
        Ok(ranges) => ranges,
        Err(error) => {
            // Deterministic: retrying would tile the same overflow forever.
            if let Err(failure) = fail_run(&pool, run_id, &RenderedError::render(&error)).await {
                warn!(?run_id, error = %failure, "failing over-tiled person run did not apply");
            }
            return run_id;
        }
    };
    match store.plan_person_chunks(run_id, &ranges).await {
        Ok(PlanOutcome::Planned { inserted }) => {
            counter!(CHUNKS_PLANNED).increment(inserted);
            info!(
                ?run_id,
                chunks = inserted,
                horizon_days = run.horizon_days,
                elapsed_secs = started_at.elapsed().as_secs_f64(),
                "person chunks planned"
            );
        }
        Ok(PlanOutcome::AlreadyPlanned) => {}
        Ok(PlanOutcome::RunNotSeeding) => return run_id,
        Err(error) => {
            warn!(?run_id, error = %error, "person chunk planning failed");
            return run_id;
        }
    }
    histogram!(PERSON_PLANNING_DURATION_SECONDS).record(started_at.elapsed().as_secs_f64());

    // Without the proof an uncovered cohort could stamp readiness on zero seeded persons.
    if request.coverage_complete {
        match mark_chunks_planned(&pool, run_id, RunKind::PersonProperty).await {
            Ok(PlanningStampOutcome::Stamped) => counter!(RUNS_PLANNING_STAMPED).increment(1),
            Ok(PlanningStampOutcome::Skipped) => {}
            Err(error) => {
                warn!(?run_id, error = %error, "stamping the person planning proof failed");
            }
        }
    }
    run_id
}
