use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures::future::join_all;
use metrics::{counter, histogram};
use slatedb::config::{CloseOptions, CompactorOptions, Settings};
use slatedb::db_cache::DbCache;
use slatedb::object_store::ObjectStore;
use slatedb::{CloseReason, CompactorBuilder, Db, ErrorKind, FilterPolicy, WriteBatch};
use tokio::sync::{Mutex, Notify};

use crate::encoding::{encode_key, encode_value, StoredProperties};
use crate::engine::{self, ExclusiveSubmissions, KeepNewest, ShardMetrics};
use crate::{shard_for, shard_path, PropertyStoreConfig, PropertyStoreError};

mod maintenance;

use maintenance::Tracked;

const OPEN_WAIT: Duration = Duration::from_secs(30);
const REOPEN_BACKOFF: Duration = Duration::from_secs(1);
/// Bounds one shard's maintenance step, so a hung shard cannot stall the rest.
const MAINTENANCE_STEP_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone)]
pub struct PropertyRecord {
    pub team_id: i64,
    pub person_id: i64,
    pub version: i64,
    pub deleted: bool,
    pub created_at: i64,
    pub properties: Bytes,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PartitionKey {
    pub topic: Arc<str>,
    pub partition: u32,
}

#[derive(Debug, thiserror::Error)]
pub enum PutError {
    /// Ownership moved since the batch began; nothing for the partition may be committed.
    #[error("ownership lost")]
    Lost,
    #[error("shards not open yet")]
    NotReady,
    #[error("invariant violated: {0}")]
    Invariant(String),
    #[error(transparent)]
    Store(#[from] PropertyStoreError),
}

struct Owned {
    generation: u64,
    partitions: u32,
    shards: HashMap<u32, OpenShard>,
    fenced_at: Option<Instant>,
}

struct OpenShard {
    db: Arc<Db>,
    metrics: ShardMetrics,
}

#[derive(Default)]
struct SlotState {
    owned: Option<Owned>,
    revoked_through: u64,
}

type Slot = Arc<Mutex<SlotState>>;

pub struct PropertyWriter {
    object_store: Arc<dyn ObjectStore>,
    prefix: String,
    shards: u32,
    settings: Settings,
    compactor_options: CompactorOptions,
    filter_policies: Vec<Arc<dyn FilterPolicy>>,
    cache: Arc<dyn DbCache>,
    memtable_flush: Option<Duration>,
    full_compaction: Option<Duration>,
    max_full_compactions: usize,
    slots: std::sync::Mutex<Slots>,
    assigned: Notify,
    full_compactions: std::sync::Mutex<HashMap<u32, Tracked>>,
    full_compacted_at: std::sync::Mutex<HashMap<u32, u64>>,
    full_cycles: std::sync::Mutex<HashMap<u32, u64>>,
}

#[derive(Default)]
struct Slots {
    by_partition: HashMap<PartitionKey, Slot>,
    closed: bool,
}

impl PropertyWriter {
    pub fn new(config: &PropertyStoreConfig, object_store: Arc<dyn ObjectStore>) -> Self {
        Self {
            object_store,
            prefix: config.prefix.clone(),
            shards: config.shards.max(1),
            settings: engine::settings(config),
            compactor_options: engine::compactor_options(config),
            filter_policies: engine::filter_policies(config),
            cache: engine::shared_cache(config),
            memtable_flush: config.memtable_flush_interval(),
            full_compaction: config.full_compaction_interval(),
            max_full_compactions: config.max_full_compactions.max(1),
            slots: std::sync::Mutex::new(Slots::default()),
            assigned: Notify::new(),
            full_compactions: std::sync::Mutex::new(HashMap::new()),
            full_compacted_at: std::sync::Mutex::new(HashMap::new()),
            full_cycles: std::sync::Mutex::new(HashMap::new()),
        }
    }

    pub fn check_partitions(&self, partitions: u32) -> Result<(), PropertyStoreError> {
        if partitions == 0 || !self.shards.is_multiple_of(partitions) {
            return Err(PropertyStoreError::ShardLayout(format!(
                "PROPERTY_STORE_SHARDS ({}) must be a multiple of the changelog partition count ({partitions})",
                self.shards
            )));
        }
        Ok(())
    }

    fn slot(&self, key: &PartitionKey) -> Option<Slot> {
        let mut slots = self.slots.lock().expect("slots lock poisoned");
        if slots.closed {
            return None;
        }
        Some(Arc::clone(
            slots.by_partition.entry(key.clone()).or_default(),
        ))
    }

