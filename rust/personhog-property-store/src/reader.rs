use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use bytes::Bytes;
use futures::future::join_all;
use metrics::{counter, gauge, histogram};
use slatedb::config::DbReaderOptions;
use slatedb::db_cache::DbCache;
use slatedb::object_store::{self, ObjectStore};
use slatedb::{DbReader, DbReaderMode, ErrorKind};
use tokio::sync::{Notify, Semaphore};

use crate::encoding::{decode_value, encode_key, version_of, StoredProperties};
use crate::engine::{self, KeepNewest, ShardMetrics};
use crate::{shard_for, shard_path, PropertyStoreConfig, PropertyStoreError};

/// SlateDB retries without limit by default, and a cache load outlives the read that started it,
/// so an outage would leave loads retrying forever. A reader's failed poll only logs.
const READER_OBJECT_STORE_RETRIES: u32 = 5;

struct OpenReader {
    reader: Arc<DbReader>,
    metrics: ShardMetrics,
    last_read: Instant,
}

#[derive(Default)]
struct SlotState {
    reader: Option<OpenReader>,
    opening: bool,
    failure: Option<String>,
}

/// Opens on its own task, so a timed-out read never cancels a slow open.
#[derive(Default)]
struct ShardSlot {
    state: Mutex<SlotState>,
    opened: Notify,
}

struct Opener {
    object_store: Arc<dyn ObjectStore>,
    prefix: String,
    options: DbReaderOptions,
    cache: Arc<dyn DbCache>,
    closed: AtomicBool,
}

/// Every read is bounded by the read timeout, because SlateDB retries object-store errors without limit.
pub struct PropertyReader {
    opener: Arc<Opener>,
    /// Without a bound, one-off reads hung on an outage would all open at once when it ends.
    fresh_reads: Arc<Semaphore>,
    shards: u32,
    read_timeout: Duration,
    open_timeout: Duration,
    idle: Duration,
    slots: Mutex<HashMap<u32, Arc<ShardSlot>>>,
    /// Owned `(partition, partitions)` pairs; two moduli can share a shard during a migration.
    held: Mutex<HashSet<(u32, u32)>>,
}

impl PropertyReader {
    pub fn new(config: &PropertyStoreConfig, object_store: Arc<dyn ObjectStore>) -> Self {
        Self {
            opener: Arc::new(Opener {
                object_store,
                prefix: config.prefix.clone(),
                options: DbReaderOptions {
                    manifest_poll_interval: config.reader_poll_interval(),
                    max_memtable_bytes: config.reader_memtable_bytes,
                    skip_wal_replay: config.reader_skip_wal,
                    object_store_max_retries: Some(READER_OBJECT_STORE_RETRIES),
                    ..DbReaderOptions::default()
                },
                cache: engine::shared_cache(config),
                closed: AtomicBool::new(false),
            }),
            fresh_reads: Arc::new(Semaphore::new(config.max_fresh_reads.max(1))),
            shards: config.shards.max(1),
            read_timeout: config.read_timeout(),
            open_timeout: config.open_timeout(),
            idle: config.reader_idle(),
            slots: Mutex::new(HashMap::new()),
            held: Mutex::new(HashSet::new()),
        }
    }

