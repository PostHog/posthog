use std::collections::{HashMap, HashSet};
use std::num::{NonZeroU32, NonZeroUsize};
use std::sync::Arc;
use std::time::Duration;

use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::{counter, gauge};
use sqlx::PgPool;
use tokio::task::JoinSet;
use tracing::{info, warn};

use crate::chunks::{ChunkError, ChunkLease, ChunkStore, ClaimedChunk};
use crate::domain::{plan_days, PlanCaps};
use crate::ids::RunId;
use crate::observability::metrics::{
    BOUNDARY_CAS_LOST, BOUNDARY_ESTABLISHED, CHUNKS_CLAIMED, CHUNKS_CONFIRMED, CHUNKS_FAILED,
    CHUNKS_PLANNED, CONDITIONS_DROPPED, LOOKBACK_TRUNCATED, RUNS_DISCOVERED, RUNS_WAITING_BOUNDARY,
    RUNS_WITHOUT_CHUNKS, RUN_CHUNKS_REMAINING, RUN_VALIDATION_FAILURES, TZ_FALLBACK,
    WINDOW_DAYS_MISMATCH,
};
use crate::pacing::TilePacer;
use crate::pinned::{Lookback, PinnedRun, PinnedWarning};
use crate::producer::{ProduceFailure, ProducerSettings, SeedTileProducer};
use crate::runs::{
    discover_runs, establish_boundary, fail_run, record_run_warning, BoundaryOutcome, RunError,
    RunStatus, RunWarningNote,
};
use crate::scan::{ChunkScanner, ScanFailure};

const PRODUCER_FLUSH_TIMEOUT: Duration = Duration::from_secs(5);
pub const ORCHESTRATOR_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, Copy)]
pub struct OrchestratorSettings {
    run_poll_interval: Duration,
    max_concurrent_chunks: NonZeroUsize,
    chunk_lease: Duration,
    max_chunk_attempts: NonZeroU32,
    plan_caps: PlanCaps,
    producer: ProducerSettings,
}

impl OrchestratorSettings {
    pub fn new(
        run_poll_interval: Duration,
        max_concurrent_chunks: usize,
        chunk_lease: Duration,
        max_chunk_attempts: u32,
        max_lookback_days: u32,
        producer: ProducerSettings,
    ) -> Result<Self, OrchestratorSettingsError> {
        if run_poll_interval.is_zero() {
            return Err(OrchestratorSettingsError::ZeroPollInterval);
        }
        if run_poll_interval >= ORCHESTRATOR_LIVENESS_DEADLINE {
            return Err(OrchestratorSettingsError::PollIntervalExceedsLivenessDeadline);
        }
        let max_concurrent_chunks = NonZeroUsize::new(max_concurrent_chunks)
            .ok_or(OrchestratorSettingsError::ZeroConcurrency)?;
        if chunk_lease < Duration::from_secs(3) {
            return Err(OrchestratorSettingsError::LeaseTooShort);
        }
        let max_chunk_attempts = NonZeroU32::new(max_chunk_attempts)
            .ok_or(OrchestratorSettingsError::ZeroMaxAttempts)?;
        Ok(Self {
            run_poll_interval,
            max_concurrent_chunks,
            chunk_lease,
            max_chunk_attempts,
            plan_caps: PlanCaps { max_lookback_days },
            producer,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum OrchestratorSettingsError {
    #[error("run poll interval must be greater than zero")]
    ZeroPollInterval,
    #[error("run poll interval must be shorter than the liveness deadline")]
    PollIntervalExceedsLivenessDeadline,
    #[error("maximum concurrent chunks must be greater than zero")]
    ZeroConcurrency,
    #[error("chunk lease must be at least three seconds")]
    LeaseTooShort,
    #[error("maximum chunk attempts must be greater than zero")]
    ZeroMaxAttempts,
}

pub struct SeederOrchestrator {
    pool: PgPool,
    store: ChunkStore,
    scanner: ChunkScanner,
    producer: SeedTileProducer,
    pacer: TilePacer,
    allowlist: TeamAllowlist,
    settings: OrchestratorSettings,
    handle: Handle,
    claimed_by: String,
}

impl SeederOrchestrator {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        pool: PgPool,
        scanner: ChunkScanner,
        producer: SeedTileProducer,
        pacer: TilePacer,
        allowlist: TeamAllowlist,
        settings: OrchestratorSettings,
        handle: Handle,
        claimed_by: String,
    ) -> Self {
        Self {
            store: ChunkStore::new(pool.clone()),
            pool,
            scanner,
            producer,
            pacer,
            allowlist,
            settings,
            handle,
            claimed_by,
        }
    }

    pub async fn process(self) {
        let _scope = self.handle.process_scope();
        let shutdown = self.handle.shutdown_token();
        let mut poll = tokio::time::interval(self.settings.run_poll_interval);
        poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let mut tasks = JoinSet::new();
        let mut eligible_runs = HashMap::new();
        let mut reported_runs = HashSet::new();
        self.handle.report_healthy();
        info!(claimant = %self.claimed_by, "cohort seeder orchestrator starting");

        loop {
            tokio::select! {
                biased;
                _ = shutdown.cancelled() => break,
                Some(result) = tasks.join_next(), if !tasks.is_empty() => {
                    record_task_result(result);
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &shutdown).await;
                    self.handle.report_healthy();
                }
                _ = poll.tick() => {
                    eligible_runs = self.refresh_runs(&mut reported_runs).await;
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &shutdown).await;
                    self.handle.report_healthy();
                }
            }
        }

        info!(
            active_chunks = tasks.len(),
            "stopping claims and draining active chunks"
        );
        while let Some(result) = tasks.join_next().await {
            record_task_result(result);
        }

        let producer = self.producer.clone();
        match tokio::task::spawn_blocking(move || producer.flush(PRODUCER_FLUSH_TIMEOUT)).await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => warn!(error = %error, "producer flush failed during shutdown"),
            Err(error) => warn!(error = %error, "producer flush task failed during shutdown"),
        }
        info!("cohort seeder orchestrator stopped");
    }

