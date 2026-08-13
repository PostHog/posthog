//! App layer: run discovery → boundary → validate → plan, per run. Depends on `store`, `domain`, and
//! `config`'s allowlist type; never imported by a lower layer.
//!
//! [`refresh_runs`] is the thin fold over discovered runs; [`prepare_run`] dispatches each on its
//! kind — behavioral runs plan inline (cheap day arithmetic), person runs surface a
//! [`PersonPlanRequest`] for the orchestrator's spawned planning slot, since their planning needs a
//! ClickHouse scan that must not run inside the poll loop's liveness deadline. Every behavioral
//! counter and gauge stays at its former point.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use cohort_core::bucket_tz::window_start_for_now;
use cohort_core::filters::CohortId;
use common_types::cohort::TeamAllowlist;
use metrics::{counter, gauge};
use sqlx::PgPool;
use tracing::warn;

use crate::domain::{
    plan_days, Lookback, PersonRunValidation, PinnedPersonRun, PinnedRun, PinnedWarning, PlanCaps,
    RunId,
};
use crate::observability::metrics::{
    BOUNDARY_CAS_LOST, BOUNDARY_ESTABLISHED, CHUNKS_PLANNED, CONDITIONS_DROPPED,
    LOOKBACK_TRUNCATED, RUNS_DISCOVERED, RUNS_PLANNING_STAMPED, RUNS_PLANNING_WITHHELD,
    RUNS_WAITING_BOUNDARY, RUNS_WITHOUT_CHUNKS, RUN_CHUNKS_REMAINING, RUN_VALIDATION_FAILURES,
    TZ_FALLBACK, WINDOW_DAYS_MISMATCH,
};
use crate::store::chunks::{PgChunkStore, PlanOutcome};
use crate::store::completion::{mark_chunks_planned, read_planning_stamp, PlanningStampOutcome};
use crate::store::runs::{
    discover_runs, establish_boundary, fail_run, record_run_warning, BoundaryOutcome,
    DiscoveredRun, RunError, RunKind, RunStatus, RunWarningNote, SeedableRun,
};
use crate::store::RenderedError;

use super::person_plan::PersonPlanRequest;

/// A run validated to the point of claim eligibility, by kind.
pub(super) enum PreparedRun {
    Behavioral(Arc<PinnedRun>),
    Person(Arc<PinnedPersonRun>),
}

/// One refresh pass's result: the claim-eligible runs plus the person runs still needing their
/// planning scan.
pub(super) struct RefreshOutcome {
    pub(super) eligible: HashMap<RunId, PreparedRun>,
    pub(super) planning: Vec<PersonPlanRequest>,
}

/// One discovered run's classification after its boundary/validate/plan pipeline.
enum PrepareOutcome {
    Eligible(PreparedRun),
    WaitingBoundary,
    NoChunks,
    Skipped,
    PlanningNeeded(PersonPlanRequest),
}

pub(super) async fn refresh_runs(
    pool: &PgPool,
    store: &PgChunkStore,
    allowlist: &TeamAllowlist,
    kinds: &[RunKind],
    plan_caps: PlanCaps,
    reported_runs: &mut HashSet<RunId>,
) -> RefreshOutcome {
    let discovered = match discover_runs(pool, allowlist, kinds).await {
        Ok(runs) => runs,
        Err(error) => {
            let run_id = error.run_id();
            handle_run_error(pool, run_id, error).await;
            return RefreshOutcome {
                eligible: HashMap::new(),
                planning: Vec::new(),
            };
        }
    };
    let mut eligible = HashMap::with_capacity(discovered.len());
    let mut planning = Vec::new();
    let mut seen_runs = HashSet::with_capacity(discovered.len());
    let mut waiting_boundary = 0_u64;
    let mut without_chunks: HashMap<RunKind, u64> = HashMap::new();

    for run in discovered {
        seen_runs.insert(run.run_id);
        let kind = run.kind;
        match prepare_run(pool, store, plan_caps, reported_runs, run).await {
            PrepareOutcome::Eligible(prepared) => {
                let run_id = match &prepared {
                    PreparedRun::Behavioral(run) => run.run_id,
                    PreparedRun::Person(run) => run.run_id,
                };
                eligible.insert(run_id, prepared);
            }
            PrepareOutcome::WaitingBoundary => waiting_boundary += 1,
            PrepareOutcome::NoChunks => *without_chunks.entry(kind).or_default() += 1,
            PrepareOutcome::Skipped => {}
            PrepareOutcome::PlanningNeeded(request) => {
                *without_chunks.entry(kind).or_default() += 1;
                planning.push(request);
            }
        }
    }

    gauge!(RUNS_WAITING_BOUNDARY).set(waiting_boundary as f64);
    for kind in [RunKind::Behavioral, RunKind::PersonProperty] {
        let count = without_chunks.get(&kind).copied().unwrap_or(0);
        gauge!(RUNS_WITHOUT_CHUNKS, "kind" => kind.as_str()).set(count as f64);
        // Split by kind too: a person run's chunk count tracks its team's person volume, on a
        // scale unrelated to behavioral day-bands, so one series would bury the other's burn-down.
        match store
            .remaining_chunks(&run_ids_of_kind(&eligible, kind))
            .await
        {
            Ok(remaining) => {
                gauge!(RUN_CHUNKS_REMAINING, "kind" => kind.as_str()).set(remaining as f64);
            }
            Err(error) => {
                warn!(error = %error, kind = kind.as_str(), "counting remaining chunks failed");
            }
        }
    }
    reported_runs.retain(|run_id| seen_runs.contains(run_id));
    RefreshOutcome { eligible, planning }
}