    /// A shard that cannot be opened is an error, never an absent person.
    pub async fn get(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<StoredProperties>, PropertyStoreError> {
        match tokio::time::timeout(self.read_timeout, self.read(team_id, person_id)).await {
            Ok(result) => result,
            Err(_) => {
                counter!("personhog_property_store_read_timeouts_total").increment(1);
                Err(PropertyStoreError::Timeout)
            }
        }
    }

    async fn read(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<StoredProperties>, PropertyStoreError> {
        let shard = shard_for(team_id, person_id, self.shards);
        let reader = self.reader(shard).await?;
        let raw = match reader.get(encode_key(team_id, person_id)).await {
            Ok(raw) => raw,
            Err(e) => {
                // A reader following the latest manifest has no garbage collection protection, so a
                // compaction can delete an SST its stale manifest still names. Reopening reads the new one.
                if is_missing_object(&e) {
                    self.evict(shard, &reader, "missing_data").await;
                }
                return Err(e.into());
            }
        };
        match raw {
            Some(raw) => Ok(Some(decode_value(team_id, person_id, raw)?)),
            None => Ok(None),
        }
    }

    fn slot(&self, shard: u32) -> Arc<ShardSlot> {
        let mut slots = self.slots.lock().expect("readers lock poisoned");
        Arc::clone(slots.entry(shard).or_default())
    }

    async fn reader(&self, shard: u32) -> Result<Arc<DbReader>, PropertyStoreError> {
        let slot = self.slot(shard);
        loop {
            if self.opener.closed.load(Ordering::SeqCst) {
                return Err(PropertyStoreError::ShardUnavailable {
                    shard,
                    reason: "the reader is closed".to_string(),
                });
            }
            // Enabled before the check, so an open that finishes in between still wakes us.
            let opened = slot.opened.notified();
            tokio::pin!(opened);
            opened.as_mut().enable();
            {
                let mut state = slot.state.lock().expect("reader slot lock poisoned");
                if let Some(open) = state.reader.as_mut() {
                    open.last_read = Instant::now();
                    return Ok(Arc::clone(&open.reader));
                }
                if !state.opening {
                    state.opening = true;
                    state.failure = None;
                    tokio::spawn(open(Arc::clone(&self.opener), shard, Arc::clone(&slot)));
                }
            }
            opened.await;
            let mut state = slot.state.lock().expect("reader slot lock poisoned");
            if let Some(open) = state.reader.as_mut() {
                open.last_read = Instant::now();
                return Ok(Arc::clone(&open.reader));
            }
            if let Some(reason) = state.failure.clone() {
                return Err(PropertyStoreError::ShardUnavailable { shard, reason });
            }
        }
    }

    /// Whether any shard still holds a key of the team.
    pub async fn team_has_keys(&self, team_id: i64) -> Result<bool, PropertyStoreError> {
        let start = Bytes::copy_from_slice(&encode_key(team_id, 0));
        let end = Bytes::copy_from_slice(&encode_key(team_id, i64::MAX));
        for shard in 0..self.shards {
            let found = async {
                let reader = self.reader(shard).await?;
                let mut keys = reader.scan(start.clone()..=end.clone()).await?;
                Ok::<_, PropertyStoreError>(keys.next().await?.is_some())
            };
            match tokio::time::timeout(self.open_timeout, found).await {
                Ok(Ok(true)) => return Ok(true),
                Ok(Ok(false)) => {}
                Ok(Err(e)) => return Err(e),
                Err(_) => return Err(PropertyStoreError::Timeout),
            }
        }
        Ok(false)
    }

    pub async fn open_partition(
        &self,
        partition: u32,
        partitions: u32,
    ) -> Result<(), PropertyStoreError> {
        self.hold(partition, partitions, true);
        let opened: Result<(), PropertyStoreError> = join_all(
            self.partition_shards(partition, partitions)
                .map(|shard| async move {
                    match tokio::time::timeout(self.open_timeout, self.reader(shard)).await {
                        Ok(opened) => opened.map(drop),
                        Err(_) => {
                            counter!("personhog_property_store_reader_open_failures_total", "kind" => "timeout")
                                .increment(1);
                            Err(PropertyStoreError::ShardUnavailable {
                                shard,
                                reason: "the open timed out".to_string(),
                            })
                        }
                    }
                }),
        )
        .await
        .into_iter()
        .collect();
        if opened.is_err() {
            self.hold(partition, partitions, false);
        }
        opened
    }

    pub fn release_partition(&self, partition: u32, partitions: u32) {
        self.hold(partition, partitions, false);
    }

    fn partition_shards(&self, partition: u32, partitions: u32) -> impl Iterator<Item = u32> {
        (partition..self.shards).step_by(partitions.max(1) as usize)
    }

    fn hold(&self, partition: u32, partitions: u32, held: bool) {
        let mut holds = self.held.lock().expect("held partitions lock poisoned");
        if held {
            holds.insert((partition, partitions.max(1)));
        } else {
            holds.remove(&(partition, partitions.max(1)));
        }
    }

    pub async fn get_fresh(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<StoredProperties>, PropertyStoreError> {
        let shard = shard_for(team_id, person_id, self.shards);
        let key = encode_key(team_id, person_id);
        let Ok(permit) = Arc::clone(&self.fresh_reads).try_acquire_owned() else {
            counter!("personhog_property_store_fresh_reads_total", "outcome" => "refused")
                .increment(1);
            return Err(PropertyStoreError::ShardUnavailable {
                shard,
                reason: "too many one-off reads in flight".to_string(),
            });
        };
        // A reader dropped unclosed keeps polling the store, so its task always closes it.
        let (done, result) = tokio::sync::oneshot::channel();
        let opener = Arc::clone(&self.opener);
        tokio::spawn(async move {
            let _permit = permit;
            let started = Instant::now();
            let raw = match opener.build(shard, None).await {
                Ok(fresh) => {
                    let raw = fresh.get(key).await;
                    if let Err(e) = fresh.close().await {
                        tracing::debug!(shard, error = %e, "closing a one-off property store reader failed");
                    }
                    raw.map_err(PropertyStoreError::from)
                }
                Err(e) => Err(PropertyStoreError::from(e)),
            };
            let outcome = match &raw {
                Ok(Some(_)) => "found",
                Ok(None) => "missing",
                Err(_) => "error",
            };
            counter!("personhog_property_store_fresh_reads_total", "outcome" => outcome)
                .increment(1);
            histogram!("personhog_property_store_fresh_read_ms")
                .record(started.elapsed().as_secs_f64() * 1000.0);
            done.send(raw).ok();
        });
        let read = async {
            let raw = result
                .await
                .map_err(|_| PropertyStoreError::ShardUnavailable {
                    shard,
                    reason: "one-off read stopped".to_string(),
                })??;
            let stored = match raw {
                Some(raw) => Some(decode_value(team_id, person_id, raw)?),
                None => None,
            };
            self.evict_if_behind(shard, &key, stored.as_ref()).await;
            Ok(stored)
        };
        match tokio::time::timeout(self.read_timeout, read).await {
            Ok(result) => result,
            Err(_) => {
                counter!("personhog_property_store_read_timeouts_total").increment(1);
                Err(PropertyStoreError::Timeout)
            }
        }
    }

    async fn evict_if_behind(&self, shard: u32, key: &[u8], fresh: Option<&StoredProperties>) {
        let Some(fresh) = fresh else {
            return;
        };
        let slot = self.slot(shard);
        let cached = slot
            .state
            .lock()
            .expect("reader slot lock poisoned")
            .reader
            .as_ref()
            .map(|open| Arc::clone(&open.reader));
        let Some(cached) = cached else {
            return;
        };
        let behind = match cached.get(key.to_vec()).await {
            Ok(Some(raw)) => version_of(&raw).is_none_or(|version| version < fresh.version),
            Ok(None) | Err(_) => true,
        };
        if behind {
            self.evict(shard, &cached, "stale").await;
        }
    }

    async fn evict(&self, shard: u32, cached: &Arc<DbReader>, reason: &'static str) {
        let slot = self.slot(shard);
        let evicted = {
            let mut state = slot.state.lock().expect("reader slot lock poisoned");
            match state.reader.as_ref() {
                Some(open) if Arc::ptr_eq(&open.reader, cached) => state.reader.take(),
                _ => None,
            }
        };
        if let Some(evicted) = evicted {
            counter!("personhog_property_store_readers_closed_total", "reason" => reason)
                .increment(1);
            tracing::warn!(
                shard,
                reason,
                "closing a property store reader; the next read reopens it"
            );
            evicted.metrics.retire();
            if let Err(e) = evicted.reader.close().await {
                tracing::debug!(shard, error = %e, "closing a property store reader failed");
            }
        }
    }

    pub fn spawn_idle_reaper(self: &Arc<Self>) -> tokio::task::JoinHandle<()> {
        let reader = Arc::downgrade(self);
        let tick = (self.idle / 2).max(Duration::from_secs(1));
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(tick).await;
                let Some(reader) = reader.upgrade() else {
                    return;
                };
                reader.close_idle().await;
            }
        })
    }