    async fn refresh_runs(
        &self,
        reported_runs: &mut HashSet<RunId>,
    ) -> HashMap<RunId, Arc<PinnedRun>> {
        let discovered = match discover_runs(&self.pool, &self.allowlist).await {
            Ok(runs) => runs,
            Err(error) => {
                let run_id = error.run_id();
                self.handle_run_error(run_id, error).await;
                return HashMap::new();
            }
        };
        let mut eligible = HashMap::with_capacity(discovered.len());
        let mut seen_runs = HashSet::with_capacity(discovered.len());
        let mut waiting_boundary = 0_u64;
        let mut without_chunks = 0_u64;

        for run in discovered {
            seen_runs.insert(run.run_id);
            counter!(RUNS_DISCOVERED, "status" => run.status.as_str()).increment(1);
            if run.trigger == crate::pinned::TriggerKind::DisasterRecovery
                && run.status == RunStatus::AwaitingBoundary
                && run.boundary_at.is_none()
            {
                waiting_boundary += 1;
                continue;
            }

            let was_awaiting_boundary = run.status == RunStatus::AwaitingBoundary;
            let discovered_run_id = run.run_id;
            let boundary = match establish_boundary(&self.pool, run).await {
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
                Ok(BoundaryOutcome::NoLongerSeedable { .. }) => continue,
                Err(RunError::DisasterRecoveryBoundaryMissing(_)) => {
                    waiting_boundary += 1;
                    continue;
                }
                Err(error) => {
                    self.handle_run_error(Some(discovered_run_id), error).await;
                    continue;
                }
            };

            let run_id = boundary.run_id;
            let validated = match boundary.load_pinned(&self.pool).await {
                Ok(validated) => validated,
                Err(error) => {
                    self.handle_run_error(Some(run_id), error).await;
                    continue;
                }
            };
            let lookback_truncated =
                lookback_was_truncated(&validated.run, self.settings.plan_caps);
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
                self.persist_run_warning(run_id, RunWarningNote::ConditionsDropped)
                    .await;
            }
            if lookback_truncated {
                self.persist_run_warning(run_id, RunWarningNote::LookbackTruncated)
                    .await;
            }

            let days = plan_days(
                &validated.run.conditions,
                validated.run.boundary,
                &self.settings.plan_caps,
            );
            if days.is_empty() {
                without_chunks += 1;
                continue;
            }
            match self.store.plan_chunks(validated.run.run_id, days).await {
                Ok(planned) => counter!(CHUNKS_PLANNED).increment(planned),
                Err(error) => {
                    warn!(run_id = ?validated.run.run_id, error = %error, "chunk planning failed");
                    continue;
                }
            }
            eligible.insert(validated.run.run_id, Arc::new(validated.run));
        }

