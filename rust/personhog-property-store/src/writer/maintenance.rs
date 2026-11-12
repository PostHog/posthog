//! Background work on the owned shards: memtable flushes on their own timer, and a full
//! compaction per shard on a schedule, so deleted persons leave the store.

use std::sync::{Arc, Weak};
use std::time::{Duration, Instant};

use futures::future::join_all;
use metrics::{counter, gauge, histogram};
use slatedb::admin::Admin;
use slatedb::compactor::{Compaction, CompactionSpec, CompactionStatus, SourceId};
use slatedb::config::{FlushOptions, FlushType};
use slatedb::manifest::VersionedManifest;
use slatedb::object_store::path::Path as ObjectPath;
use slatedb::object_store::{ObjectStoreExt, PutPayload};

use super::{PropertyWriter, MAINTENANCE_STEP_TIMEOUT};
use crate::shard_path;

const MAINTENANCE_TICK: Duration = Duration::from_secs(60);

/// L0 moves to a sorted run before the runs merge, so a long merge never stalls flushes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Stage {
    L0,
    Runs,
}

#[derive(Clone)]
pub(super) struct Tracked {
    stage: Stage,
    compaction: Compaction,
    submitted: Instant,
}

impl PropertyWriter {
    pub fn spawn_maintenance(self: &Arc<Self>) -> tokio::task::JoinHandle<()> {
        let writer = Arc::downgrade(self);
        let flush = self.memtable_flush;
        tokio::spawn(async move {
            match flush {
                Some(every) => {
                    tokio::join!(
                        flush_loop(Weak::clone(&writer), every),
                        compaction_loop(writer)
                    );
                }
                None => compaction_loop(writer).await,
            }
        })
    }

    pub async fn flush_memtables(&self) {
        let options = FlushOptions {
            flush_type: FlushType::MemTable,
        };
        join_all(self.open_dbs().await.into_iter().map(|(shard, db)| {
            let options = options.clone();
            async move {
                let flush = db.flush_with_options(options);
                let outcome = match tokio::time::timeout(MAINTENANCE_STEP_TIMEOUT, flush).await {
                    Ok(Ok(())) => "flushed",
                    Ok(Err(e)) => {
                        tracing::debug!(shard, error = %e, "memtable flush failed");
                        "failed"
                    }
                    Err(_) => "timed_out",
                };
                counter!("personhog_property_store_memtable_flushes_total", "outcome" => outcome)
                    .increment(1);
            }
        }))
        .await;
    }

    pub async fn compact_due(&self) -> usize {
        let Some(interval) = self.full_compaction else {
            return 0;
        };
        let mut in_flight = self.settle_full_compactions().await;
        let now = now_ms();
        let mut stalest = Duration::ZERO;
        let mut submitted = 0;
        for (shard, db) in self.open_dbs().await {
            let since = match self.full_compacted_at(shard).await {
                Some(at) => at,
                None => {
                    let manifest = db.manifest();
                    let oldest = manifest
                        .l0()
                        .iter()
                        .chain(
                            manifest
                                .compacted()
                                .iter()
                                .flat_map(|sr| sr.sst_views().iter()),
                        )
                        .map(|view| view.id.timestamp_ms())
                        .min();
                    match oldest {
                        Some(at) => at,
                        None => continue,
                    }
                }
            };
            let age = Duration::from_millis(now.saturating_sub(since));
            stalest = stalest.max(age);
            let cutoff = {
                let mut cycles = self.full_cycles.lock().expect("full cycles lock poisoned");
                match cycles.get(&shard) {
                    Some(&cutoff) => cutoff,
                    None if age >= interval => {
                        cycles.insert(shard, now);
                        now
                    }
                    None => continue,
                }
            };
            let tracked = self
                .full_compactions
                .lock()
                .expect("full compactions lock poisoned")
                .contains_key(&shard);
            if tracked || in_flight >= self.max_full_compactions {
                continue;
            }
            let step = tokio::time::timeout(
                MAINTENANCE_STEP_TIMEOUT,
                self.submit_next_stage(shard, cutoff),
            )
            .await;
            match step {
                Ok(Ok(Some(stage))) => {
                    in_flight += 1;
                    submitted += 1;
                    counter!("personhog_property_store_full_compactions_total", "stage" => stage_label(stage), "outcome" => "submitted")
                        .increment(1);
                }
                Ok(Ok(None)) => {}
                Ok(Err(e)) => {
                    tracing::warn!(shard, error = %e, "full compaction stage not submitted");
                    counter!("personhog_property_store_full_compactions_total", "stage" => "unknown", "outcome" => "submit_failed")
                        .increment(1);
                }
                Err(_) => {
                    tracing::warn!(shard, "submitting a full compaction stage timed out");
                    counter!("personhog_property_store_full_compactions_total", "stage" => "unknown", "outcome" => "submit_failed")
                        .increment(1);
                }
            }
        }
        gauge!("personhog_property_store_full_compaction_age_seconds").set(stalest.as_secs_f64());
        submitted
    }