    pub async fn close_idle(&self) -> usize {
        let mut idle = Vec::new();
        let mut still_open = 0;
        let held = self
            .held
            .lock()
            .expect("held partitions lock poisoned")
            .clone();
        for (shard, slot) in self.slots.lock().expect("readers lock poisoned").iter() {
            let is_held = held
                .iter()
                .any(|&(partition, partitions)| shard % partitions == partition);
            let mut state = slot.state.lock().expect("reader slot lock poisoned");
            match state.reader.as_ref() {
                Some(reader) if !is_held && reader.last_read.elapsed() >= self.idle => {
                    idle.push((*shard, state.reader.take().expect("checked above")));
                }
                Some(_) => still_open += 1,
                None => {}
            }
        }
        gauge!("personhog_property_store_open_readers").set(still_open as f64);
        for (shard, open) in idle {
            counter!("personhog_property_store_readers_closed_total", "reason" => "idle")
                .increment(1);
            open.metrics.retire();
            if let Err(e) = open.reader.close().await {
                tracing::debug!(shard, error = %e, "closing idle property store reader failed");
            }
        }
        still_open
    }

    pub async fn close(&self) {
        self.opener.closed.store(true, Ordering::SeqCst);
        let readers: Vec<(u32, OpenReader)> = self
            .slots
            .lock()
            .expect("readers lock poisoned")
            .drain()
            .filter_map(|(shard, slot)| {
                let reader = slot
                    .state
                    .lock()
                    .expect("reader slot lock poisoned")
                    .reader
                    .take()?;
                Some((shard, reader))
            })
            .collect();
        for (shard, open) in readers {
            open.metrics.retire();
            if let Err(e) = open.reader.close().await {
                tracing::warn!(shard, error = %e, "closing property store reader failed");
            }
        }
    }
}

