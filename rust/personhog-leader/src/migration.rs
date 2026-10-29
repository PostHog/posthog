//! The leader's share of a changelog migration: seal the old generation and ack it.

use std::collections::{hash_map, BTreeSet, HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::parse_watch_value;

use metrics::{counter, histogram};
use personhog_coordination::protocol::migration::{seal_overdue, seal_targets};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{MigrationPhase, MigrationState, SealAck};
use tokio::sync::Semaphore;
use tokio::task::{JoinHandle, JoinSet};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::fencing::FencedChangelogProducers;

pub const ACTIVE_INTERVAL: Duration = Duration::from_millis(250);
pub const IDLE_INTERVAL: Duration = Duration::from_secs(2);
/// Each seal spends one blocking thread per lane.
const SEAL_CONCURRENCY: usize = 8;

pub struct SealDuty {
    pub store: Arc<PersonhogStore>,
    pub pod_name: String,
    pub fenced: Arc<FencedChangelogProducers>,
}

/// Registers the seal metrics at zero. Migrations are rare and short, so a
/// series born at its first seal would hide that seal from `increase()`.
fn register_seal_metrics() {
    for outcome in ["ok", "error"] {
        counter!("personhog_leader_fence_seal_total", "outcome" => outcome).increment(0);
    }
    for path in ["prepared", "cold"] {
        drop(histogram!("personhog_leader_fence_seal_ms", "path" => path));
    }
    counter!("personhog_leader_seal_duty_failures_total").increment(0);
    counter!("personhog_leader_seal_overdue_passes_total").increment(0);
}

impl SealDuty {
    /// Wakes when the saga or its phase changes, and on an interval for retries.
    pub async fn run(self, cancel: CancellationToken) {
        register_seal_metrics();
        let mut sealed: HashSet<(String, u32)> = HashSet::new();
        let mut preconnecting: HashMap<(String, u32), JoinHandle<()>> = HashMap::new();
        let mut acked: Option<(String, BTreeSet<u32>)> = None;
        let mut seen: Option<(String, MigrationPhase)> = None;
        let preconnects = Arc::new(Semaphore::new(SEAL_CONCURRENCY));
        let mut watch = None;
        loop {
            if watch.is_none() {
                watch = match self.store.current_revision().await {
                    Ok(revision) => self.store.watch_migration_from(revision + 1).await.ok(),
                    Err(_) => None,
                };
            }
            let interval = match self.store.get_migration().await {
                Ok(Some(migration)) => {
                    seen = Some((migration.id.clone(), migration.phase));
                    let pass = match migration.phase {
                        MigrationPhase::Freezing | MigrationPhase::Draining => {
                            self.prepare(&migration, &mut preconnecting, &preconnects)
                                .await
                        }
                        MigrationPhase::Sealing => {
                            self.tick(&migration, &mut sealed, &mut acked).await
                        }
                        _ => Ok(()),
                    };
                    if let Err(e) = pass {
                        warn!(migration = %migration.id, error = %e, "seal duty pass failed");
                        counter!("personhog_leader_seal_duty_failures_total").increment(1);
                    }
                    // Only Sealing retries on a clock; the watch wakes every other phase.
                    if migration.phase == MigrationPhase::Sealing {
                        ACTIVE_INTERVAL
                    } else {
                        IDLE_INTERVAL
                    }
                }
                Ok(None) => {
                    seen = None;
                    sealed.clear();
                    preconnecting.clear();
                    acked = None;
                    IDLE_INTERVAL
                }
                Err(e) => {
                    warn!(error = %e, "seal duty could not read the migration");
                    IDLE_INTERVAL
                }
            };
            let woke = async {
                let Some(stream) = watch.as_mut() else {
                    return std::future::pending().await;
                };
                loop {
                    match stream.message().await {
                        // The coordinator rewrites the record on every seal ack; only a
                        // new saga or phase is worth a pass.
                        Ok(Some(resp)) if !resp.canceled() => {
                            // A deletion has no value to parse, so it reads as no saga.
                            let changed = resp.events().iter().any(|e| {
                                parse_watch_value::<MigrationState>(e)
                                    .ok()
                                    .map(|m| (m.id, m.phase))
                                    != seen
                            });
                            if changed {
                                return true;
                            }
                        }
                        // A cancelled response ends the stream; rebuild it like a dead one.
                        _ => return false,
                    }
                }
            };
            tokio::select! {
                _ = cancel.cancelled() => return,
                _ = tokio::time::sleep(interval) => {}
                live = woke => {
                    if !live {
                        watch = None;
                    }
                }
            }
        }
    }

    async fn targets(&self, migration: &MigrationState, overdue: bool) -> Result<Vec<u32>, String> {
        let pods = self
            .store
            .list_pods()
            .await
            .map_err(|e| format!("list pods: {e}"))?;
        let registered: HashSet<&str> = pods.iter().map(|p| p.pod_name.as_str()).collect();
        let assignments = self
            .store
            .list_assignments()
            .await
            .map_err(|e| format!("list assignments: {e}"))?;
        // Past the grace the acks matter: what no ack reports sealed is a target too.
        let acks = if overdue {
            self.store
                .list_seal_acks()
                .await
                .map_err(|e| format!("list seal acks: {e}"))?
        } else {
            Vec::new()
        };
        Ok(seal_targets(
            &self.pod_name,
            &migration.id,
            migration.from.partitions,
            &assignments,
            &registered,
            &acks,
            overdue,
        ))
    }

    /// Asks for each target's old-topic connection unless a request for it is still
    /// running: one the sweep discarded is dialed again on the next pass.
    async fn prepare(
        &self,
        migration: &MigrationState,
        preconnecting: &mut HashMap<(String, u32), JoinHandle<()>>,
        preconnects: &Arc<Semaphore>,
    ) -> Result<(), String> {
        preconnecting.retain(|_, task| !task.is_finished());
        for partition in self.targets(migration, false).await? {
            let hash_map::Entry::Vacant(slot) =
                preconnecting.entry((migration.id.clone(), partition))
            else {
                continue;
            };
            let fenced = Arc::clone(&self.fenced);
            let from = migration.from.clone();
            let permits = Arc::clone(preconnects);
            slot.insert(tokio::spawn(async move {
                let _permit = permits.acquire().await;
                fenced.preconnect(partition, &from).await
            }));
        }
        Ok(())
    }

    /// One Sealing pass: seal every target not yet sealed, then ack the state of all of them.
    pub async fn tick(
        &self,
        migration: &MigrationState,
        sealed: &mut HashSet<(String, u32)>,
        acked: &mut Option<(String, BTreeSet<u32>)>,
    ) -> Result<(), String> {
        let overdue = seal_overdue(migration, assignment_coordination::util::now_millis());
        let targets = self.targets(migration, overdue).await?;
        let topic = migration.from.topic.as_str();
        let pending: Vec<u32> = targets
            .iter()
            .copied()
            .filter(|p| !sealed.contains(&(migration.id.clone(), *p)))
            .collect();
        if overdue && !pending.is_empty() {
            counter!("personhog_leader_seal_overdue_passes_total").increment(1);
            warn!(migration = %migration.id, partitions = ?pending, "partitions still unsealed past the seal grace; sealing every one this pod can reach");
        }
        if !pending.is_empty() {
            let permits = Arc::new(Semaphore::new(SEAL_CONCURRENCY));
            let mut seals = JoinSet::new();
            for partition in pending {
                let fenced = Arc::clone(&self.fenced);
                let from = migration.from.clone();
                let permits = Arc::clone(&permits);
                seals.spawn(async move {
                    let _permit = permits.acquire().await;
                    (partition, fenced.seal(partition, &from).await)
                });
            }
            while let Some(joined) = seals.join_next().await {
                let (partition, result) = joined.map_err(|e| format!("seal join: {e}"))?;
                match result {
                    Ok(path) => {
                        info!(partition, %topic, path, "sealed the old changelog partition");
                        sealed.insert((migration.id.clone(), partition));
                        // Acked as it lands; a failed write is retried by the next ack.
                        if let Err(e) = self.ack(migration, sealed, acked).await {
                            warn!(partition, error = %e, "seal ack failed; the next ack carries it");
                        }
                    }
                    Err(e) => warn!(partition, %topic, error = %e, "seal failed; retrying"),
                }
            }
        }
        self.ack(migration, sealed, acked).await
    }

    /// Reports every partition this process has sealed, so an overdue target
    /// drops out of the unsealed set once acked; a restarted leader reseals.
    async fn ack(
        &self,
        migration: &MigrationState,
        sealed: &HashSet<(String, u32)>,
        acked: &mut Option<(String, BTreeSet<u32>)>,
    ) -> Result<(), String> {
        let report: BTreeSet<u32> = sealed
            .iter()
            .filter(|(id, _)| *id == migration.id)
            .map(|(_, p)| *p)
            .collect();
        // An unchanged ack wakes the coordinator for nothing.
        if acked.as_ref() == Some(&(migration.id.clone(), report.clone())) {
            return Ok(());
        }
        self.store
            .put_seal_ack(&SealAck {
                migration_id: migration.id.clone(),
                pod_name: self.pod_name.clone(),
                sealed: report.clone(),
            })
            .await
            .map_err(|e| format!("write seal ack: {e}"))?;
        *acked = Some((migration.id.clone(), report));
        Ok(())
    }
}
