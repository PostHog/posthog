//! App layer: the seeder poll loop that discovers runs, fills claim slots, and drains on shutdown.
//! Depends on `store`, `clickhouse`, `kafka`, `domain`, and its `app` siblings (`prepare`,
//! `execute`, `person_execute`, `person_plan`, `settings`); it is the crate's top module, imported
//! only by `main`.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::counter;
use sqlx::PgPool;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::clickhouse::person_scanner::PersonScanner;
use crate::clickhouse::scanner::ChunkScanner;
use crate::domain::{ClaimKind, RunId};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{CHUNKS_CLAIMED, CHUNKS_POISONED, CHUNKS_RECLAIMED};
use crate::store::chunks::{Claim, PgChunkStore};
use crate::store::runs::RunKind;
use crate::store::Claimant;

use super::completion::CompletionDriver;
use super::execute::{execute_chunk, record_task_result, ChunkOutcome, ChunkTaskContext};
use super::person_execute::{execute_person_chunk, PersonChunkTaskContext};
use super::person_plan::{plan_person_run, PersonPlanAttempt, PersonPlanRequest};
use super::prepare::{refresh_runs, run_ids_of_kind, PreparedRun, RefreshOutcome};
use super::settings::OrchestratorSettings;

const PRODUCER_FLUSH_TIMEOUT: Duration = Duration::from_secs(5);
pub const ORCHESTRATOR_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);
/// One planning scan at a time: it streams a team's whole live person-id set from ClickHouse.
const MAX_CONCURRENT_PLANNING_SCANS: usize = 1;
/// How long a run whose planning attempt failed sits out before this replica retries — the
/// boundary scan is a full-table aggregation on shared ClickHouse, so a failure must not be
/// re-issued at the poll cadence. It also keeps one perpetually failing run from monopolizing the
/// planning slot: backed-off runs cede it to the next candidate.
const PERSON_PLANNING_RETRY_BACKOFF: Duration = Duration::from_secs(300);

/// The person path's infra clients, present only when `SEEDER_PERSON_SEEDS_ENABLED` is on. The
/// pacer is separate from the behavioral tile pacer so the two throughputs tune independently.
pub struct PersonComponents {
    pub scanner: PersonScanner,
    pub pacer: TilePacer,
}

/// The planning slot's bookkeeping: which runs a spawned task covers (keyed by task id, so a
/// panicked task un-tracks only itself) and when each run's last attempt failed.
#[derive(Default)]
struct PlanningState {
    inflight: HashMap<tokio::task::Id, RunId>,
    failed_at: HashMap<RunId, Instant>,
}

impl PlanningState {
    fn is_inflight(&self, run_id: RunId) -> bool {
        self.inflight.values().any(|inflight| *inflight == run_id)
    }

    fn in_backoff(&self, run_id: RunId) -> bool {
        self.failed_at
            .get(&run_id)
            .is_some_and(|failed_at| failed_at.elapsed() < PERSON_PLANNING_RETRY_BACKOFF)
    }

    /// Drop cool-downs that have run their course, bounding the failure map. Keyed on age, never on
    /// the pass's request set: `refresh_runs` yields no requests at all when discovery errors, and
    /// reading that as "nothing needs planning" would refund every cool-down and put a persistently
    /// failing run straight back into the sole planning slot.
    fn expire_backoffs(&mut self) {
        self.failed_at
            .retain(|_, failed_at| failed_at.elapsed() < PERSON_PLANNING_RETRY_BACKOFF);
    }
}