    async fn settle_full_compactions(&self) -> usize {
        let tracked: Vec<(u32, Tracked)> = self
            .full_compactions
            .lock()
            .expect("full compactions lock poisoned")
            .iter()
            .map(|(&shard, tracked)| (shard, tracked.clone()))
            .collect();
        let mut in_flight = 0;
        for (shard, tracked) in tracked {
            let finished = tokio::time::timeout(
                MAINTENANCE_STEP_TIMEOUT,
                self.stage_outcome(shard, &tracked),
            )
            .await
            .unwrap_or(None);
            let Some(completed) = finished else {
                in_flight += 1;
                continue;
            };
            let outcome = if completed { "completed" } else { "failed" };
            counter!(
                "personhog_property_store_full_compactions_total",
                "stage" => stage_label(tracked.stage),
                "outcome" => outcome
            )
            .increment(1);
            // Settled on the maintenance tick, so durations are accurate to about one tick.
            histogram!(
                "personhog_property_store_full_compaction_stage_seconds",
                "stage" => stage_label(tracked.stage),
                "outcome" => outcome
            )
            .record(tracked.submitted.elapsed().as_secs_f64());
            self.full_compactions
                .lock()
                .expect("full compactions lock poisoned")
                .remove(&shard);
            if completed && tracked.stage == Stage::Runs {
                let cutoff = self
                    .full_cycles
                    .lock()
                    .expect("full cycles lock poisoned")
                    .remove(&shard);
                if let Some(cutoff) = cutoff {
                    self.record_full_compaction(shard, cutoff).await;
                }
            }
        }
        in_flight
    }

    async fn stage_outcome(&self, shard: u32, tracked: &Tracked) -> Option<bool> {
        let admin = self.admin(shard);
        match admin.read_compaction(tracked.compaction.id(), None).await {
            Ok(Some(c)) if c.status() == CompactionStatus::Completed => Some(true),
            Ok(Some(c)) if c.status() == CompactionStatus::Failed => Some(false),
            Ok(Some(_)) => None,
            Ok(None) => match admin.read_manifest(None).await {
                Ok(Some(manifest)) => Some(sources_gone(&tracked.compaction, &manifest)),
                Ok(None) => Some(false),
                Err(_) => None,
            },
            Err(e) => {
                tracing::debug!(shard, error = %e, "full compaction status unavailable");
                None
            }
        }
    }

    fn admin(&self, shard: u32) -> Admin {
        Admin::builder(
            shard_path(&self.prefix, shard),
            Arc::clone(&self.object_store),
        )
        .build()
    }

    async fn submit_next_stage(
        &self,
        shard: u32,
        cutoff: u64,
    ) -> Result<Option<Stage>, slatedb::Error> {
        let admin = self.admin(shard);
        let Some(manifest) = admin.read_manifest(None).await? else {
            return Ok(None);
        };
        let runs: Vec<u32> = manifest.compacted().iter().map(|sr| sr.id).collect();
        // Taken from the oldest end, so the window is the consecutive tail SlateDB requires.
        let mut old_l0: Vec<SourceId> = manifest
            .l0()
            .iter()
            .rev()
            .take_while(|view| view.id.timestamp_ms() < cutoff)
            .map(|view| SourceId::SstView(view.id))
            .collect();
        old_l0.reverse();
        let (stage, spec) = if !old_l0.is_empty() {
            // A clash with a routine compaction fails and is retried.
            let destination = runs.iter().max().map_or(0, |id| id + 1);
            (Stage::L0, CompactionSpec::new(old_l0, destination))
        } else if !runs.is_empty() {
            // A lone run is rewritten too, so SST settings such as filters reach existing data.
            let sources = runs.iter().map(|&id| SourceId::SortedRun(id)).collect();
            let destination = *runs.iter().min().expect("at least one run");
            (Stage::Runs, CompactionSpec::new(sources, destination))
        } else {
            self.full_cycles
                .lock()
                .expect("full cycles lock poisoned")
                .remove(&shard);
            self.record_full_compaction(shard, cutoff).await;
            return Ok(None);
        };
        let compaction = admin.submit_compaction(spec).await?;
        self.full_compactions
            .lock()
            .expect("full compactions lock poisoned")
            .insert(
                shard,
                Tracked {
                    stage,
                    compaction,
                    submitted: Instant::now(),
                },
            );
        Ok(Some(stage))
    }