/// Only a missing object; a corrupt one fails the same way after a reopen, so closing the reader gains nothing.
fn is_missing_object(error: &slatedb::Error) -> bool {
    let mut current: Option<&(dyn std::error::Error + 'static)> = Some(error);
    while let Some(err) = current {
        let not_found = err
            .downcast_ref::<object_store::Error>()
            .or_else(|| {
                err.downcast_ref::<Arc<object_store::Error>>()
                    .map(|e| e.as_ref())
            })
            .is_some_and(|e| matches!(e, object_store::Error::NotFound { .. }));
        if not_found {
            return true;
        }
        current = err.source();
    }
    false
}

impl Opener {
    async fn build(
        &self,
        shard: u32,
        metrics: Option<&ShardMetrics>,
    ) -> Result<DbReader, slatedb::Error> {
        let builder = DbReader::builder(
            shard_path(&self.prefix, shard),
            Arc::clone(&self.object_store),
        )
        .with_reader_mode(DbReaderMode::FollowLatest)
        .with_options(self.options.clone())
        .with_db_cache(Arc::clone(&self.cache), u64::from(shard))
        .with_merge_operator(Arc::new(KeepNewest));
        let builder = match metrics {
            Some(metrics) => builder.with_metrics_recorder(metrics.recorder()),
            None => builder,
        };
        builder.build().await
    }
}

async fn open(opener: Arc<Opener>, shard: u32, slot: Arc<ShardSlot>) {
    let metrics = ShardMetrics::new();
    let started = Instant::now();
    let opened = opener.build(shard, Some(&metrics)).await;
    histogram!("personhog_property_store_reader_open_ms")
        .record(started.elapsed().as_secs_f64() * 1000.0);
    let unwanted = {
        let mut state = slot.state.lock().expect("reader slot lock poisoned");
        state.opening = false;
        match opened {
            Ok(reader) if opener.closed.load(Ordering::SeqCst) => Some(reader),
            Ok(reader) => {
                counter!("personhog_property_store_readers_opened_total").increment(1);
                state.failure = None;
                state.reader = Some(OpenReader {
                    reader: Arc::new(reader),
                    metrics,
                    last_read: Instant::now(),
                });
                drop(state);
                slot.opened.notify_waiters();
                return;
            }
            Err(e) => {
                let kind = if e.kind() == ErrorKind::Data {
                    tracing::error!(shard, error = %e, "opening a property store reader failed");
                    "data"
                } else {
                    tracing::warn!(shard, error = %e, "opening a property store reader failed");
                    "unavailable"
                };
                counter!("personhog_property_store_reader_open_failures_total", "kind" => kind)
                    .increment(1);
                state.failure = Some(e.to_string());
                None
            }
        }
    };
    slot.opened.notify_waiters();
    metrics.retire();
    if let Some(reader) = unwanted {
        if let Err(e) = reader.close().await {
            tracing::debug!(shard, error = %e, "closing property store reader failed");
        }
    }
}
