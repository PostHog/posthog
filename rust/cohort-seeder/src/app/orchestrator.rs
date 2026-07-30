//! App layer: the seeder poll loop that discovers runs, fills claim slots, and drains on shutdown.
//! Depends on `store`, `clickhouse`, `kafka`, `domain`, and its `app` siblings (`prepare`,
//! `execute`, `person_execute`, `person_plan`, `settings`); it is the crate's top module, imported
//! only by `main`.

use std::collections::{HashMap, HashSet};
use std::time::Duration;

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
use crate::store::Claimant;

use super::completion::CompletionDriver;
use super::execute::{execute_chunk, record_task_result, ChunkOutcome, ChunkTaskContext};
use super::person_execute::{execute_person_chunk, PersonChunkTaskContext};
use super::person_plan::{plan_person_run, PersonPlanRequest};
use super::prepare::{refresh_runs, PreparedRun};
use super::settings::OrchestratorSettings;

const PRODUCER_FLUSH_TIMEOUT: Duration = Duration::from_secs(5);
pub const ORCHESTRATOR_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);
/// One planning scan at a time: it streams a team's whole live person-id set from ClickHouse.
const MAX_CONCURRENT_PLANNING_SCANS: usize = 1;

/// The person path's infra clients, present only when `SEEDER_PERSON_SEEDS_ENABLED` is on. The
/// pacer is separate from the behavioral tile pacer so the two throughputs tune independently.
pub struct PersonComponents {
    pub scanner: PersonScanner,
    pub pacer: TilePacer,
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
        let mut planning: JoinSet<RunId> = JoinSet::new();
        let mut planning_inflight: HashSet<RunId> = HashSet::new();
        let mut eligible_runs = HashMap::new();
        let mut reported_runs = HashSet::new();
        self.handle.report_healthy();
        info!(claimant = %self.claimant.as_str(), "cohort seeder orchestrator starting");

        loop {
            tokio::select! {
                biased;
                _ = shutdown.cancelled() => break,
                Some(result) = tasks.join_next(), if !tasks.is_empty() => {
                    record_task_result(result);
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &shutdown).await;
                    self.handle.report_healthy();
                }
                Some(result) = planning.join_next(), if !planning.is_empty() => {
                    match result {
                        Ok(run_id) => {
                            planning_inflight.remove(&run_id);
                        }
                        Err(error) => {
                            warn!(error = %error, "person planning task failed unexpectedly");
                            planning_inflight.clear();
                        }
                    }
                    self.handle.report_healthy();
                }
                _ = poll.tick() => {
                    let refreshed = refresh_runs(
                        &self.pool,
                        &self.store,
                        &self.allowlist,
                        self.settings.discovery_kinds(),
                        self.settings.plan_caps,
                        &mut reported_runs,
                    )
                    .await;
                    eligible_runs = refreshed.eligible;
                    self.spawn_person_planning(
                        refreshed.planning,
                        &mut planning,
                        &mut planning_inflight,
                        &shutdown,
                    );
                    self.reap_poisoned_chunks(&eligible_runs).await;
                    self.fill_claim_slots(&eligible_runs, &mut tasks, &shutdown).await;
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

    fn spawn_person_planning(
        &self,
        requests: Vec<PersonPlanRequest>,
        planning: &mut JoinSet<RunId>,
        planning_inflight: &mut HashSet<RunId>,
        shutdown: &CancellationToken,
    ) {
        let (Some(person), Some(person_settings)) = (&self.person, self.settings.person) else {
            return;
        };
        for request in requests {
            if planning.len() >= MAX_CONCURRENT_PLANNING_SCANS || shutdown.is_cancelled() {
                return;
            }
            if !planning_inflight.insert(request.run.run_id) {
                continue;
            }
            planning.spawn(plan_person_run(
                self.pool.clone(),
                self.store.clone(),
                person.scanner.clone(),
                person_settings.persons_per_chunk,
                request,
                shutdown.clone(),
            ));
        }
    }

    /// Dead-letter `scanning` chunks whose lease expired at the attempt cap — the chunks a
    /// hard-crashed worker left behind, which the claim predicate no longer reclaims.
    async fn reap_poisoned_chunks(&self, eligible_runs: &HashMap<RunId, PreparedRun>) {
        if eligible_runs.is_empty() {
            return;
        }
        let run_ids = eligible_runs.keys().copied().collect::<Vec<_>>();
        match self
            .store
            .reap_poisoned_chunks(&run_ids, self.settings.max_chunk_attempts)
            .await
        {
            Ok(0) => {}
            Ok(reaped) => {
                counter!(CHUNKS_POISONED).increment(reaped);
                warn!(
                    reaped,
                    "dead-lettered scanning chunks whose lease expired at the attempt cap"
                );
            }
            Err(error) => warn!(error = %error, "reaping poisoned chunks failed"),
        }
    }

    async fn fill_claim_slots(
        &self,
        eligible_runs: &HashMap<RunId, PreparedRun>,
        tasks: &mut JoinSet<ChunkOutcome>,
        shutdown: &CancellationToken,
    ) {
        if eligible_runs.is_empty() || shutdown.is_cancelled() {
            return;
        }
        let run_ids = eligible_runs.keys().copied().collect::<Vec<_>>();
        while tasks.len() < self.settings.max_concurrent_chunks.get() && !shutdown.is_cancelled() {
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
            if kind == ClaimKind::Reclaim {
                counter!(CHUNKS_RECLAIMED).increment(1);
            }
            let chunk_lease = chunk.spec().lease;
            let Some(prepared) = eligible_runs.get(&chunk_lease.run_id()) else {
                if let Err(error) = self.store.unclaim(chunk_lease).await {
                    warn!(?chunk_lease, error = %error, "claimed chunk had no validated run and could not be unclaimed");
                }
                continue;
            };
            match prepared {
                PreparedRun::Behavioral(run) => {
                    counter!(CHUNKS_CLAIMED).increment(1);
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
                    counter!(CHUNKS_CLAIMED).increment(1);
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
                    tasks.spawn(async move { execute_person_chunk(ctx, shutdown).await });
                }
            }
        }
    }
}