pub struct SeederOrchestrator {
    pool: PgPool,
    store: PgChunkStore,
    scanner: ChunkScanner,
    producer: SeedTileProducer,
    pacer: TilePacer,
    allowlist: TeamAllowlist,
    settings: OrchestratorSettings,
    handle: Handle,
    claimant: Claimant,
    completion_driver: Option<CompletionDriver>,
    person: Option<PersonComponents>,
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
        completion_driver: Option<CompletionDriver>,
        person: Option<PersonComponents>,
    ) -> Self {
        let claimant =
            Claimant::new(claimed_by).expect("seeder claimant is 1..=255 bytes by construction");
        Self {
            store: PgChunkStore::new(pool.clone()),
            pool,
            scanner,
            producer,
            pacer,
            allowlist,
            settings,
            handle,
            claimant,
            completion_driver,
            person,
        }
    }

    pub async fn process(self) {
        let _scope = self.handle.process_scope();
        let shutdown = self.handle.shutdown_token();
        let mut poll = tokio::time::interval(self.settings.run_poll_interval);
        poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let mut tasks = JoinSet::new();
        let mut person_tasks = JoinSet::new();
        let mut planning: JoinSet<(RunId, PersonPlanAttempt)> = JoinSet::new();
        let mut planning_state = PlanningState::default();
        let mut eligible_runs = HashMap::new();
        let mut reported_runs = HashSet::new();
        self.handle.report_healthy();
        info!(claimant = %self.claimant.as_str(), "cohort seeder orchestrator starting");

        loop {
            tokio::select! {
                biased;
                _ = shutdown.cancelled() => break,
                Some(result) = tasks.join_next(), if !tasks.is_empty() => {
                    record_task_result(result, RunKind::Behavioral);
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &mut person_tasks, &shutdown)
                        .await;
                    self.handle.report_healthy();
                }
                Some(result) = person_tasks.join_next(), if !person_tasks.is_empty() => {
                    record_task_result(result, RunKind::PersonProperty);
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &mut person_tasks, &shutdown)
                        .await;
                    self.handle.report_healthy();
                }
                Some(result) = planning.join_next_with_id(), if !planning.is_empty() => {
                    match result {
                        Ok((task_id, (run_id, attempt))) => {
                            planning_state.inflight.remove(&task_id);
                            if attempt == PersonPlanAttempt::Failed {
                                planning_state.failed_at.insert(run_id, Instant::now());
                            }
                        }
                        Err(error) => {
                            planning_state.inflight.remove(&error.id());
                            warn!(error = %error, "person planning task failed unexpectedly");
                        }
                    }
                    self.handle.report_healthy();
                }
                _ = poll.tick() => {
                    let RefreshOutcome { eligible, planning: requests } = refresh_runs(
                        &self.pool,
                        &self.store,
                        &self.allowlist,
                        self.settings.discovery_kinds(),
                        self.settings.plan_caps,
                        &mut reported_runs,
                    )
                    .await;
                    eligible_runs = eligible;
                    self.spawn_person_planning(
                        requests,
                        &mut planning,
                        &mut planning_state,
                        &shutdown,
                    );
                    self.reap_poisoned_chunks(&eligible_runs).await;
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &mut person_tasks, &shutdown)
                        .await;
                    if let Some(driver) = &self.completion_driver {
                        // Dispatch work is spawned off this tick, but observation runs inline: a few
                        // DB reads per reconciling run, plus at most one OffsetFetch and one
                        // watermark sweep for the whole tick (the driver memoizes both). If the
                        // per-run cost ever stops being negligible, observation must be spawned like
                        // dispatch to stay inside the liveness deadline.
                        driver.tick().await;
                    }
                    self.handle.report_healthy();
                }
            }
        }

        // The planning insert is a single statement, so aborting a planner mid-scan leaves either
        // zero chunks or all chunks.
        planning.shutdown().await;
        info!(
            active_chunks = tasks.len() + person_tasks.len(),
            "stopping claims and draining active chunks"
        );
        while let Some(result) = tasks.join_next().await {
            record_task_result(result, RunKind::Behavioral);
        }
        while let Some(result) = person_tasks.join_next().await {
            record_task_result(result, RunKind::PersonProperty);
        }

        let producer = self.producer.clone();
        match tokio::task::spawn_blocking(move || producer.flush(PRODUCER_FLUSH_TIMEOUT)).await {
            Ok(Ok(())) => {}
            Ok(Err(error)) => warn!(error = %error, "producer flush failed during shutdown"),
            Err(error) => warn!(error = %error, "producer flush task failed during shutdown"),
        }
        info!("cohort seeder orchestrator stopped");
    }

    fn spawn_person_planning(
        &self,
        requests: Vec<PersonPlanRequest>,
        planning: &mut JoinSet<(RunId, PersonPlanAttempt)>,
        state: &mut PlanningState,
        shutdown: &CancellationToken,
    ) {
        let (Some(person), Some(person_settings)) = (&self.person, self.settings.person) else {
            return;
        };
        state.expire_backoffs();
        for request in requests {
            if planning.len() >= MAX_CONCURRENT_PLANNING_SCANS || shutdown.is_cancelled() {
                return;
            }
            let run_id = request.run.run_id;
            if state.is_inflight(run_id) || state.in_backoff(run_id) {
                continue;
            }
            let handle = planning.spawn(plan_person_run(
                self.pool.clone(),
                self.store.clone(),
                person.scanner.clone(),
                person_settings.persons_per_chunk,
                request,
                shutdown.clone(),
            ));
            state.inflight.insert(handle.id(), run_id);
        }
    }

    /// Dead-letter `scanning` chunks whose lease expired at the attempt cap — the chunks a
    /// hard-crashed worker left behind, which the claim predicate no longer reclaims.
    async fn reap_poisoned_chunks(&self, eligible_runs: &HashMap<RunId, PreparedRun>) {
        for kind in [RunKind::Behavioral, RunKind::PersonProperty] {
            let run_ids = run_ids_of_kind(eligible_runs, kind);
            if run_ids.is_empty() {
                continue;
            }
            match self
                .store
                .reap_poisoned_chunks(&run_ids, self.settings.max_chunk_attempts)
                .await
            {
                Ok(0) => {}
                Ok(reaped) => {
                    counter!(CHUNKS_POISONED, "kind" => kind.as_str()).increment(reaped);
                    warn!(
                        reaped,
                        kind = kind.as_str(),
                        "dead-lettered scanning chunks whose lease expired at the attempt cap"
                    );
                }
                Err(error) => warn!(error = %error, "reaping poisoned chunks failed"),
            }
        }
    }

    /// Claim work for whichever kind still has slot capacity. The claimable run-id set is
    /// recomputed per claim from the remaining capacity, so a person chunk can never occupy a
    /// behavioral slot (or vice versa) — the two budgets are independent by construction.
    async fn fill_claim_slots(
        &self,
        eligible_runs: &HashMap<RunId, PreparedRun>,
        tasks: &mut JoinSet<ChunkOutcome>,
        person_tasks: &mut JoinSet<ChunkOutcome>,
        shutdown: &CancellationToken,
    ) {
        loop {
            if eligible_runs.is_empty() || shutdown.is_cancelled() {
                return;
            }
            let behavioral_room = tasks.len() < self.settings.max_concurrent_chunks.get();
            let person_room = self.settings.person.is_some_and(|person_settings| {
                person_tasks.len() < person_settings.max_concurrent_chunks.get()
            });
            let mut run_ids = Vec::with_capacity(eligible_runs.len());
            for (run_id, prepared) in eligible_runs {
                let admitted = match prepared {
                    PreparedRun::Behavioral(_) => behavioral_room,
                    PreparedRun::Person(_) => person_room,
                };
                if admitted {
                    run_ids.push(*run_id);
                }
            }
            if run_ids.is_empty() {
                return;
            }
            let claim = match self
                .store
                .claim_next(
                    &run_ids,
                    &self.claimant,
                    self.settings.chunk_lease,
                    self.settings.max_chunk_attempts,
                )
                .await
            {
                Ok(claim) => claim,
                Err(error) => {
                    warn!(error = %error, "chunk claim failed");
                    return;
                }
            };
            let Some(Claim { chunk, kind, lease }) = claim else {
                return;
            };
            let chunk_lease = chunk.spec().lease;
            let Some(prepared) = eligible_runs.get(&chunk_lease.run_id()) else {
                if let Err(error) = self.store.unclaim(chunk_lease).await {
                    warn!(?chunk_lease, error = %error, "claimed chunk had no validated run and could not be unclaimed");
                }
                continue;
            };
            match prepared {
                PreparedRun::Behavioral(run) => {
                    record_claim(kind, RunKind::Behavioral);
                    let ctx = ChunkTaskContext {
                        chunk,
                        lease,
                        run: run.clone(),
                        store: self.store.clone(),
                        scanner: self.scanner.clone(),
                        producer: self.producer.clone(),
                        pacer: self.pacer.clone(),
                        producer_settings: self.settings.producer,
                    };
                    let shutdown = shutdown.clone();
                    tasks.spawn(async move { execute_chunk(ctx, shutdown).await });
                }
                PreparedRun::Person(run) => {
                    // Unreachable while the gate is off: discovery never yields person runs then.
                    let (Some(person), Some(person_settings)) =
                        (&self.person, self.settings.person)
                    else {
                        if let Err(error) = self.store.unclaim(chunk_lease).await {
                            warn!(?chunk_lease, error = %error, "person chunk claimed with the person path disabled and could not be unclaimed");
                        }
                        continue;
                    };
                    record_claim(kind, RunKind::PersonProperty);
                    let ctx = PersonChunkTaskContext {
                        chunk,
                        lease,
                        run: run.clone(),
                        store: self.store.clone(),
                        scanner: person.scanner.clone(),
                        producer: self.producer.clone(),
                        pacer: person.pacer.clone(),
                        producer_settings: self.settings.producer,
                        emit_nonmatchers: person_settings.emit_nonmatchers,
                    };
                    let shutdown = shutdown.clone();
                    person_tasks.spawn(async move { execute_person_chunk(ctx, shutdown).await });
                }
            }
        }
    }
}

fn record_claim(claim_kind: ClaimKind, run_kind: RunKind) {
    counter!(CHUNKS_CLAIMED, "kind" => run_kind.as_str()).increment(1);
    if claim_kind == ClaimKind::Reclaim {
        counter!(CHUNKS_RECLAIMED, "kind" => run_kind.as_str()).increment(1);
    }
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    /// A bookkeeping pass must never refund an unexpired cool-down. Pruning against the pass's
    /// request set did: a discovery blip yields an empty set, which read as "no run needs
    /// planning" and handed a persistently failing run the planning slot again on the next tick.
    #[test]
    fn expiring_backoffs_keeps_an_unexpired_cooldown() {
        let mut state = PlanningState::default();
        let run_id = RunId(Uuid::nil());
        state.failed_at.insert(run_id, Instant::now());

        state.expire_backoffs();

        assert!(state.in_backoff(run_id));
    }
}