async fn prepare_run(
    pool: &PgPool,
    store: &PgChunkStore,
    plan_caps: PlanCaps,
    reported_runs: &mut HashSet<RunId>,
    run: DiscoveredRun,
) -> PrepareOutcome {
    counter!(RUNS_DISCOVERED, "status" => run.status.as_str(), "kind" => run.kind.as_str())
        .increment(1);

    let kind = run.kind;
    let Some(boundary) = resolve_boundary(pool, run).await else {
        return PrepareOutcome::Skipped;
    };
    let Resolved::Seedable(boundary) = boundary else {
        return PrepareOutcome::WaitingBoundary;
    };
    match kind {
        RunKind::Behavioral => {
            prepare_behavioral(pool, store, plan_caps, reported_runs, boundary).await
        }
        RunKind::PersonProperty => prepare_person(pool, store, reported_runs, boundary).await,
    }
}

enum Resolved {
    Seedable(SeedableRun),
    WaitingBoundary,
}

/// Establish (or re-read) the run's boundary; `None` means the run was skipped.
async fn resolve_boundary(pool: &PgPool, run: DiscoveredRun) -> Option<Resolved> {
    let was_awaiting_boundary = run.status == RunStatus::AwaitingBoundary;
    let discovered_run_id = run.run_id;
    match establish_boundary(pool, run).await {
        Ok(BoundaryOutcome::Established(run)) => {
            counter!(BOUNDARY_ESTABLISHED, "trigger" => run.trigger.as_str()).increment(1);
            Some(Resolved::Seedable(run))
        }
        Ok(BoundaryOutcome::AlreadyEstablished(run)) => {
            if was_awaiting_boundary {
                counter!(BOUNDARY_CAS_LOST).increment(1);
            }
            Some(Resolved::Seedable(run))
        }
        Ok(BoundaryOutcome::NoLongerSeedable { .. }) => None,
        Err(RunError::DisasterRecoveryBoundaryMissing(_)) => Some(Resolved::WaitingBoundary),
        Err(error) => {
            handle_run_error(pool, Some(discovered_run_id), error).await;
            None
        }
    }
}

async fn prepare_behavioral(
    pool: &PgPool,
    store: &PgChunkStore,
    plan_caps: PlanCaps,
    reported_runs: &mut HashSet<RunId>,
    boundary: SeedableRun,
) -> PrepareOutcome {
    let run_id = boundary.run_id;
    let validated = match boundary.load_pinned(pool).await {
        Ok(validated) => validated,
        Err(error) => {
            handle_run_error(pool, Some(run_id), error).await;
            return PrepareOutcome::Skipped;
        }
    };
    let lookback_truncated = lookback_was_truncated(&validated.run, plan_caps);
    if reported_runs.insert(run_id) {
        record_pinned_warnings(&validated.warnings);
        if lookback_truncated {
            counter!(LOOKBACK_TRUNCATED).increment(1);
        }
    }
    if validated
        .warnings
        .iter()
        .any(|warning| matches!(warning, PinnedWarning::ConditionDropped { .. }))
    {
        persist_run_warning(pool, run_id, RunWarningNote::ConditionsDropped).await;
    }
    if lookback_truncated {
        persist_run_warning(pool, run_id, RunWarningNote::LookbackTruncated).await;
    }

    // Without the proof the run never dispatches, so an uncovered cohort can never stamp readiness
    // on zero seeded history. Siblings still get planned and seeded.
    let coverage_complete =
        record_coverage(run_id, RunKind::Behavioral, &validated.uncovered_cohorts);

    let days = plan_days(
        &validated.run.conditions,
        validated.run.boundary,
        &plan_caps,
    );
    if days.is_empty() {
        if coverage_complete {
            // A legitimately zero-chunk run still needs the proof, or it stalls waiting for chunks
            // that will never exist.
            stamp_planning(pool, run_id, RunKind::Behavioral).await;
        }
        return PrepareOutcome::NoChunks;
    }
    match store
        .plan_chunks(validated.run.run_id, days, plan_caps.bands_per_day)
        .await
    {
        Ok(PlanOutcome::Planned { inserted }) => {
            counter!(CHUNKS_PLANNED, "kind" => RunKind::Behavioral.as_str()).increment(inserted);
            if coverage_complete {
                stamp_planning(pool, run_id, RunKind::Behavioral).await;
            }
        }
        Ok(PlanOutcome::RunNotSeeding) => return PrepareOutcome::Skipped,
        Ok(PlanOutcome::AlreadyPlanned) => {
            // Behavioral planning never takes the all-or-nothing gate; reaching this means the
            // store contract changed underneath this caller.
            warn!(
                ?run_id,
                "behavioral planning unexpectedly reported AlreadyPlanned"
            );
            return PrepareOutcome::Skipped;
        }
        Err(error) => {
            warn!(run_id = ?validated.run.run_id, error = %error, "chunk planning failed");
            return PrepareOutcome::Skipped;
        }
    }
    PrepareOutcome::Eligible(PreparedRun::Behavioral(Arc::new(validated.run)))
}

