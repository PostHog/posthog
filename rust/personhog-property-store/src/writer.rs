use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures::future::join_all;
use metrics::{counter, gauge, histogram};
use slatedb::admin::Admin;
use slatedb::compactor::{Compaction, CompactionSpec, CompactionStatus, SourceId};
use slatedb::config::{CloseOptions, FlushOptions, FlushType, Settings};
use slatedb::db_cache::DbCache;
use slatedb::manifest::VersionedManifest;
use slatedb::object_store::path::Path as ObjectPath;
use slatedb::object_store::{ObjectStore, ObjectStoreExt, PutPayload};
use slatedb::{CloseReason, Db, ErrorKind, FilterPolicy, WriteBatch};
use tokio::sync::{Mutex, Notify};

use crate::encoding::{encode_key, encode_value, StoredProperties};
use crate::engine::{self, KeepNewest, ShardMetrics};
use crate::{shard_for, shard_path, PropertyStoreConfig, PropertyStoreError};

const OPEN_WAIT: Duration = Duration::from_secs(30);
const REOPEN_BACKOFF: Duration = Duration::from_secs(1);
const MAINTENANCE_TICK: Duration = Duration::from_secs(60);
/// Bounds one shard's maintenance step, so a hung shard cannot stall the rest.
const MAINTENANCE_STEP_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone)]
pub struct PropertyRecord {
    pub team_id: i64,
    pub person_id: i64,
    pub version: i64,
    pub deleted: bool,
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

/// L0 moves to a sorted run before the runs merge, so a long merge never stalls flushes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stage {
    L0,
    Runs,
}

#[derive(Clone)]
struct Tracked {
    stage: Stage,
    compaction: Compaction,
    submitted: Instant,
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
                    if failure.is_none() {
                        failure = Some(PropertyStoreError::from(e).into());
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
            let db = Db::builder(
                shard_path(&self.prefix, shard),
                Arc::clone(&self.object_store),
            )
            .with_settings(self.settings.clone())
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
                    Err(PropertyStoreError::from(e))
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

    fn open_dbs(&self) -> Vec<(u32, Arc<Db>)> {
        let slots: Vec<Slot> = self
            .slots
            .lock()
            .expect("slots lock poisoned")
            .by_partition
            .values()
            .cloned()
            .collect();
        let mut dbs = Vec::new();
        for slot in slots {
            let Ok(state) = slot.try_lock() else {
                continue;
            };
            if let Some(owned) = state.owned.as_ref() {
                dbs.extend(
                    owned
                        .shards
                        .iter()
                        .map(|(&shard, open)| (shard, Arc::clone(&open.db))),
                );
            }
        }
        dbs
    }

    pub fn spawn_maintenance(self: &Arc<Self>) -> tokio::task::JoinHandle<()> {
        let writer = Arc::downgrade(self);
        let flush = self.memtable_flush;
        tokio::spawn(async move {
            let mut last_flush = Instant::now();
            loop {
                tokio::time::sleep(MAINTENANCE_TICK).await;
                let Some(writer) = writer.upgrade() else {
                    return;
                };
                if flush.is_some_and(|f| last_flush.elapsed() >= f) {
                    last_flush = Instant::now();
                    writer.flush_memtables().await;
                }
                writer.compact_due().await;
            }
        })
    }

    pub async fn flush_memtables(&self) {
        let options = FlushOptions {
            flush_type: FlushType::MemTable,
        };
        join_all(self.open_dbs().into_iter().map(|(shard, db)| {
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
        for (shard, db) in self.open_dbs() {
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
    fn forget_full_compactions<'a>(&self, shards: impl Iterator<Item = &'a u32>) {
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

    fn key() -> PartitionKey {
        PartitionKey {
            topic: Arc::from("changelog"),
            partition: 0,
        }
    }

    async fn writer_with_two_l0_tables(
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
                properties: Bytes::from_static(b"{}"),
            };
            writer.put(&key(), generation, &[record]).await.unwrap();
            writer.flush_memtables().await;
        }
        writer
    }

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