        gauge!(RUNS_WAITING_BOUNDARY).set(waiting_boundary as f64);
        gauge!(RUNS_WITHOUT_CHUNKS).set(without_chunks as f64);
        let eligible_run_ids = eligible.keys().copied().collect::<Vec<_>>();
        match self.store.remaining_chunks(&eligible_run_ids).await {
            Ok(remaining) => gauge!(RUN_CHUNKS_REMAINING).set(remaining as f64),
            Err(error) => warn!(error = %error, "counting remaining chunks failed"),
        }
        reported_runs.retain(|run_id| seen_runs.contains(run_id));
        eligible
    }

    async fn handle_run_error(&self, run_id: Option<RunId>, error: RunError) {
        let disposition = run_error_disposition(run_id, &error);
        if let RunErrorDisposition::Fail { run_id, reason } = disposition {
            counter!(RUN_VALIDATION_FAILURES, "reason" => reason).increment(1);
            let detail = error.to_string();
            if let Err(failure) = fail_run(&self.pool, run_id, &detail).await {
                warn!(run_id = ?run_id, error = %failure, "failing invalid run did not apply");
            }
            return;
        }
        warn!(error = %error, "transient run preparation failed");
    }

    async fn persist_run_warning(&self, run_id: RunId, note: RunWarningNote) {
        if let Err(error) = record_run_warning(&self.pool, run_id, note).await {
            warn!(run_id = ?run_id, error = %error, "persisting run warning failed");
        }
    }

    async fn fill_claim_slots(
        &self,
        eligible_runs: &HashMap<RunId, Arc<PinnedRun>>,
        tasks: &mut JoinSet<ChunkTaskOutcome>,
        shutdown: &tokio_util::sync::CancellationToken,
    ) {
        if eligible_runs.is_empty() || shutdown.is_cancelled() {
            return;
        }
        let run_ids = eligible_runs.keys().copied().collect::<Vec<_>>();
        while tasks.len() < self.settings.max_concurrent_chunks.get() && !shutdown.is_cancelled() {
            let claimed = match self
                .store
                .claim_next(
                    &run_ids,
                    &self.claimed_by,
                    self.settings.chunk_lease,
                    self.settings.max_chunk_attempts.get(),
                )
                .await
            {
                Ok(claimed) => claimed,
                Err(error) => {
                    warn!(error = %error, "chunk claim failed");
                    return;
                }
            };
            let Some(chunk) = claimed else {
                return;
            };
            let Some(run) = eligible_runs.get(&chunk.lease().run_id()).cloned() else {
                let lease = chunk.lease();
                if let Err(error) = chunk.unclaim().await {
                    warn!(?lease, error = %error, "claimed chunk had no validated run and could not be unclaimed");
                }
                continue;
            };
            counter!(CHUNKS_CLAIMED).increment(1);
            let scanner = self.scanner.clone();
            let producer = self.producer.clone();
            let pacer = self.pacer.clone();
            let producer_settings = self.settings.producer;
            let shutdown = shutdown.clone();
            tasks.spawn(async move {
                execute_chunk(
                    chunk,
                    run,
                    scanner,
                    producer,
                    pacer,
                    producer_settings,
                    shutdown,
                )
                .await
            });
        }
    }
}

async fn execute_chunk(
    chunk: ClaimedChunk,
    run: Arc<PinnedRun>,
    scanner: ChunkScanner,
    producer: SeedTileProducer,
    pacer: TilePacer,
    producer_settings: ProducerSettings,
    shutdown: tokio_util::sync::CancellationToken,
) -> ChunkTaskOutcome {
    let scanned = match scanner.scan(chunk, &run, &shutdown).await {
        Ok(scanned) => scanned,
        Err(failure) => return recover_scan_failure(failure, &shutdown).await,
    };
    let produced = match producer
        .produce(scanned, &pacer, producer_settings, &shutdown)
        .await
    {
        Ok(produced) => produced,
        Err(failure) => return recover_produce_failure(failure, &shutdown).await,
    };
    let lease = produced.lease();
    let tiles_produced = produced.tiles_produced();
    match produced.confirm().await {
        Ok(()) => ChunkTaskOutcome::Confirmed {
            lease,
            tiles_produced,
        },
        Err(failure) => {
            let (produced, source) = failure.into_parts();
            let detail = source.to_string();
            match produced.fail(&detail).await {
                Ok(()) => ChunkTaskOutcome::Failed { lease, detail },
                Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
                    lease,
                    detail,
                    recovery,
                },
            }
        }
    }
}