    pub async fn assign(
        &self,
        key: &PartitionKey,
        generation: u64,
        partitions: u32,
        still_assigned: impl Fn() -> bool,
    ) -> Result<(), PropertyStoreError> {
        self.check_partitions(partitions)?;
        let Some(slot) = self.slot(key) else {
            return Ok(());
        };
        let mut state = slot.lock().await;
        if generation <= state.revoked_through
            || state
                .owned
                .as_ref()
                .is_some_and(|o| o.generation >= generation)
        {
            return Ok(());
        }
        if let Some(previous) = state.owned.take() {
            close_all(previous.shards).await;
        }
        if !still_assigned() {
            return Ok(());
        }
        let shards = self.open_shards(key.partition, partitions).await?;
        state.owned = Some(Owned {
            generation,
            partitions,
            shards,
            fenced_at: None,
        });
        drop(state);
        counter!("personhog_property_store_ownership_total", "event" => "assigned").increment(1);
        self.assigned.notify_waiters();
        Ok(())
    }

    pub async fn revoke(&self, key: &PartitionKey, generation: u64) {
        let Some(slot) = self.slot(key) else {
            return;
        };
        let mut state = slot.lock().await;
        state.revoked_through = state.revoked_through.max(generation);
        if state
            .owned
            .as_ref()
            .is_some_and(|o| o.generation <= generation)
        {
            if let Some(previous) = state.owned.take() {
                self.forget_full_compactions(previous.shards.keys());
                close_all(previous.shards).await;
            }
            counter!("personhog_property_store_ownership_total", "event" => "revoked").increment(1);
        }
        drop(state);
        self.assigned.notify_waiters();
    }