/// The person pipeline: validate the pinned payload (zero surviving hashes with an active
/// participation fails the run inside `handle_run_error`; all-superseded retires as zero-work),
/// then classify by planning state — the stamp or existing chunks make the run claim-eligible;
/// otherwise it needs its planning scan.
async fn prepare_person(
    pool: &PgPool,
    store: &PgChunkStore,
    reported_runs: &mut HashSet<RunId>,
    boundary: SeedableRun,
) -> PrepareOutcome {
    let run_id = boundary.run_id;
    let validated = match boundary.load_person_pinned(pool).await {
        Ok(PersonRunValidation::Seedable(validated)) => validated,
        Ok(PersonRunValidation::Retired { warnings }) => {
            if reported_runs.insert(run_id) {
                record_pinned_warnings(&warnings);
            }
            // Nothing expects coverage, so the zero-chunk proof lets the run finish as zero-work
            // downstream — the behavioral zero-condition retirement, kind-adjusted.
            stamp_planning(pool, run_id, RunKind::PersonProperty).await;
            return PrepareOutcome::NoChunks;
        }
        Err(error) => {
            handle_run_error(pool, Some(run_id), error).await;
            return PrepareOutcome::Skipped;
        }
    };
    if reported_runs.insert(run_id) {
        record_pinned_warnings(&validated.warnings);
    }
    if validated
        .warnings
        .iter()
        .any(|warning| matches!(warning, PinnedWarning::ConditionDropped { .. }))
    {
        persist_run_warning(pool, run_id, RunWarningNote::ConditionsDropped).await;
    }
    let coverage_complete = record_coverage(
        run_id,
        RunKind::PersonProperty,
        &validated.uncovered_cohorts,
    );

    let stamped = match read_planning_stamp(pool, run_id, RunKind::PersonProperty).await {
        Ok(stamp) => stamp.is_some(),
        Err(error) => {
            warn!(?run_id, error = %error, "reading the person planning stamp failed");
            return PrepareOutcome::Skipped;
        }
    };
    let run = Arc::new(validated.run);
    if stamped {
        return PrepareOutcome::Eligible(PreparedRun::Person(run));
    }
    match store.chunk_progress(run_id).await {
        Ok(progress) if progress.total() > 0 => {
            // Planned but not yet stamped — the planner left the stamp to this pass (its coverage
            // snapshot could predate a supersession). Coverage here is fresh from the database.
            if coverage_complete {
                stamp_planning(pool, run_id, RunKind::PersonProperty).await;
            }
            PrepareOutcome::Eligible(PreparedRun::Person(run))
        }
        Ok(_) => PrepareOutcome::PlanningNeeded(PersonPlanRequest {
            run,
            coverage_complete,
        }),
        Err(error) => {
            warn!(?run_id, error = %error, "reading person chunk progress failed");
            PrepareOutcome::Skipped
        }
    }
}

/// The eligible run ids of one kind — the per-kind label on every shared chunk metric resolves
/// through here, so the mapping lives in one place.
pub(super) fn run_ids_of_kind(
    eligible_runs: &HashMap<RunId, PreparedRun>,
    kind: RunKind,
) -> Vec<RunId> {
    eligible_runs
        .iter()
        .filter(|(_, prepared)| {
            matches!(
                (prepared, kind),
                (PreparedRun::Behavioral(_), RunKind::Behavioral)
                    | (PreparedRun::Person(_), RunKind::PersonProperty)
            )
        })
        .map(|(run_id, _)| *run_id)
        .collect()
}