async fn recover_scan_failure(
    failure: ScanFailure,
    shutdown: &tokio_util::sync::CancellationToken,
) -> ChunkTaskOutcome {
    let (chunk, source) = failure.into_parts();
    let lease = chunk.lease();
    let detail = source.to_string();
    if shutdown.is_cancelled() {
        return match chunk.unclaim().await {
            Ok(()) => ChunkTaskOutcome::Unclaimed { lease },
            Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
                lease,
                detail,
                recovery,
            },
        };
    }
    match chunk.fail(&detail).await {
        Ok(()) => ChunkTaskOutcome::Failed { lease, detail },
        Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
            lease,
            detail,
            recovery,
        },
    }
}

async fn recover_produce_failure(
    failure: ProduceFailure,
    shutdown: &tokio_util::sync::CancellationToken,
) -> ChunkTaskOutcome {
    match failure {
        ProduceFailure::BeforeMark { chunk, source } => {
            let lease = chunk.lease();
            let detail = source.to_string();
            if shutdown.is_cancelled() {
                return match chunk.unclaim().await {
                    Ok(()) => ChunkTaskOutcome::Unclaimed { lease },
                    Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
                        lease,
                        detail,
                        recovery,
                    },
                };
            }
            match chunk.fail(&detail).await {
                Ok(()) => ChunkTaskOutcome::Failed { lease, detail },
                Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
                    lease,
                    detail,
                    recovery,
                },
            }
        }
        ProduceFailure::AfterMark { chunk, source } => {
            let lease = chunk.lease();
            let detail = source.to_string();
            match chunk.fail(&detail).await {
                Ok(()) => ChunkTaskOutcome::Failed { lease, detail },
                Err(recovery) => ChunkTaskOutcome::RecoveryFailed {
                    lease,
                    detail,
                    recovery,
                },
            }
        }
    }
}

#[derive(Debug)]
enum ChunkTaskOutcome {
    Confirmed {
        lease: ChunkLease,
        tiles_produced: u64,
    },
    Failed {
        lease: ChunkLease,
        detail: String,
    },
    Unclaimed {
        lease: ChunkLease,
    },
    RecoveryFailed {
        lease: ChunkLease,
        detail: String,
        recovery: ChunkError,
    },
}

fn record_task_result(result: Result<ChunkTaskOutcome, tokio::task::JoinError>) {
    match result {
        Ok(ChunkTaskOutcome::Confirmed {
            lease,
            tiles_produced,
        }) => {
            counter!(CHUNKS_CONFIRMED).increment(1);
            info!(?lease, tiles_produced, "chunk confirmed");
        }
        Ok(ChunkTaskOutcome::Failed { lease, detail }) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(?lease, error = %detail, "chunk failed and was released for retry");
        }
        Ok(ChunkTaskOutcome::Unclaimed { lease }) => {
            info!(?lease, "chunk unclaimed during shutdown");
        }
        Ok(ChunkTaskOutcome::RecoveryFailed {
            lease,
            detail,
            recovery,
        }) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(?lease, error = %detail, recovery_error = %recovery, "chunk recovery update did not apply");
        }
        Err(error) => {
            counter!(CHUNKS_FAILED).increment(1);
            warn!(error = %error, "chunk task failed unexpectedly");
        }
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
    run.conditions
        .iter()
        .any(|condition| match condition.lookback {
            Lookback::SlidingDays(days) => days > caps.max_lookback_days,
            Lookback::FixedRange { from_day: None, .. } => true,
            Lookback::SubDay
            | Lookback::FixedRange {
                from_day: Some(_), ..
            }
            | Lookback::Dropped => false,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::producer::ProducerSettings;

    fn producer_settings() -> ProducerSettings {
        ProducerSettings::new(1, Duration::from_millis(1)).unwrap()
    }

    #[test]
    fn settings_reject_values_that_disable_progress_or_lease_heartbeats() {
        let cases = [
            (
                OrchestratorSettings::new(
                    ORCHESTRATOR_LIVENESS_DEADLINE,
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    producer_settings(),
                ),
                OrchestratorSettingsError::PollIntervalExceedsLivenessDeadline,
            ),
            (
                OrchestratorSettings::new(
                    Duration::ZERO,
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    producer_settings(),
                ),
                OrchestratorSettingsError::ZeroPollInterval,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    0,
                    Duration::from_secs(3),
                    1,
                    400,
                    producer_settings(),
                ),
                OrchestratorSettingsError::ZeroConcurrency,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(2),
                    1,
                    400,
                    producer_settings(),
                ),
                OrchestratorSettingsError::LeaseTooShort,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(3),
                    0,
                    400,
                    producer_settings(),
                ),
                OrchestratorSettingsError::ZeroMaxAttempts,
            ),
        ];
        for (result, expected) in cases {
            assert_eq!(result.unwrap_err(), expected);
        }
    }
}