    pub async fn put(
        &self,
        key: &PartitionKey,
        generation: u64,
        records: &[PropertyRecord],
    ) -> Result<(), PutError> {
        if records.is_empty() {
            return Ok(());
        }
        let Some(slot) = self.slot(key) else {
            return Err(PutError::Lost);
        };
        let deadline = Instant::now() + OPEN_WAIT;
        let mut guard = loop {
            // Enabled before the check, so an assign that lands in between still wakes us.
            let notified = self.assigned.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let guard = slot.lock().await;
            if generation <= guard.revoked_through {
                return Err(PutError::Lost);
            }
            match guard.owned.as_ref().map(|o| o.generation) {
                Some(held) if held == generation => break guard,
                Some(held) if held > generation => return Err(PutError::Lost),
                _ => {}
            }
            drop(guard);
            if tokio::time::timeout_at(deadline.into(), notified)
                .await
                .is_err()
            {
                return Err(PutError::NotReady);
            }
        };
        let state = guard
            .owned
            .as_mut()
            .expect("held at the batch's generation");

        if let Some(fenced_at) = state.fenced_at {
            if fenced_at.elapsed() < REOPEN_BACKOFF {
                return Err(PutError::Lost);
            }
            // Still assigned here, so the fencing writer opened late: retry without a strike.
            close_all(std::mem::take(&mut state.shards)).await;
            state.shards = match self.open_shards(key.partition, state.partitions).await {
                Ok(shards) => shards,
                Err(e) => {
                    tracing::warn!(topic = %key.topic, partition = key.partition, error = %e, "reopening fenced property store shards failed");
                    state.fenced_at = Some(Instant::now());
                    return Err(PutError::NotReady);
                }
            };
            state.fenced_at = None;
            counter!("personhog_property_store_ownership_total", "event" => "reopened")
                .increment(1);
        }

        let mut by_shard: HashMap<u32, Vec<&PropertyRecord>> = HashMap::new();
        for record in records {
            let shard = shard_for(record.team_id, record.person_id, self.shards);
            if shard % state.partitions != key.partition {
                return Err(PutError::Invariant(format!(
                    "team {} person {} hashes to shard {shard}, outside partition {} of {}",
                    record.team_id, record.person_id, key.partition, state.partitions
                )));
            }
            by_shard.entry(shard).or_default().push(record);
        }

        let results = join_all(by_shard.into_iter().map(|(shard, records)| {
            let db = Arc::clone(
                &state
                    .shards
                    .get(&shard)
                    .expect("every owned shard is open")
                    .db,
            );
            async move { (shard, self.put_shard(&db, records).await) }
        }))
        .await;
        let mut failure = None;
        for (shard, result) in results {
            match result {
                Ok(()) => {}
                Err(e) if matches!(e.kind(), ErrorKind::Closed(CloseReason::Fenced)) => {
                    tracing::warn!(topic = %key.topic, partition = key.partition, shard, "property store shard fenced by another writer");
                    failure = Some(PutError::Lost);
                }
                Err(e) => {
                    let error = PropertyStoreError::from(e);
                    counter!("personhog_property_store_put_failures_total", "kind" => error.class())
                        .increment(1);
                    if failure.is_none() {
                        failure = Some(error.into());
                    }
                }
            }
        }
        match failure {
            Some(PutError::Lost) => {
                state.fenced_at = Some(Instant::now());
                counter!("personhog_property_store_ownership_total", "event" => "fenced")
                    .increment(1);
                Err(PutError::Lost)
            }
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    async fn put_shard(
        &self,
        db: &Db,
        records: Vec<&PropertyRecord>,
    ) -> Result<(), slatedb::Error> {
        let mut newest: HashMap<(i64, i64), &PropertyRecord> = HashMap::new();
        for record in records {
            newest
                .entry((record.team_id, record.person_id))
                .and_modify(|held| {
                    if record.version > held.version {
                        *held = record;
                    }
                })
                .or_insert(record);
        }
        let mut batch = WriteBatch::new();
        for ((team_id, person_id), record) in &newest {
            batch.merge(
                encode_key(*team_id, *person_id),
                encode_value(&StoredProperties {
                    version: record.version,
                    deleted: record.deleted,
                    created_at: record.created_at,
                    properties: if record.deleted {
                        Bytes::new()
                    } else {
                        record.properties.clone()
                    },
                }),
            );
        }
        let started = Instant::now();
        let written = db.write(batch).await?;
        // Flush the log now: the caller commits offsets once this returns.
        db.flush().await?;
        written.await_durable().await?;
        histogram!("personhog_property_store_durable_write_ms")
            .record(started.elapsed().as_secs_f64() * 1000.0);
        counter!("personhog_property_store_puts_total", "outcome" => "written")
            .increment(newest.len() as u64);
        Ok(())
    }

    async fn open_shards(
        &self,
        partition: u32,
        partitions: u32,
    ) -> Result<HashMap<u32, OpenShard>, PropertyStoreError> {
        let shards: Vec<u32> = (partition..self.shards)
            .step_by(partitions as usize)
            .collect();
        let opened = join_all(shards.iter().map(|&shard| async move {
            let started = Instant::now();
            let metrics = ShardMetrics::new();
            let compactor = CompactorBuilder::new(
                shard_path(&self.prefix, shard),
                Arc::clone(&self.object_store),
            )
            .with_options(self.compactor_options.clone())
            .with_filter_policies(self.filter_policies.clone())
            .with_scheduler_supplier(Arc::new(ExclusiveSubmissions));
            let db = Db::builder(
                shard_path(&self.prefix, shard),
                Arc::clone(&self.object_store),
            )
            .with_settings(self.settings.clone())
            .with_compactor_builder(compactor)
            .with_filter_policies(self.filter_policies.clone())
            .with_db_cache(Arc::clone(&self.cache), u64::from(shard))
            .with_merge_operator(Arc::new(KeepNewest))
            .with_metrics_recorder(metrics.recorder())
            .build()
            .await;
            match db {
                Ok(db) => {
                    histogram!("personhog_property_store_shard_open_ms")
                        .record(started.elapsed().as_secs_f64() * 1000.0);
                    Ok((
                        shard,
                        OpenShard {
                            db: Arc::new(db),
                            metrics,
                        },
                    ))
                }
                Err(e) => {
                    metrics.retire();
                    let error = PropertyStoreError::from(e);
                    counter!("personhog_property_store_shard_open_failures_total", "kind" => error.class())
                        .increment(1);
                    Err(error)
                }
            }
        }))
        .await;
        let mut shards = HashMap::with_capacity(opened.len());
        let mut failure = None;
        for result in opened {
            match result {
                Ok((shard, open)) => {
                    shards.insert(shard, open);
                }
                Err(e) => failure = Some(e),
            }
        }
        match failure {
            None => Ok(shards),
            // The retry reopens every shard, so close the ones that opened.
            Some(e) => {
                close_all(shards).await;
                Err(e)
            }
        }
    }

    /// Waits out a write in progress, so a partition that is always writing still gets maintained.
    async fn open_dbs(&self) -> Vec<(u32, Arc<Db>)> {
        let slots: Vec<Slot> = self
            .slots
            .lock()
            .expect("slots lock poisoned")
            .by_partition
            .values()
            .cloned()
            .collect();
        let held = join_all(slots.iter().map(|slot| async move {
            let state = tokio::time::timeout(MAINTENANCE_STEP_TIMEOUT, slot.lock())
                .await
                .ok()?;
            let owned = state.owned.as_ref()?;
            Some(
                owned
                    .shards
                    .iter()
                    .map(|(&shard, open)| (shard, Arc::clone(&open.db)))
                    .collect::<Vec<_>>(),
            )
        }))
        .await;
        held.into_iter().flatten().flatten().collect()
    }

    pub async fn close(&self) {
        let slots: Vec<Slot> = {
            let mut slots = self.slots.lock().expect("slots lock poisoned");
            slots.closed = true;
            slots.by_partition.drain().map(|(_, slot)| slot).collect()
        };
        join_all(slots.into_iter().map(|slot| async move {
            if let Some(owned) = slot.lock().await.owned.take() {
                close_all(owned.shards).await;
            }
        }))
        .await;
    }
}

/// Every write was durable, so close skips the memtable flush; a fenced shard's close fails and is logged.
async fn close_all(shards: HashMap<u32, OpenShard>) {
    join_all(shards.into_iter().map(|(shard, open)| async move {
        let options = CloseOptions { flush_type: None };
        if let Err(e) = open.db.close_with_options(options).await {
            tracing::debug!(shard, error = %e, "closing property store shard failed");
        }
        open.metrics.retire();
    }))
    .await;
}

#[cfg(test)]
mod tests {
    use slatedb::object_store::local::LocalFileSystem;

    use super::*;

    pub(super) fn key() -> PartitionKey {
        PartitionKey {
            topic: Arc::from("changelog"),
            partition: 0,
        }
    }

    pub(super) async fn writer_with_two_l0_tables(
        store: &Arc<dyn ObjectStore>,
        generation: u64,
    ) -> PropertyWriter {
        let writer = PropertyWriter::new(
            &PropertyStoreConfig {
                full_compaction_secs: 1,
                ..PropertyStoreConfig::local("props", 1)
            },
            Arc::clone(store),
        );
        writer.assign(&key(), generation, 1, || true).await.unwrap();
        for version in 1..=2 {
            let record = PropertyRecord {
                team_id: 7,
                person_id: 1,
                version: version + 10 * generation as i64,
                deleted: false,
                created_at: 0,
                properties: Bytes::from_static(b"{}"),
            };
            writer.put(&key(), generation, &[record]).await.unwrap();
            writer.flush_memtables().await;
        }
        writer
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn maintenance_reaches_a_partition_while_a_write_holds_it() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        let writing = writer.slot(&key()).unwrap().lock_owned().await;

        let (dbs, ()) = tokio::join!(writer.open_dbs(), async move {
            tokio::task::yield_now().await;
            drop(writing);
        });

        assert_eq!(dbs.len(), 1);
        writer.close().await;
    }

    fn ssts(dir: &std::path::Path) -> Vec<std::path::PathBuf> {
        let compacted = dir.join("props/shard-00000/compacted");
        std::fs::read_dir(compacted)
            .map(|entries| entries.map(|e| e.unwrap().path()).collect())
            .unwrap_or_default()
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_reader_whose_sst_was_collected_reopens_on_the_next_read() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        let reader = crate::PropertyReader::new(
            &PropertyStoreConfig {
                reader_poll_ms: 600_000,
                ..PropertyStoreConfig::local("props", 1)
            },
            Arc::clone(&store),
        );
        assert!(reader.get(7, 1).await.unwrap().is_some());
        let before_compaction = ssts(dir.path());
        tokio::time::sleep(Duration::from_millis(1100)).await;
        let deadline = Instant::now() + Duration::from_secs(30);
        while writer.full_compacted_at.lock().unwrap().get(&0).is_none() {
            assert!(
                Instant::now() < deadline,
                "the full compaction never finished"
            );
            writer.compact_due().await;
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        for sst in before_compaction {
            std::fs::remove_file(sst).unwrap();
        }

        let collected = reader.get(7, 1).await;
        let reopened = reader.get(7, 1).await;

        assert!(collected.is_err(), "{collected:?}");
        assert_eq!(reopened.unwrap().map(|s| s.version), Some(12));
        reader.close().await;
        writer.close().await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_corrupt_table_fails_its_reads_without_closing_the_shard_reader() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        let reader = crate::PropertyReader::new(
            &PropertyStoreConfig {
                reader_poll_ms: 600_000,
                ..PropertyStoreConfig::local("props", 1)
            },
            Arc::clone(&store),
        );
        assert!(reader.get(7, 1).await.unwrap().is_some());
        for sst in ssts(dir.path()) {
            let corrupt: Vec<u8> = std::fs::read(&sst).unwrap().iter().map(|b| !b).collect();
            std::fs::write(sst, corrupt).unwrap();
        }

        let read = reader.get(7, 1).await;

        assert!(read.is_err(), "{read:?}");
        assert_eq!(
            reader.close_idle().await,
            1,
            "the shard's reader stays open"
        );
        reader.close().await;
        writer.close().await;
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_revoked_shard_leaves_no_full_compaction_state_behind() {
        let dir = tempfile::tempdir().unwrap();
        let store: Arc<dyn ObjectStore> =
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap());
        let writer = writer_with_two_l0_tables(&store, 1).await;
        tokio::time::sleep(Duration::from_millis(1100)).await;
        assert_eq!(writer.compact_due().await, 1, "a cycle is under way");

        writer.revoke(&key(), 1).await;

        assert!(writer.full_cycles.lock().unwrap().is_empty());
        assert!(writer.full_compactions.lock().unwrap().is_empty());
        assert!(writer.full_compacted_at.lock().unwrap().is_empty());
        writer.close().await;
    }
}