    /// The shard's next owner keeps its own state; stale state here would mislead a later return.
    pub(super) fn forget_full_compactions<'a>(&self, shards: impl Iterator<Item = &'a u32>) {
        let mut compactions = self
            .full_compactions
            .lock()
            .expect("full compactions lock poisoned");
        let mut cycles = self.full_cycles.lock().expect("full cycles lock poisoned");
        let mut compacted_at = self
            .full_compacted_at
            .lock()
            .expect("full compaction times lock poisoned");
        for shard in shards {
            compactions.remove(shard);
            cycles.remove(shard);
            compacted_at.remove(shard);
        }
    }

    fn marker_path(&self, shard: u32) -> ObjectPath {
        ObjectPath::from(format!(
            "{}/maintenance/shard-{shard:05}/full-compaction",
            self.prefix
        ))
    }

    async fn full_compacted_at(&self, shard: u32) -> Option<u64> {
        if let Some(&at) = self
            .full_compacted_at
            .lock()
            .expect("full compaction times lock poisoned")
            .get(&shard)
        {
            return Some(at);
        }
        let read = async {
            let raw = self.object_store.get(&self.marker_path(shard)).await.ok()?;
            raw.bytes().await.ok()
        };
        let bytes = tokio::time::timeout(MAINTENANCE_STEP_TIMEOUT, read)
            .await
            .ok()??;
        let at = std::str::from_utf8(&bytes).ok()?.trim().parse().ok()?;
        self.full_compacted_at
            .lock()
            .expect("full compaction times lock poisoned")
            .insert(shard, at);
        Some(at)
    }

    async fn record_full_compaction(&self, shard: u32, at: u64) {
        self.full_compacted_at
            .lock()
            .expect("full compaction times lock poisoned")
            .insert(shard, at);
        let path = self.marker_path(shard);
        let put = self
            .object_store
            .put(&path, PutPayload::from(at.to_string()));
        match tokio::time::timeout(MAINTENANCE_STEP_TIMEOUT, put).await {
            Ok(Ok(_)) => {}
            Ok(Err(e)) => tracing::warn!(shard, error = %e, "recording a full compaction failed"),
            Err(_) => tracing::warn!(shard, "recording a full compaction timed out"),
        }
    }
}

async fn flush_loop(writer: Weak<PropertyWriter>, every: Duration) {
    loop {
        tokio::time::sleep(every).await;
        let Some(writer) = writer.upgrade() else {
            return;
        };
        writer.flush_memtables().await;
    }
}

async fn compaction_loop(writer: Weak<PropertyWriter>) {
    loop {
        tokio::time::sleep(MAINTENANCE_TICK).await;
        let Some(writer) = writer.upgrade() else {
            return;
        };
        writer.compact_due().await;
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn stage_label(stage: Stage) -> &'static str {
    match stage {
        Stage::L0 => "l0",
        Stage::Runs => "runs",
    }
}

fn sources_gone(compaction: &Compaction, manifest: &VersionedManifest) -> bool {
    let destination = compaction.spec().destination();
    compaction
        .spec()
        .sources()
        .iter()
        .all(|source| match source {
            SourceId::SstView(id) => manifest.l0().iter().all(|view| view.id != *id),
            SourceId::SortedRun(id) => {
                Some(*id) == destination || manifest.compacted().iter().all(|sr| sr.id != *id)
            }
        })
}

#[cfg(test)]
mod tests {
    use slatedb::object_store::local::LocalFileSystem;
    use slatedb::object_store::ObjectStore;

    use super::super::tests::writer_with_two_l0_tables;
    use super::*;

    #[tokio::test(flavor = "multi_thread")]
    async fn a_shard_comes_due_from_its_last_full_compaction_not_its_tables() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        tokio::time::sleep(Duration::from_millis(1100)).await;
        writer.record_full_compaction(0, now_ms()).await;

        assert_eq!(writer.compact_due().await, 0, "just recorded");
        writer.close().await;

        let restarted = writer_with_two_l0_tables(&store, 2).await;
        assert_eq!(
            restarted.compact_due().await,
            0,
            "recorded before the restart"
        );
        restarted.close().await;

        store.delete(&restarted.marker_path(0)).await.unwrap();
        let unrecorded = writer_with_two_l0_tables(&store, 3).await;
        assert_eq!(unrecorded.compact_due().await, 1);
        let stage = unrecorded
            .full_compactions
            .lock()
            .unwrap()
            .get(&0)
            .map(|tracked| tracked.stage);
        assert_eq!(stage, Some(Stage::L0));
        unrecorded.close().await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_full_compaction_rewrites_a_lone_sorted_run() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        tokio::time::sleep(Duration::from_millis(1100)).await;

        let mut stages = Vec::new();
        let deadline = Instant::now() + Duration::from_secs(30);
        while writer.full_compacted_at.lock().unwrap().get(&0).is_none() {
            assert!(
                Instant::now() < deadline,
                "the cycle never finished: {stages:?}"
            );
            writer.compact_due().await;
            let stage = writer
                .full_compactions
                .lock()
                .unwrap()
                .get(&0)
                .map(|tracked| tracked.stage);
            if let Some(stage) = stage {
                if stages.last() != Some(&stage) {
                    stages.push(stage);
                }
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }

        assert_eq!(stages, vec![Stage::L0, Stage::Runs]);
        writer.close().await;
    }
}