fn record_coverage(run_id: RunId, kind: RunKind, uncovered_cohorts: &[CohortId]) -> bool {
    let coverage_complete = uncovered_cohorts.is_empty();
    if !coverage_complete {
        counter!(RUNS_PLANNING_WITHHELD, "kind" => kind.as_str()).increment(1);
        warn!(
            run_id = ?run_id,
            uncovered_cohorts = ?uncovered_cohorts,
            "active participations have no surviving pinned condition; withholding the planning proof"
        );
    }
    coverage_complete
}

/// Stamp the planning proof once planning has run. A failure is logged but never changes the prepare
/// outcome — the run keeps seeding and the next pass re-stamps.
async fn stamp_planning(pool: &PgPool, run_id: RunId, kind: RunKind) {
    match mark_chunks_planned(pool, run_id, kind).await {
        Ok(PlanningStampOutcome::Stamped) => {
            counter!(RUNS_PLANNING_STAMPED, "kind" => kind.as_str()).increment(1);
        }
        Ok(PlanningStampOutcome::Skipped) => {}
        Err(error) => warn!(run_id = ?run_id, error = %error, "stamping the planning proof failed"),
    }
}

async fn handle_run_error(pool: &PgPool, run_id: Option<RunId>, error: RunError) {
    let disposition = run_error_disposition(run_id, &error);
    if let RunErrorDisposition::Fail { run_id, reason } = disposition {
        counter!(RUN_VALIDATION_FAILURES, "reason" => reason).increment(1);
        let detail = RenderedError::render(&error);
        if let Err(failure) = fail_run(pool, run_id, &detail).await {
            warn!(run_id = ?run_id, error = %failure, "failing invalid run did not apply");
        }
        return;
    }
    warn!(error = %error, "transient run preparation failed");
}

async fn persist_run_warning(pool: &PgPool, run_id: RunId, note: RunWarningNote) {
    if let Err(error) = record_run_warning(pool, run_id, note).await {
        warn!(run_id = ?run_id, error = %error, "persisting run warning failed");
    }
}

fn record_pinned_warnings(warnings: &[PinnedWarning]) {
    for warning in warnings {
        match warning {
            PinnedWarning::TimezoneFallback { .. } => counter!(TZ_FALLBACK).increment(1),
            PinnedWarning::ConditionDropped { reason, .. } => {
                counter!(CONDITIONS_DROPPED, "reason" => reason.as_str()).increment(1);
            }
            PinnedWarning::ConditionSuperseded { .. } => {
                counter!(CONDITIONS_DROPPED, "reason" => "superseded_participation").increment(1);
            }
            PinnedWarning::WindowDaysMismatch { .. } => {
                counter!(WINDOW_DAYS_MISMATCH).increment(1);
            }
        }
    }
}

fn lookback_was_truncated(run: &PinnedRun, caps: PlanCaps) -> bool {
    let capped_start = window_start_for_now(run.boundary.day(), caps.max_lookback_days);
    run.conditions
        .iter()
        .any(|condition| match condition.lookback {
            Lookback::SlidingDays(days) => days > caps.max_lookback_days,
            Lookback::FixedRange { from_day: None, .. } => true,
            Lookback::FixedRange {
                from_day: Some(from),
                ..
            } => from < capped_start,
            Lookback::SubDay => false,
        })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RunErrorDisposition {
    Retry,
    Fail { run_id: RunId, reason: &'static str },
}

fn run_error_disposition(run_id: Option<RunId>, error: &RunError) -> RunErrorDisposition {
    match error {
        RunError::Pg(_) => RunErrorDisposition::Retry,
        RunError::Pinned(_) => run_id.map_or(RunErrorDisposition::Retry, |run_id| {
            RunErrorDisposition::Fail {
                run_id,
                reason: "pinned_validation",
            }
        }),
        RunError::CrossTeamParticipation { run_id, .. } => RunErrorDisposition::Fail {
            run_id: *run_id,
            reason: "cross_team_participation",
        },
        RunError::SeedingBoundaryMissing(run_id) => RunErrorDisposition::Fail {
            run_id: *run_id,
            reason: "missing_boundary",
        },
        RunError::DisasterRecoveryBoundaryMissing(_) => RunErrorDisposition::Retry,
        RunError::InvalidKind { run_id, .. }
        | RunError::InvalidTrigger { run_id, .. }
        | RunError::InvalidScope { run_id, .. }
        | RunError::InvalidStatus { run_id, .. } => RunErrorDisposition::Fail {
            run_id: *run_id,
            reason: "invalid_run_row",
        },
        RunError::UnknownStatus(_)
        | RunError::UnknownScope(_)
        | RunError::NotFound(_)
        | RunError::NotActive(_) => RunErrorDisposition::Retry,
    }
}
