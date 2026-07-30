//! App layer: run discovery → boundary → validate → plan, per run. Depends on `store`, `domain`, and
//! `config`'s allowlist type; never imported by a lower layer.
//!
//! [`refresh_runs`] is the thin fold over discovered runs; [`prepare_run`] is the per-run pipeline
//! that classifies each into a [`PrepareOutcome`]. Every counter and gauge stays at its former point.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use cohort_core::bucket_tz::window_start_for_now;
use common_types::cohort::TeamAllowlist;
use metrics::{counter, gauge};
use sqlx::PgPool;
use tracing::warn;

use crate::domain::{plan_days, Lookback, PinnedRun, PinnedWarning, PlanCaps, RunId};
use crate::observability::metrics::{
    BOUNDARY_CAS_LOST, BOUNDARY_ESTABLISHED, CHUNKS_PLANNED, CONDITIONS_DROPPED,
    LOOKBACK_TRUNCATED, RUNS_DISCOVERED, RUNS_WAITING_BOUNDARY, RUNS_WITHOUT_CHUNKS,
    RUN_CHUNKS_REMAINING, RUN_VALIDATION_FAILURES, TZ_FALLBACK, WINDOW_DAYS_MISMATCH,
};
use crate::store::chunks::{PgChunkStore, PlanOutcome};
use crate::store::runs::{
    discover_runs, establish_boundary, fail_run, record_run_warning, BoundaryOutcome,
    DiscoveredRun, RunError, RunStatus, RunWarningNote,
};
use crate::store::RenderedError;

/// One discovered run's classification after its boundary/validate/plan pipeline.
enum PrepareOutcome {
    Eligible(Arc<PinnedRun>),
    WaitingBoundary,
    NoChunks,
    Skipped,
}

pub(super) async fn refresh_runs(
    pool: &PgPool,
    store: &PgChunkStore,
    allowlist: &TeamAllowlist,
    plan_caps: PlanCaps,
    reported_runs: &mut HashSet<RunId>,
) -> HashMap<RunId, Arc<PinnedRun>> {
    let discovered = match discover_runs(pool, allowlist).await {
        Ok(runs) => runs,
        Err(error) => {
            let run_id = error.run_id();
            handle_run_error(pool, run_id, error).await;
            return HashMap::new();
        }
    };
    let mut eligible = HashMap::with_capacity(discovered.len());
    let mut seen_runs = HashSet::with_capacity(discovered.len());
    let mut waiting_boundary = 0_u64;
    let mut without_chunks = 0_u64;

    for run in discovered {
        seen_runs.insert(run.run_id);
        match prepare_run(pool, store, plan_caps, reported_runs, run).await {
            PrepareOutcome::Eligible(pinned) => {
                eligible.insert(pinned.run_id, pinned);
            }
            PrepareOutcome::WaitingBoundary => waiting_boundary += 1,
            PrepareOutcome::NoChunks => without_chunks += 1,
            PrepareOutcome::Skipped => {}
        }
    }

    gauge!(RUNS_WAITING_BOUNDARY).set(waiting_boundary as f64);
    gauge!(RUNS_WITHOUT_CHUNKS).set(without_chunks as f64);
    let eligible_run_ids = eligible.keys().copied().collect::<Vec<_>>();
    match store.remaining_chunks(&eligible_run_ids).await {
        Ok(remaining) => gauge!(RUN_CHUNKS_REMAINING).set(remaining as f64),
        Err(error) => warn!(error = %error, "counting remaining chunks failed"),
    }
    reported_runs.retain(|run_id| seen_runs.contains(run_id));
    eligible
}

async fn prepare_run(
    pool: &PgPool,
    store: &PgChunkStore,
    plan_caps: PlanCaps,
    reported_runs: &mut HashSet<RunId>,
    run: DiscoveredRun,
) -> PrepareOutcome {
    counter!(RUNS_DISCOVERED, "status" => run.status.as_str()).increment(1);

    let was_awaiting_boundary = run.status == RunStatus::AwaitingBoundary;
    let discovered_run_id = run.run_id;
    let boundary = match establish_boundary(pool, run).await {
        Ok(BoundaryOutcome::Established(run)) => {
            counter!(BOUNDARY_ESTABLISHED, "trigger" => run.trigger.as_str()).increment(1);
            run
        }
        Ok(BoundaryOutcome::AlreadyEstablished(run)) => {
            if was_awaiting_boundary {
                counter!(BOUNDARY_CAS_LOST).increment(1);
            }
            run
        }
        Ok(BoundaryOutcome::NoLongerSeedable { .. }) => return PrepareOutcome::Skipped,
        Err(RunError::DisasterRecoveryBoundaryMissing(_)) => {
            return PrepareOutcome::WaitingBoundary;
        }
        Err(error) => {
            handle_run_error(pool, Some(discovered_run_id), error).await;
            return PrepareOutcome::Skipped;
        }
    };

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

    let days = plan_days(
        &validated.run.conditions,
        validated.run.boundary,
        &plan_caps,
    );
    if days.is_empty() {
        return PrepareOutcome::NoChunks;
    }
    match store
        .plan_chunks(validated.run.run_id, days, plan_caps.bands_per_day)
        .await
    {
        Ok(PlanOutcome::Planned { inserted }) => {
            counter!(CHUNKS_PLANNED).increment(inserted);
        }
        Ok(PlanOutcome::RunNotSeeding) => return PrepareOutcome::Skipped,
        Err(error) => {
            warn!(run_id = ?validated.run.run_id, error = %error, "chunk planning failed");
            return PrepareOutcome::Skipped;
        }
    }
    PrepareOutcome::Eligible(Arc::new(validated.run))
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
        RunError::InvalidTrigger { run_id, .. }
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
