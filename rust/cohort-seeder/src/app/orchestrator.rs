//! App layer: the seeder poll loop that discovers runs, fills claim slots, and drains on shutdown.
//! Depends on `store`, `clickhouse`, `kafka`, `domain`, and its `app` siblings (`prepare`, `execute`,
//! `settings`); it is the crate's top module, imported only by `main`.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use common_types::cohort::TeamAllowlist;
use lifecycle::Handle;
use metrics::counter;
use sqlx::PgPool;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::clickhouse::scanner::ChunkScanner;
use crate::domain::{ClaimKind, PinnedRun, RunId};
use crate::kafka::pacing::TilePacer;
use crate::kafka::producer::SeedTileProducer;
use crate::observability::metrics::{CHUNKS_CLAIMED, CHUNKS_POISONED, CHUNKS_RECLAIMED};
use crate::store::chunks::{Claim, PgChunkStore};
use crate::store::Claimant;

use super::execute::{execute_chunk, record_task_result, ChunkOutcome, ChunkTaskContext};
use super::prepare::refresh_runs;
use super::settings::OrchestratorSettings;

const PRODUCER_FLUSH_TIMEOUT: Duration = Duration::from_secs(5);
pub const ORCHESTRATOR_LIVENESS_DEADLINE: Duration = Duration::from_secs(60);

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
                _ = poll.tick() => {
                    eligible_runs = refresh_runs(
                        &self.pool,
                        &self.store,
                        &self.allowlist,
                        self.settings.plan_caps,
                        &mut reported_runs,
                    )
                    .await;
                    self.reap_poisoned_chunks(&eligible_runs).await;
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

    /// Dead-letter `scanning` chunks whose lease expired at the attempt cap — the chunks a
    /// hard-crashed worker left behind, which the claim predicate no longer reclaims.
    async fn reap_poisoned_chunks(&self, eligible_runs: &HashMap<RunId, Arc<PinnedRun>>) {
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
        eligible_runs: &HashMap<RunId, Arc<PinnedRun>>,
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
            let Some(run) = eligible_runs.get(&chunk.spec().lease.run_id()).cloned() else {
                let chunk_lease = chunk.spec().lease;
                if let Err(error) = self.store.unclaim(chunk_lease).await {
                    warn!(?chunk_lease, error = %error, "claimed chunk had no validated run and could not be unclaimed");
                }
                continue;
            };
            counter!(CHUNKS_CLAIMED).increment(1);
            let store = self.store.clone();
            let scanner = self.scanner.clone();
            let producer = self.producer.clone();
            let pacer = self.pacer.clone();
            let producer_settings = self.settings.producer;
            let shutdown = shutdown.clone();
            tasks.spawn(async move {
                execute_chunk(
                    ChunkTaskContext {
                        chunk,
                        lease,
                        run,
                        store,
                        scanner,
                        producer,
                        pacer,
                        producer_settings,
                    },
                    shutdown,
                )
                .await
            });
        }
    }
}
