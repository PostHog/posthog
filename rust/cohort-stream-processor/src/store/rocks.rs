//! RocksDB wrapper: multi-CF atomic `WriteBatch`, async WAL.

// This module defines the disallowed `CohortStore` I/O methods, which call one another internally
// (e.g. `apply` replays through the `write_batch` path). The lint targets async callers, not the
// store's own implementation.
#![allow(clippy::disallowed_methods)]

use std::cell::Cell;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use rocksdb::properties::{self, PropName};
use rocksdb::statistics::{StatsLevel, Ticker};
use rocksdb::{
    Cache, ColumnFamily, DBWithThreadMode, Direction, FlushOptions, IteratorMode, Options,
    ReadOptions, SingleThreaded, WriteBatch, WriteOptions,
};
use thiserror::Error;
use tracing::warn;

use super::column_families::{self, Cf, OpaqueCf};
use super::keys::{
    self, MergeAppliedKey, MergeDrainKey, PendingTransferKey, Stage2Key, TombstoneKey,
};
use super::keyspace::{
    BehavioralKey, Keyspace, Meta, PersonPrefix, PersonRecordKey, META_SCHEMA_VERSION,
};
use super::staged::{StagedBatch, StagedOp};
use crate::observability::metrics::{
    CHECKPOINT_DURATION_SECONDS, STORE_ERRORS_TOTAL, STORE_READS_TOTAL,
    STORE_READ_DURATION_SECONDS, STORE_SCHEMA_MISMATCH_WIPES_TOTAL, STORE_WRITE_BATCH_TOTAL,
    STORE_WRITE_DURATION_SECONDS, WAL_FSYNC_DURATION_SECONDS, WAL_FSYNC_ERRORS_TOTAL,
};

/// On-disk store schema version, stamped into `cf_meta` at first open and checked on every reopen.
/// A layout revision (key codec, value shape) that keeps the same CF set MUST bump this so an older
/// store fails fast instead of being misread; a CF-set change is caught independently by
/// `open_cf_descriptors`.
pub const STORE_SCHEMA_VERSION: u32 = 3;

const OP_OPEN: &str = "open";
const OP_DESTROY: &str = "destroy";
const OP_GET: &str = "get";
const OP_MULTI_GET: &str = "multi_get";
const OP_WRITE_BATCH: &str = "write_batch";
const OP_DELETE_PARTITION: &str = "delete_partition";
const OP_FLUSH: &str = "flush";
const OP_FLUSH_WAL: &str = "flush_wal";
const OP_SCAN: &str = "scan";
const OP_CHECKPOINT: &str = "checkpoint";

const DEFAULT_BLOCK_CACHE_BYTES: usize = 128 * 1024 * 1024;
const DEFAULT_WRITE_BUFFER_BYTES: usize = 64 * 1024 * 1024;
const DEFAULT_MAX_OPEN_FILES: i32 = 1024;
/// `get` is on the hot path, so sample the latency histogram 1-in-64 by default; the counter is exact.
const DEFAULT_READ_SAMPLE_RATIO: u32 = 64;

const DEFAULT_COMPACT_ON_DELETION_WINDOW: usize = 1000;
const DEFAULT_COMPACT_ON_DELETION_NUM_DELS_TRIGGER: usize = 500;
const DEFAULT_COMPACT_ON_DELETION_RATIO: f64 = 0.5;

/// Resolved RocksDB settings.
#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub path: PathBuf,
    /// Shared across all CFs; also holds index/filter blocks when `tuned_block_options` is set.
    pub block_cache_bytes: usize,
    pub write_buffer_bytes: usize,
    pub max_open_files: i32,
    pub create_if_missing: bool,
    /// Destroy any existing database at `path` before opening.
    pub wipe_on_start: bool,
    /// On a schema-version mismatch at open, destroy and recreate the store instead of failing fast.
    /// Off by default: a mismatch is a hard error so a stale store or checkpoint is never misread.
    pub wipe_on_schema_mismatch: bool,
    /// Enable RocksDB statistics so [`CohortStore::stats_snapshot`] reports live cache tickers; they
    /// read 0 when off.
    pub statistics_enabled: bool,
    /// Sample 1-in-N reads into [`STORE_READ_DURATION_SECONDS`] (the read counter stays exact).
    /// `1` records every read; clamped to `>= 1` at open.
    pub read_sample_ratio: u32,
    /// Cache and partition index/filter blocks so point lookups short-circuit on the bloom.
    pub tuned_block_options: bool,
    /// Mark tombstone-heavy SSTs for compaction.
    pub compact_on_deletion: bool,
    /// Window of recent entries the compact-on-deletion collector inspects.
    pub compact_on_deletion_window: usize,
    /// Tombstone count within the window that arms the collector.
    pub compact_on_deletion_num_dels_trigger: usize,
    /// Tombstone ratio that arms the collector; `<= 0` or `> 1` disables the ratio trigger.
    pub compact_on_deletion_ratio: f64,
    /// `0` disables it.
    pub periodic_compaction_seconds: u64,
    /// Non-positive leaves RocksDB's default untouched.
    pub max_background_jobs: i32,
    /// TTL in days for `cf_person_records`: a compaction filter drops a person record whose
    /// `last_seen_ms` is older than this. `0` (the default) installs no filter. Attached to
    /// `cf_person_records` **only** — never `cf_behavioral`, whose eviction deadlines are the sweep's
    /// contract. See [`super::ttl_filter`].
    pub person_record_ttl_days: u32,
}

impl Default for StoreConfig {
    fn default() -> Self {
        Self {
            path: PathBuf::from("cohort-store"),
            block_cache_bytes: DEFAULT_BLOCK_CACHE_BYTES,
            write_buffer_bytes: DEFAULT_WRITE_BUFFER_BYTES,
            max_open_files: DEFAULT_MAX_OPEN_FILES,
            create_if_missing: true,
            wipe_on_start: false,
            wipe_on_schema_mismatch: false,
            statistics_enabled: true,
            read_sample_ratio: DEFAULT_READ_SAMPLE_RATIO,
            tuned_block_options: true,
            compact_on_deletion: true,
            compact_on_deletion_window: DEFAULT_COMPACT_ON_DELETION_WINDOW,
            compact_on_deletion_num_dels_trigger: DEFAULT_COMPACT_ON_DELETION_NUM_DELS_TRIGGER,
            compact_on_deletion_ratio: DEFAULT_COMPACT_ON_DELETION_RATIO,
            periodic_compaction_seconds: 0,
            max_background_jobs: 0,
            person_record_ttl_days: 0,
        }
    }
}

/// Errors from the state store.
#[derive(Debug, Error)]
pub enum StoreError {
    #[error("opening RocksDB at {path:?}: {source}")]
    Open {
        path: PathBuf,
        source: rocksdb::Error,
    },

    #[error("RocksDB {op}: {source}")]
    Backend {
        op: &'static str,
        source: rocksdb::Error,
    },

    #[error("unknown column family: {0}")]
    UnknownColumnFamily(&'static str),

    #[error("decoding {kind} key: expected {expected} bytes, got {actual}")]
    KeyDecode {
        kind: &'static str,
        expected: usize,
        actual: usize,
    },

    /// A key of the right length that matches none of the keyspace's known literals (closed-set
    /// keyspaces like `cf_meta`). Distinct from [`Self::KeyDecode`], which reports a length mismatch.
    #[error("unknown {kind} key: matches no known literal")]
    UnknownKey { kind: &'static str },

    #[error(
        "store schema mismatch: on-disk version {found:?} != expected {expected}; refusing to open \
         (set COHORT_WIPE_ON_SCHEMA_MISMATCH=true to wipe and recreate)"
    )]
    SchemaMismatch { found: Option<u32>, expected: u32 },

    #[error("store offload cancelled by runtime shutdown")]
    OffloadCancelled,
}

/// One scanned key/value pair as raw bytes — the merge-CF GC decodes each per CF.
pub type RawKv = (Vec<u8>, Vec<u8>);

/// Handle to the per-process state store.
///
/// Writes have two layers. The closure-based [`Self::write_batch`] is for synchronous callers that
/// can borrow the store's CF handles for the duration of the call — it stages through a
/// [`BatchBuilder`] whose handles are tied to `&self`. [`StagedBatch`] plus [`Self::apply`] is the
/// owned staging path: keys and operands are encoded into owned bytes up front, so the batch is
/// `Send + 'static` and can be built on one thread and applied on another. Both funnel through the
/// same commit, so the two produce identical RocksDB writes.
#[derive(Clone)]
pub struct CohortStore {
    db: Arc<DBWithThreadMode<SingleThreaded>>,
    /// Retained so [`Self::stats_snapshot`] can read cache tickers: RocksDB shares one statistics
    /// handle between these `Options` and the live DB, so reads here reflect ongoing activity.
    db_opts: Arc<Options>,
    /// See [`StoreConfig::read_sample_ratio`]; `>= 1`.
    read_sample_ratio: u32,
}

impl CohortStore {
    /// Open the column families at `config.path`, creating them if missing.
    ///
    /// After open, the schema guard runs: a store that did not exist before this open is stamped with
    /// [`STORE_SCHEMA_VERSION`]; an existing store's stamp is checked. A mismatch (or an absent stamp on
    /// an existing store) is a hard [`StoreError::SchemaMismatch`] — unless `wipe_on_schema_mismatch`,
    /// which destroys and recreates the store, then stamps the fresh one. CF-set changes are caught
    /// independently by `open_cf_descriptors` failing to open, backstopping the version check.
    pub fn open(config: &StoreConfig) -> Result<Self, StoreError> {
        let db_opts = db_options(config);

        if config.wipe_on_start && config.path.exists() {
            destroy_db(&db_opts, &config.path)?;
        }

        let mut path_existed = config.path.exists();
        loop {
            let store = Self::open_inner(config, &db_opts)?;
            match store.check_schema(path_existed, config.wipe_on_schema_mismatch)? {
                SchemaCheck::Ok => return Ok(store),
                SchemaCheck::WipeAndRetry => {
                    // Drop the handle before destroy: RocksDB cannot destroy an open DB.
                    drop(store);
                    counter!(STORE_SCHEMA_MISMATCH_WIPES_TOTAL).increment(1);
                    warn!(
                        path = ?config.path,
                        expected = STORE_SCHEMA_VERSION,
                        "store schema mismatch with wipe-on-mismatch set: destroying and recreating",
                    );
                    destroy_db(&db_opts, &config.path)?;
                    // The recreated store is fresh, so the retry stamps it rather than re-checking.
                    path_existed = false;
                }
            }
        }
    }

    /// Open the DB handle without the schema guard. Shared by the first open and the post-wipe reopen.
    fn open_inner(config: &StoreConfig, db_opts: &Options) -> Result<Self, StoreError> {
        let cache = Cache::new_lru_cache(config.block_cache_bytes);
        let descriptors = column_families::descriptors(config, &cache);
        let db = DBWithThreadMode::<SingleThreaded>::open_cf_descriptors(
            db_opts,
            &config.path,
            descriptors,
        )
        .map_err(|source| {
            counter!(STORE_ERRORS_TOTAL, "op" => OP_OPEN).increment(1);
            StoreError::Open {
                path: config.path.clone(),
                source,
            }
        })?;

        Ok(Self {
            db: Arc::new(db),
            db_opts: Arc::new(db_opts.clone()),
            // Floor at 1: `next % ratio` must not divide by zero.
            read_sample_ratio: config.read_sample_ratio.max(1),
        })
    }

    /// Compare the `cf_meta` schema stamp against [`STORE_SCHEMA_VERSION`]. A fresh store (one that
    /// did not exist before this open) is stamped and passes; an existing store must match. On
    /// mismatch, either fail typed or signal a wipe-and-retry per `wipe_on_schema_mismatch`.
    fn check_schema(
        &self,
        path_existed: bool,
        wipe_on_schema_mismatch: bool,
    ) -> Result<SchemaCheck, StoreError> {
        if !path_existed {
            self.stamp_schema_version()?;
            return Ok(SchemaCheck::Ok);
        }
        let found = self
            .get(Cf::Meta, META_SCHEMA_VERSION.0)?
            .and_then(|bytes| {
                bytes
                    .get(0..4)
                    .map(|b| u32::from_be_bytes([b[0], b[1], b[2], b[3]]))
            });
        if found == Some(STORE_SCHEMA_VERSION) {
            Ok(SchemaCheck::Ok)
        } else if wipe_on_schema_mismatch {
            Ok(SchemaCheck::WipeAndRetry)
        } else {
            Err(StoreError::SchemaMismatch {
                found,
                expected: STORE_SCHEMA_VERSION,
            })
        }
    }

    /// Stamp `cf_meta[b"schema_version"]` with the current schema version (big-endian `u32`).
    fn stamp_schema_version(&self) -> Result<(), StoreError> {
        self.write_batch(|batch| {
            batch.put::<Meta>(&META_SCHEMA_VERSION, &STORE_SCHEMA_VERSION.to_be_bytes());
        })
    }

    /// Read a raw value from any CF.
    pub fn get(&self, cf: Cf, key: &[u8]) -> Result<Option<Vec<u8>>, StoreError> {
        let handle = self.cf(cf)?;
        // Sample 1-in-N; unsampled reads skip even `Instant::now()`. The counter below stays exact.
        let started = should_sample_read(self.read_sample_ratio).then(Instant::now);
        let result = self.db.get_cf(handle, key);
        if let Some(started) = started {
            histogram!(STORE_READ_DURATION_SECONDS, "op" => OP_GET)
                .record(started.elapsed().as_secs_f64());
        }
        counter!(STORE_READS_TOTAL, "op" => OP_GET).increment(1);
        result.map_err(|source| {
            counter!(STORE_ERRORS_TOTAL, "op" => OP_GET).increment(1);
            StoreError::Backend { op: OP_GET, source }
        })
    }

    pub fn get_behavioral(&self, key: &BehavioralKey) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Behavioral, &key.encode())
    }

    /// Batch-read several `cf_behavioral` values in one call, preserving input order.
    pub fn multi_get_behavioral(
        &self,
        keys: &[BehavioralKey],
    ) -> Result<Vec<Option<Vec<u8>>>, StoreError> {
        // An empty batch is not a read: skip it so it records no phantom read-latency sample.
        if keys.is_empty() {
            return Ok(Vec::new());
        }
        let handle = self.cf(Cf::Behavioral)?;
        let encoded: Vec<_> = keys.iter().map(BehavioralKey::encode).collect();
        let started = Instant::now();
        let results = self
            .db
            .multi_get_cf(encoded.iter().map(|key| (handle, key.as_slice())));
        record_multi_get(started, keys.len());
        results
            .into_iter()
            .map(|result| {
                result.map_err(|source| {
                    counter!(STORE_ERRORS_TOTAL, "op" => OP_MULTI_GET).increment(1);
                    StoreError::Backend {
                        op: OP_MULTI_GET,
                        source,
                    }
                })
            })
            .collect()
    }

    /// Point-read one person's `cf_person_records` value as raw bytes. Decoding into a
    /// [`PersonRecord`](crate::stage1::PersonRecord) lives with the caller.
    pub fn get_person_record(&self, key: &PersonRecordKey) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::PersonRecords, &key.encode())
    }

    /// Read one event's full state snapshot in a single mixed-CF `multi_get`: the `behavioral` keys
    /// (in order) plus, when `record` is given, the person's `cf_person_records` key as the final
    /// lookup.
    ///
    /// The result preserves order: `behavioral[i]` corresponds to the i-th requested behavioral key,
    /// and `record` is `Some(_)` iff a record key was requested (`Some(None)` = requested but absent).
    /// An empty behavioral set with no record key reads nothing.
    pub fn read_event_snapshot(
        &self,
        behavioral: &[BehavioralKey],
        record: Option<&PersonRecordKey>,
    ) -> Result<EventSnapshotRaw, StoreError> {
        // Nothing to read: skip so no phantom read-latency sample is recorded.
        if behavioral.is_empty() && record.is_none() {
            return Ok(EventSnapshotRaw {
                behavioral: Vec::new(),
                record: None,
            });
        }

        let behavioral_handle = self.cf(Cf::Behavioral)?;
        let behavioral_encoded: Vec<_> = behavioral.iter().map(BehavioralKey::encode).collect();

        // Behavioral handles first, the record handle last; `multi_get_cf` preserves this order, so the
        // record's result is the trailing slot.
        let mut pairs: Vec<(&ColumnFamily, &[u8])> = behavioral_encoded
            .iter()
            .map(|key| (behavioral_handle, key.as_slice()))
            .collect();

        let record_encoded = record.map(PersonRecordKey::encode);
        if let Some(encoded) = record_encoded.as_ref() {
            let record_handle = self.cf(Cf::PersonRecords)?;
            pairs.push((record_handle, encoded.as_slice()));
        }

        let started = Instant::now();
        let results = self.db.multi_get_cf(pairs);
        record_multi_get(started, results.len());

        let mut decoded: Vec<Option<Vec<u8>>> = Vec::with_capacity(results.len());
        for result in results {
            decoded.push(result.map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_MULTI_GET).increment(1);
                StoreError::Backend {
                    op: OP_MULTI_GET,
                    source,
                }
            })?);
        }

        let record_slot = if record.is_some() {
            Some(
                decoded
                    .pop()
                    .expect("a requested record key yields a result slot"),
            )
        } else {
            None
        };

        Ok(EventSnapshotRaw {
            behavioral: decoded,
            record: record_slot,
        })
    }

    pub fn get_stage2(&self, key: &Stage2Key) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Stage2, &key.encode())
    }

    /// Batch-read several `cf_stage2` values in one call, preserving input order.
    pub fn multi_get_stage2(&self, keys: &[Stage2Key]) -> Result<Vec<Option<Vec<u8>>>, StoreError> {
        // An empty batch is not a read: skip it so it records no phantom read-latency sample.
        if keys.is_empty() {
            return Ok(Vec::new());
        }
        let handle = self.cf(Cf::Stage2)?;
        let encoded: Vec<_> = keys.iter().map(Stage2Key::encode).collect();
        let started = Instant::now();
        let results = self
            .db
            .multi_get_cf(encoded.iter().map(|key| (handle, key.as_slice())));
        record_multi_get(started, keys.len());
        results
            .into_iter()
            .map(|result| {
                result.map_err(|source| {
                    counter!(STORE_ERRORS_TOTAL, "op" => OP_MULTI_GET).increment(1);
                    StoreError::Backend {
                        op: OP_MULTI_GET,
                        source,
                    }
                })
            })
            .collect()
    }

    /// Apply writes across CFs in one atomic `WriteBatch`.
    pub fn write_batch<F>(&self, build: F) -> Result<(), StoreError>
    where
        F: FnOnce(&mut BatchBuilder<'_>),
    {
        let mut builder = BatchBuilder {
            batch: WriteBatch::default(),
            behavioral: self.cf(Cf::Behavioral)?,
            person_records: self.cf(Cf::PersonRecords)?,
            stage2: self.cf(Cf::Stage2)?,
            merge_drains_applied: self.cf(Cf::MergeDrainsApplied)?,
            pending_transfers: self.cf(Cf::PendingTransfers)?,
            merge_applied: self.cf(Cf::MergeApplied)?,
            merge_tombstones: self.cf(Cf::MergeTombstones)?,
            meta: self.cf(Cf::Meta)?,
        };
        build(&mut builder);
        self.commit(builder.batch, OP_WRITE_BATCH)
    }

    /// Replay an owned [`StagedBatch`] into one atomic `WriteBatch`, in staging order, and commit it.
    ///
    /// This is the owned counterpart to [`Self::write_batch`]: the same operations staged either way
    /// produce identical writes. It goes through the same commit funnel with the same op label, so
    /// metrics do not distinguish the two paths.
    pub fn apply(&self, staged: &StagedBatch) -> Result<(), StoreError> {
        let mut batch = WriteBatch::default();
        for op in staged.ops() {
            match op {
                StagedOp::Put { cf, key, value } => {
                    batch.put_cf(self.cf(*cf)?, key, value);
                }
                StagedOp::Delete { cf, key } => {
                    batch.delete_cf(self.cf(*cf)?, key);
                }
            }
        }
        self.commit(batch, OP_WRITE_BATCH)
    }

    pub fn get_merge_drain_applied(
        &self,
        key: &MergeDrainKey,
    ) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::MergeDrainsApplied, &key.encode())
    }

    pub fn get_pending_transfer(
        &self,
        key: &PendingTransferKey,
    ) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::PendingTransfers, &key.encode())
    }

    pub fn get_merge_applied(&self, key: &MergeAppliedKey) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::MergeApplied, &key.encode())
    }

    pub fn get_tombstone(&self, key: &TombstoneKey) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::MergeTombstones, &key.encode())
    }

    /// Clear one outbox slot once its transfer is acked.
    pub fn clear_pending_transfer(&self, key: &PendingTransferKey) -> Result<(), StoreError> {
        self.write_batch(|batch| batch.delete_pending_transfer(key))
    }

    /// Scan up to `limit` of one partition's `cf_pending_transfers` slice, returning `(key, value)`
    /// in key order, resuming strictly *after* `start_after` (exclusive) when given. The per-tick
    /// redrive passes a bounded `limit` and no cursor; the eager boot redrive paginates with a cursor
    /// to drain the whole outbox (mirrors [`Self::scan_behavioral`] / [`Self::scan_merge_cf`]).
    pub fn scan_pending_transfers(
        &self,
        partition_id: u16,
        start_after: Option<&[u8]>,
        limit: usize,
    ) -> Result<Vec<(PendingTransferKey, Vec<u8>)>, StoreError> {
        let (prefix_start, prefix_end) = keys::partition_range(partition_id);
        let handle = self.cf(Cf::PendingTransfers)?;

        // Resume after the cursor when it falls inside this partition, else at the prefix start.
        let begin: Vec<u8> = match start_after {
            Some(cursor) if cursor >= prefix_start.as_slice() && cursor < prefix_end.as_slice() => {
                successor(cursor)
            }
            _ => prefix_start.clone(),
        };

        let mut read_opts = ReadOptions::default();
        read_opts.set_iterate_upper_bound(prefix_end);
        let iter = self.db.iterator_cf_opt(
            handle,
            read_opts,
            IteratorMode::From(&begin, Direction::Forward),
        );

        let mut out = Vec::with_capacity(limit.min(1024));
        for item in iter {
            if out.len() == limit {
                break;
            }
            let (key_bytes, value) = item.map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_SCAN).increment(1);
                StoreError::Backend {
                    op: OP_SCAN,
                    source,
                }
            })?;
            out.push((PendingTransferKey::decode(&key_bytes)?, value.to_vec()));
        }
        Ok(out)
    }

    /// Scan up to `limit` raw `(key, value)` pairs from one partition's slice of a CF, in key order,
    /// resuming strictly *after* `start_after` (exclusive) when given.
    ///
    /// Returns raw bytes (not typed keys/values) so each GC handler can decode the CF's own value
    /// shape and keep the last key as its resume cursor. The mechanics are CF-generic: the merge-CF GC
    /// passes the three time-stamped merge CFs (`DrainStamp` / `ApplyStamp` / `Tombstone`, see
    /// [`crate::merge::gc`]), and the `cf_stage2` orphan GC passes `Cf::Stage2` (see
    /// [`crate::workers::stage2_gc`]). `cf_pending_transfers` is the redrive's outbox and no GC path
    /// passes it.
    pub fn scan_merge_cf(
        &self,
        cf: Cf,
        partition_id: u16,
        start_after: Option<&[u8]>,
        limit: usize,
    ) -> Result<Vec<RawKv>, StoreError> {
        let (prefix_start, prefix_end) = keys::partition_range(partition_id);
        let handle = self.cf(cf)?;

        // Resume after the cursor when it falls inside this partition, else at the prefix start.
        // `successor` is the smallest key strictly greater than the cursor, turning the inclusive
        // `IteratorMode::From(_, Forward)` seek into an exclusive resume.
        let begin: Vec<u8> = match start_after {
            Some(cursor) if cursor >= prefix_start.as_slice() && cursor < prefix_end.as_slice() => {
                successor(cursor)
            }
            _ => prefix_start.clone(),
        };

        let mut read_opts = ReadOptions::default();
        read_opts.set_iterate_upper_bound(prefix_end);
        let iter = self.db.iterator_cf_opt(
            handle,
            read_opts,
            IteratorMode::From(&begin, Direction::Forward),
        );

        let mut out = Vec::with_capacity(limit.min(1024));
        for item in iter {
            if out.len() == limit {
                break;
            }
            let (key_bytes, value) = item.map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_SCAN).increment(1);
                StoreError::Backend {
                    op: OP_SCAN,
                    source,
                }
            })?;
            out.push((key_bytes.to_vec(), value.to_vec()));
        }
        Ok(out)
    }

    /// Reclaim all state for one partition on rebalance. Non-partitioned CFs (`cf_meta`) are skipped:
    /// their short literal keys collide with an arbitrary partition's byte range, so a range delete
    /// would wipe store-wide guards like the schema stamp.
    pub fn delete_partition(&self, partition_id: u16) -> Result<(), StoreError> {
        let (start, end) = keys::partition_range(partition_id);
        let mut batch = WriteBatch::default();
        for cf in Cf::ALL {
            if !cf.partitioned() {
                continue;
            }
            let handle = self.cf(cf)?;
            batch.delete_range_cf(handle, start.as_slice(), end.as_slice());
        }
        self.commit(batch, OP_DELETE_PARTITION)
    }

    /// Flush all CF memtables to SST. Checkpoint path and tests only.
    pub fn flush(&self) -> Result<(), StoreError> {
        let handles: Vec<&ColumnFamily> = Cf::ALL
            .iter()
            .map(|&cf| self.cf(cf))
            .collect::<Result<_, _>>()?;
        let mut flush_opts = FlushOptions::default();
        flush_opts.set_wait(true);
        self.db
            .flush_cfs_opt(&handles, &flush_opts)
            .map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_FLUSH).increment(1);
                StoreError::Backend {
                    op: OP_FLUSH,
                    source,
                }
            })
    }

    /// Synchronously fsync the WAL, making every write so far durable. The hot path writes with an
    /// async WAL (`set_sync(false)`), so without this a committed Kafka offset could outrun the durable
    /// state on a hard crash; callers fsync before every offset commit to keep `committed <= durable`.
    /// On error the caller skips the commit (fail-stop).
    pub fn flush_wal_sync(&self) -> Result<(), StoreError> {
        let started = Instant::now();
        let result = self.db.flush_wal(true);
        histogram!(WAL_FSYNC_DURATION_SECONDS).record(started.elapsed().as_secs_f64());
        result.map_err(|source| {
            counter!(WAL_FSYNC_ERRORS_TOTAL).increment(1);
            StoreError::Backend {
                op: OP_FLUSH_WAL,
                source,
            }
        })
    }

    /// Take a frozen, point-in-time RocksDB checkpoint of the whole DB into `path`. RocksDB
    /// hard-links the immutable SSTs into `path`, so `path` must be on the **same filesystem** as
    /// the store path and **must not be a child** of it (RocksDB refuses a nested checkpoint path).
    pub fn create_checkpoint(&self, path: &Path) -> Result<(), StoreError> {
        let started = Instant::now();
        let result = rocksdb::checkpoint::Checkpoint::new(&self.db)
            .and_then(|cp| cp.create_checkpoint(path));
        histogram!(CHECKPOINT_DURATION_SECONDS).record(started.elapsed().as_secs_f64());
        result.map_err(|source| {
            counter!(STORE_ERRORS_TOTAL, "op" => OP_CHECKPOINT).increment(1);
            StoreError::Backend {
                op: OP_CHECKPOINT,
                source,
            }
        })
    }

    /// Scan up to `limit` of one partition's `cf_behavioral` slice as `(BehavioralKey, raw_value)` in
    /// key order, resuming strictly after `start_after` when given. The value stays raw so the caller
    /// decodes the [`StatefulRecord`](crate::stage1::StatefulRecord) (and owns the decode-error metric)
    /// and the resume cursor is the last scanned key.
    ///
    /// This is a partition-wide scan that crosses many 26-byte person prefixes. `cf_behavioral` has a
    /// fixed-prefix extractor, so the iterator defaults to prefix-seek mode and would silently stop at
    /// the first person boundary; `set_total_order_seek(true)` forces a full-order iteration across all
    /// prefixes.
    pub fn scan_behavioral(
        &self,
        partition_id: u16,
        start_after: Option<&[u8]>,
        limit: usize,
    ) -> Result<Vec<(BehavioralKey, Vec<u8>)>, StoreError> {
        let (prefix_start, prefix_end) = keys::partition_range(partition_id);
        let handle = self.cf(Cf::Behavioral)?;

        // Resume after the cursor when it falls inside this partition, else at the prefix start.
        let begin: Vec<u8> = match start_after {
            Some(cursor) if cursor >= prefix_start.as_slice() && cursor < prefix_end.as_slice() => {
                successor(cursor)
            }
            _ => prefix_start.clone(),
        };

        let mut read_opts = ReadOptions::default();
        read_opts.set_iterate_upper_bound(prefix_end);
        read_opts.set_total_order_seek(true);
        let iter = self.db.iterator_cf_opt(
            handle,
            read_opts,
            IteratorMode::From(&begin, Direction::Forward),
        );

        let mut out = Vec::with_capacity(limit.min(1024));
        for item in iter {
            if out.len() == limit {
                break;
            }
            let (key_bytes, value) = item.map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_SCAN).increment(1);
                StoreError::Backend {
                    op: OP_SCAN,
                    source,
                }
            })?;
            out.push((BehavioralKey::decode(&key_bytes)?, value.to_vec()));
        }
        Ok(out)
    }

    /// Scan one person's whole `cf_behavioral` slice as `(BehavioralKey, raw_value)` in lsk order.
    ///
    /// Bounded to the person's 26-byte prefix by both the iterate-upper-bound (the prefix successor)
    /// and `set_prefix_same_as_start(true)`, which pins the iterator to the seek key's prefix so it can
    /// never leak into an adjacent person's rows. Used by the merge drain to enumerate P_old's leaves.
    pub fn scan_behavioral_prefix(
        &self,
        prefix: PersonPrefix,
    ) -> Result<Vec<(BehavioralKey, Vec<u8>)>, StoreError> {
        let (start, end) = prefix.scan_range();
        let handle = self.cf(Cf::Behavioral)?;

        let mut read_opts = ReadOptions::default();
        read_opts.set_iterate_upper_bound(end);
        read_opts.set_prefix_same_as_start(true);
        let iter = self.db.iterator_cf_opt(
            handle,
            read_opts,
            IteratorMode::From(&start, Direction::Forward),
        );

        let mut out = Vec::new();
        for item in iter {
            let (key_bytes, value) = item.map_err(|source| {
                counter!(STORE_ERRORS_TOTAL, "op" => OP_SCAN).increment(1);
                StoreError::Backend {
                    op: OP_SCAN,
                    source,
                }
            })?;
            out.push((BehavioralKey::decode(&key_bytes)?, value.to_vec()));
        }
        Ok(out)
    }

    /// Snapshot the block-cache tickers and per-CF size properties. Tickers are cumulative since store
    /// open and read 0 when `statistics_enabled` is off; per-CF properties read 0 when RocksDB has no
    /// estimate yet (a fresh, never-written CF).
    pub fn stats_snapshot(&self) -> StoreStats {
        let ticker = |t: Ticker| self.db_opts.get_ticker_count(t);
        StoreStats {
            block_cache_hits: ticker(Ticker::BlockCacheHit),
            block_cache_misses: ticker(Ticker::BlockCacheMiss),
            block_cache_data_hits: ticker(Ticker::BlockCacheDataHit),
            block_cache_data_misses: ticker(Ticker::BlockCacheDataMiss),
            block_cache_index_hits: ticker(Ticker::BlockCacheIndexHit),
            block_cache_index_misses: ticker(Ticker::BlockCacheIndexMiss),
            block_cache_filter_hits: ticker(Ticker::BlockCacheFilterHit),
            block_cache_filter_misses: ticker(Ticker::BlockCacheFilterMiss),
            bloom_filter_useful: ticker(Ticker::BloomFilterUseful),
            // The block cache is shared across every CF, so any CF handle reports the same usage.
            block_cache_usage_bytes: self
                .cf_property_u64(Cf::Behavioral, properties::BLOCK_CACHE_USAGE),
            per_cf: Cf::ALL
                .iter()
                .map(|&cf| CfStats {
                    cf,
                    sst_bytes: self.cf_property_u64(cf, properties::TOTAL_SST_FILES_SIZE),
                    live_data_bytes: self.cf_property_u64(cf, properties::ESTIMATE_LIVE_DATA_SIZE),
                    num_keys: self.cf_property_u64(cf, properties::ESTIMATE_NUM_KEYS),
                })
                .collect(),
        }
    }

    /// Read an integer RocksDB property for one CF; an absent handle, error, or missing estimate all
    /// fold to 0.
    fn cf_property_u64(&self, cf: Cf, name: &PropName) -> u64 {
        let Ok(handle) = self.cf(cf) else {
            return 0;
        };
        self.db
            .property_int_value_cf(handle, name)
            .ok()
            .flatten()
            .unwrap_or(0)
    }

    fn cf(&self, cf: Cf) -> Result<&ColumnFamily, StoreError> {
        self.db
            .cf_handle(cf.as_str())
            .ok_or(StoreError::UnknownColumnFamily(cf.as_str()))
    }

    fn commit(&self, batch: WriteBatch, op: &'static str) -> Result<(), StoreError> {
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(false);

        let started = Instant::now();
        let result = self.db.write_opt(batch, &write_opts);
        histogram!(STORE_WRITE_DURATION_SECONDS, "op" => op)
            .record(started.elapsed().as_secs_f64());

        match result {
            Ok(()) => {
                counter!(STORE_WRITE_BATCH_TOTAL, "op" => op).increment(1);
                Ok(())
            }
            Err(source) => {
                counter!(STORE_ERRORS_TOTAL, "op" => op).increment(1);
                Err(StoreError::Backend { op, source })
            }
        }
    }
}

/// Snapshot of the store's cache tickers and per-CF sizes, produced by
/// [`CohortStore::stats_snapshot`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoreStats {
    pub block_cache_hits: u64,
    pub block_cache_misses: u64,
    pub block_cache_data_hits: u64,
    pub block_cache_data_misses: u64,
    pub block_cache_index_hits: u64,
    pub block_cache_index_misses: u64,
    pub block_cache_filter_hits: u64,
    pub block_cache_filter_misses: u64,
    /// Point lookups the bloom filter let skip a data-block read.
    pub bloom_filter_useful: u64,
    pub block_cache_usage_bytes: u64,
    /// One entry per [`Cf::ALL`].
    pub per_cf: Vec<CfStats>,
}

/// Per-column-family size properties. See [`StoreStats`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CfStats {
    pub cf: Cf,
    pub sst_bytes: u64,
    /// Estimated live (non-tombstone) data bytes.
    pub live_data_bytes: u64,
    /// Estimated key count (memtable-inclusive, so non-zero before a flush).
    pub num_keys: u64,
}

/// The raw bytes of one event's state snapshot from a single mixed-CF `multi_get`, produced by
/// [`CohortStore::read_event_snapshot`]. Decoding lives with the caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventSnapshotRaw {
    /// One slot per requested behavioral key, in request order; `None` = absent row.
    pub behavioral: Vec<Option<Vec<u8>>>,
    /// The person-record slot: outer `None` = no record key was requested; `Some(None)` = requested
    /// but absent; `Some(Some(bytes))` = present.
    pub record: Option<Option<Vec<u8>>>,
}

/// Typed builder for a multi-CF [`WriteBatch`].
pub struct BatchBuilder<'db> {
    batch: WriteBatch,
    behavioral: &'db ColumnFamily,
    person_records: &'db ColumnFamily,
    stage2: &'db ColumnFamily,
    merge_drains_applied: &'db ColumnFamily,
    pending_transfers: &'db ColumnFamily,
    merge_applied: &'db ColumnFamily,
    merge_tombstones: &'db ColumnFamily,
    meta: &'db ColumnFamily,
}

impl<'db> BatchBuilder<'db> {
    /// The held handle for one CF, returned at the store's `'db` lifetime rather than `&self` so it
    /// does not alias the `&mut self.batch` callers immediately take.
    fn handle(&self, cf: Cf) -> &'db ColumnFamily {
        match cf {
            Cf::Behavioral => self.behavioral,
            Cf::PersonRecords => self.person_records,
            Cf::Stage2 => self.stage2,
            Cf::MergeDrainsApplied => self.merge_drains_applied,
            Cf::PendingTransfers => self.pending_transfers,
            Cf::MergeApplied => self.merge_applied,
            Cf::MergeTombstones => self.merge_tombstones,
            Cf::Meta => self.meta,
        }
    }

    /// Put a typed key/value into its keyspace's CF. The [`Keyspace`] binding routes to the right CF,
    /// so a key cannot be written to the wrong column family.
    pub fn put<K: Keyspace>(&mut self, key: &K::Key, value: &[u8]) {
        let handle = self.handle(K::CF);
        self.batch.put_cf(handle, K::encode(key), value);
    }

    /// Delete a typed key from its keyspace's CF.
    pub fn delete<K: Keyspace>(&mut self, key: &K::Key) {
        let handle = self.handle(K::CF);
        self.batch.delete_cf(handle, K::encode(key));
    }

    /// Range-delete one person's whole `cf_behavioral` slice in a single tombstone, reclaiming every
    /// leaf under the person prefix at once (used when a merge drains P_old's state).
    pub fn delete_behavioral_prefix(&mut self, prefix: &PersonPrefix) {
        let (start, end) = prefix.scan_range();
        self.batch
            .delete_range_cf(self.behavioral, start.as_slice(), end.as_slice());
    }

    pub fn put_stage2(&mut self, key: &Stage2Key, value: &[u8]) {
        self.batch.put_cf(self.stage2, key.encode(), value);
    }

    pub fn delete_stage2(&mut self, key: &Stage2Key) {
        self.batch.delete_cf(self.stage2, key.encode());
    }

    /// Stage the Phase 1 idempotence marker for a drained merge message.
    pub fn put_merge_drain_applied(&mut self, key: &MergeDrainKey, value: &[u8]) {
        self.batch
            .put_cf(self.merge_drains_applied, key.encode(), value);
    }

    /// GC-delete one expired Phase 1 idempotence marker.
    pub fn delete_merge_drain_applied(&mut self, key: &MergeDrainKey) {
        self.batch
            .delete_cf(self.merge_drains_applied, key.encode());
    }

    /// Stage a packaged merge into the outbox.
    pub fn put_pending_transfer(&mut self, key: &PendingTransferKey, value: &[u8]) {
        self.batch
            .put_cf(self.pending_transfers, key.encode(), value);
    }

    /// Clear an outbox slot once its transfer is acked.
    pub fn delete_pending_transfer(&mut self, key: &PendingTransferKey) {
        self.batch.delete_cf(self.pending_transfers, key.encode());
    }

    /// Stage the Phase 2 idempotence marker for an applied transfer message.
    pub fn put_merge_applied(&mut self, key: &MergeAppliedKey, value: &[u8]) {
        self.batch.put_cf(self.merge_applied, key.encode(), value);
    }

    /// GC-delete one expired Phase 2 idempotence marker.
    pub fn delete_merge_applied(&mut self, key: &MergeAppliedKey) {
        self.batch.delete_cf(self.merge_applied, key.encode());
    }

    /// Stage the redirect tombstone for a merged-away person.
    pub fn put_tombstone(&mut self, key: &TombstoneKey, value: &[u8]) {
        self.batch
            .put_cf(self.merge_tombstones, key.encode(), value);
    }

    /// GC-delete one expired redirect tombstone.
    pub fn delete_tombstone(&mut self, key: &TombstoneKey) {
        self.batch.delete_cf(self.merge_tombstones, key.encode());
    }

    /// Raw put by pre-encoded key bytes. Restricted to [`OpaqueCf`].
    pub fn put_raw(&mut self, cf: OpaqueCf, key: &[u8], value: &[u8]) {
        self.batch.put_cf(self.handle(cf.cf()), key, value);
    }
}

thread_local! {
    /// Thread-local to avoid cross-worker contention; each worker samples independently (~1-in-N).
    static READ_SAMPLE_COUNTER: Cell<u32> = const { Cell::new(0) };
}

/// Fires once per `ratio` calls. Count-based, so sampled quantiles stay unbiased; `ratio >= 1`.
fn should_sample_read(ratio: u32) -> bool {
    READ_SAMPLE_COUNTER.with(|counter| {
        let next = counter.get().wrapping_add(1);
        counter.set(next);
        next % ratio == 0
    })
}

/// Records one duration sample and `key_count` logical reads for a `multi_get` (a batch touches
/// `key_count` keys).
fn record_multi_get(started: Instant, key_count: usize) {
    histogram!(STORE_READ_DURATION_SECONDS, "op" => OP_MULTI_GET)
        .record(started.elapsed().as_secs_f64());
    counter!(STORE_READS_TOTAL, "op" => OP_MULTI_GET).increment(key_count as u64);
}

/// The smallest byte string strictly greater than `key`: `key` with a trailing `0x00` appended.
/// Used to turn an inclusive `IteratorMode::From` seek into an exclusive resume past a cursor.
fn successor(key: &[u8]) -> Vec<u8> {
    let mut next = Vec::with_capacity(key.len() + 1);
    next.extend_from_slice(key);
    next.push(0x00);
    next
}

/// Outcome of the open-time schema-version check.
enum SchemaCheck {
    /// The stamp matched (or a fresh store was just stamped).
    Ok,
    /// A mismatch under `wipe_on_schema_mismatch`: the caller destroys and reopens fresh.
    WipeAndRetry,
}

/// Destroy the store at `path`, counting a metric on failure. Requires no open handle.
fn destroy_db(db_opts: &Options, path: &Path) -> Result<(), StoreError> {
    DBWithThreadMode::<SingleThreaded>::destroy(db_opts, path).map_err(|source| {
        counter!(STORE_ERRORS_TOTAL, "op" => OP_DESTROY).increment(1);
        StoreError::Open {
            path: path.to_path_buf(),
            source,
        }
    })
}

fn db_options(config: &StoreConfig) -> Options {
    let mut opts = Options::default();
    opts.create_if_missing(config.create_if_missing);
    opts.create_missing_column_families(true);
    opts.set_atomic_flush(true);
    opts.set_max_open_files(config.max_open_files);
    opts.set_allow_mmap_reads(false);
    opts.set_allow_mmap_writes(false);
    if config.statistics_enabled {
        // `ExceptHistogramOrTimers` keeps the cheap cache tickers and drops the expensive per-op
        // histograms and timers.
        opts.enable_statistics();
        opts.set_statistics_level(StatsLevel::ExceptHistogramOrTimers);
    }
    if config.max_background_jobs > 0 {
        opts.set_max_background_jobs(config.max_background_jobs);
    }
    opts
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use uuid::Uuid;

    use super::super::keyspace::{Behavioral, PersonRecords};
    use crate::stage1::key::LeafStateKey;

    fn behavioral_key() -> BehavioralKey {
        BehavioralKey::new(3, 7, Uuid::from_u128(1), LeafStateKey([0xAB; 16]))
    }

    fn record_key(partition: u16, person: u128) -> PersonRecordKey {
        PersonRecordKey::new(partition, 7, Uuid::from_u128(person))
    }

    #[test]
    fn wipe_on_start_clears_existing_state_and_is_a_noop_when_off() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        let key = behavioral_key();

        // Seed a value, then close the database (drop the only handle).
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            store
                .write_batch(|b| b.put::<Behavioral>(&key, b"state"))
                .unwrap();
            assert_eq!(
                store.get_behavioral(&key).unwrap().as_deref(),
                Some(b"state".as_slice()),
            );
        }

        // Reopen without wiping: the value survives a restart.
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                wipe_on_start: false,
                ..StoreConfig::default()
            })
            .unwrap();
            assert_eq!(
                store.get_behavioral(&key).unwrap().as_deref(),
                Some(b"state".as_slice()),
            );
        }

        // Reopen with wiping: the previous owner's state is gone.
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                wipe_on_start: true,
                ..StoreConfig::default()
            })
            .unwrap();
            assert_eq!(store.get_behavioral(&key).unwrap(), None);
        }
    }

    #[test]
    fn wipe_on_start_opens_cleanly_when_no_store_exists_yet() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("fresh"),
            wipe_on_start: true,
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(store.get_behavioral(&behavioral_key()).unwrap(), None);
    }

    #[test]
    fn fresh_store_stamps_the_schema_version_and_a_reopen_matches() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            assert_eq!(
                store
                    .get(Cf::Meta, META_SCHEMA_VERSION.0)
                    .unwrap()
                    .as_deref(),
                Some(STORE_SCHEMA_VERSION.to_be_bytes().as_slice()),
                "a fresh store stamps the current schema version",
            );
        }
        // A reopen matches the stamp and opens cleanly.
        CohortStore::open(&StoreConfig {
            path,
            wipe_on_start: false,
            ..StoreConfig::default()
        })
        .unwrap();
    }

    #[test]
    fn a_version_mismatch_fails_typed_and_the_wipe_flag_recreates_empty() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        let key = behavioral_key();

        // Seed a store and corrupt its stamp to a bogus version.
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            store
                .write_batch(|b| b.put::<Behavioral>(&key, b"state"))
                .unwrap();
            store
                .write_batch(|b| b.put::<Meta>(&META_SCHEMA_VERSION, &999u32.to_be_bytes()))
                .unwrap();
        }

        // Without the wipe flag, a mismatch is a typed hard error and the store is untouched.
        // (`CohortStore` is not `Debug`, so match the `Result` rather than `unwrap_err`.)
        let result = CohortStore::open(&StoreConfig {
            path: path.clone(),
            wipe_on_start: false,
            ..StoreConfig::default()
        });
        assert!(
            matches!(
                result,
                Err(StoreError::SchemaMismatch {
                    found: Some(999),
                    expected,
                }) if expected == STORE_SCHEMA_VERSION
            ),
            "expected a typed schema mismatch",
        );

        // With the wipe flag, the store is destroyed, recreated, and re-stamped — the old row is gone.
        let store = CohortStore::open(&StoreConfig {
            path,
            wipe_on_start: false,
            wipe_on_schema_mismatch: true,
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(
            store.get_behavioral(&key).unwrap(),
            None,
            "wipe-on-mismatch recreates an empty store",
        );
        assert_eq!(
            store
                .get(Cf::Meta, META_SCHEMA_VERSION.0)
                .unwrap()
                .as_deref(),
            Some(STORE_SCHEMA_VERSION.to_be_bytes().as_slice()),
            "the recreated store is re-stamped with the current version",
        );
    }

    #[test]
    fn multi_get_behavioral_preserves_order_and_reports_absent_keys() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let present = |person: u128, lsk: u8| {
            BehavioralKey::new(3, 7, Uuid::from_u128(person), LeafStateKey([lsk; 16]))
        };
        let a = present(1, 0xA0);
        let b = present(2, 0xB0);
        let absent = present(9, 0xFF);
        store
            .write_batch(|batch| {
                batch.put::<Behavioral>(&a, b"alpha");
                batch.put::<Behavioral>(&b, b"bravo");
            })
            .unwrap();

        // Order: present, absent, present — the absent key must surface as a `None` hole, not shift
        // the others.
        let results = store.multi_get_behavioral(&[a, absent, b]).unwrap();
        assert_eq!(results.len(), 3);
        assert_eq!(results[0].as_deref(), Some(b"alpha".as_slice()));
        assert_eq!(results[1], None);
        assert_eq!(results[2].as_deref(), Some(b"bravo".as_slice()));

        assert!(
            store.multi_get_behavioral(&[]).unwrap().is_empty(),
            "an empty key set reads no values",
        );
    }

    #[test]
    fn person_record_get_round_trips_through_its_cf() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let key = record_key(3, 1);
        assert_eq!(
            store.get_person_record(&key).unwrap(),
            None,
            "absent before write"
        );
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, b"record-bytes"))
            .unwrap();
        assert_eq!(
            store.get_person_record(&key).unwrap().as_deref(),
            Some(b"record-bytes".as_slice()),
        );
    }

    #[test]
    fn read_event_snapshot_aligns_behavioral_hits_misses_and_the_record_slot() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let b = |person: u128, lsk: u8| {
            BehavioralKey::new(3, 7, Uuid::from_u128(person), LeafStateKey([lsk; 16]))
        };
        let present_a = b(1, 0xA0);
        let present_b = b(1, 0xB0);
        let absent = b(9, 0xFF);
        let record = record_key(3, 1);
        store
            .write_batch(|batch| {
                batch.put::<Behavioral>(&present_a, b"alpha");
                batch.put::<Behavioral>(&present_b, b"bravo");
                batch.put::<PersonRecords>(&record, b"rec");
            })
            .unwrap();

        // Behavioral order present/absent/present, plus the record present.
        let snap = store
            .read_event_snapshot(&[present_a, absent, present_b], Some(&record))
            .unwrap();
        assert_eq!(snap.behavioral.len(), 3);
        assert_eq!(snap.behavioral[0].as_deref(), Some(b"alpha".as_slice()));
        assert_eq!(
            snap.behavioral[1], None,
            "the absent behavioral key is a hole"
        );
        assert_eq!(snap.behavioral[2].as_deref(), Some(b"bravo".as_slice()));
        assert_eq!(snap.record, Some(Some(b"rec".to_vec())), "record present");

        // Record requested but absent ⇒ Some(None); behavioral all present.
        let absent_record = record_key(3, 999);
        let snap = store
            .read_event_snapshot(&[present_a], Some(&absent_record))
            .unwrap();
        assert_eq!(snap.behavioral.len(), 1);
        assert_eq!(snap.record, Some(None), "requested but absent record");

        // Record not requested ⇒ outer None; behavioral only.
        let snap = store.read_event_snapshot(&[present_a], None).unwrap();
        assert_eq!(snap.behavioral.len(), 1);
        assert_eq!(snap.record, None, "no record key requested");

        // Record-only (empty behavioral).
        let snap = store.read_event_snapshot(&[], Some(&record)).unwrap();
        assert!(snap.behavioral.is_empty());
        assert_eq!(snap.record, Some(Some(b"rec".to_vec())));

        // Empty both ⇒ no read, empty result.
        let snap = store.read_event_snapshot(&[], None).unwrap();
        assert!(snap.behavioral.is_empty());
        assert_eq!(snap.record, None);
    }

    #[test]
    fn delete_partition_wipes_person_records_for_that_partition_only() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let victim = record_key(5, 1);
        let survivor = record_key(6, 1);
        store
            .write_batch(|batch| {
                batch.put::<PersonRecords>(&victim, b"v");
                batch.put::<PersonRecords>(&survivor, b"s");
            })
            .unwrap();

        store.delete_partition(5).unwrap();
        assert_eq!(
            store.get_person_record(&victim).unwrap(),
            None,
            "partition 5's record is reclaimed",
        );
        assert_eq!(
            store.get_person_record(&survivor).unwrap().as_deref(),
            Some(b"s".as_slice()),
            "partition 6's record is untouched",
        );
    }

    #[test]
    fn multi_get_stage2_preserves_order_and_reports_absent_keys() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let present = |person: u128, cohort: u64| Stage2Key {
            partition_id: 3,
            team_id: 7,
            cohort_id: cohort,
            person_id: Uuid::from_u128(person),
        };
        let a = present(1, 100);
        let b = present(2, 200);
        let absent = present(9, 999);
        store
            .write_batch(|batch| {
                batch.put_stage2(&a, b"alpha");
                batch.put_stage2(&b, b"bravo");
            })
            .unwrap();

        // Order: present, absent, present — the absent key must surface as a `None` hole, not shift
        // the others.
        let results = store.multi_get_stage2(&[a, absent, b]).unwrap();
        assert_eq!(results.len(), 3);
        assert_eq!(results[0].as_deref(), Some(b"alpha".as_slice()));
        assert_eq!(results[1], None);
        assert_eq!(results[2].as_deref(), Some(b"bravo".as_slice()));

        assert!(
            store.multi_get_stage2(&[]).unwrap().is_empty(),
            "an empty key set reads no values",
        );
    }

    #[test]
    fn scan_merge_cf_resumes_after_the_cursor_and_honors_the_limit_and_partition_bounds() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let tombstone_key = |partition_id: u16, person: u128| TombstoneKey {
            partition_id,
            team_id: 7,
            person: Uuid::from_u128(person),
        };

        // Four tombstones in partition 5, one in partition 6 (must never surface for a p=5 scan).
        store
            .write_batch(|batch| {
                for person in 1..=4u128 {
                    batch.put_tombstone(&tombstone_key(5, person), b"v");
                }
                batch.put_tombstone(&tombstone_key(6, 9), b"other-partition");
            })
            .unwrap();

        let page1 = store
            .scan_merge_cf(Cf::MergeTombstones, 5, None, 2)
            .unwrap();
        assert_eq!(page1.len(), 2);
        let decoded: Vec<_> = page1
            .iter()
            .map(|(k, _)| TombstoneKey::decode(k).unwrap().person)
            .collect();
        assert_eq!(
            decoded,
            vec![Uuid::from_u128(1), Uuid::from_u128(2)],
            "key-ordered ascending",
        );

        let cursor = page1.last().unwrap().0.clone();
        let page2 = store
            .scan_merge_cf(Cf::MergeTombstones, 5, Some(&cursor), 10)
            .unwrap();
        let decoded2: Vec<_> = page2
            .iter()
            .map(|(k, _)| TombstoneKey::decode(k).unwrap().person)
            .collect();
        assert_eq!(
            decoded2,
            vec![Uuid::from_u128(3), Uuid::from_u128(4)],
            "resumes past the cursor, never re-emits it, and stays inside partition 5",
        );

        // A cursor at the partition's last key → empty (exhausted), wrapping is the caller's job.
        let last_cursor = page2.last().unwrap().0.clone();
        let exhausted = store
            .scan_merge_cf(Cf::MergeTombstones, 5, Some(&last_cursor), 10)
            .unwrap();
        assert!(exhausted.is_empty(), "no keys past the partition's last");

        // A cursor that is not in this partition falls back to a fresh prefix scan.
        let foreign_cursor = tombstone_key(6, 9).encode().to_vec();
        let fresh = store
            .scan_merge_cf(Cf::MergeTombstones, 5, Some(&foreign_cursor), 10)
            .unwrap();
        assert_eq!(
            fresh.len(),
            4,
            "out-of-partition cursor rescans from the start"
        );
    }

    #[test]
    fn flush_wal_sync_succeeds_and_persists_writes_across_a_reopen() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        let key = behavioral_key();
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            store
                .write_batch(|b| b.put::<Behavioral>(&key, b"durable"))
                .unwrap();
            store.flush_wal_sync().unwrap();
            // A second fsync with nothing new pending is a no-op, not an error.
            store.flush_wal_sync().unwrap();
        }
        let reopened = CohortStore::open(&StoreConfig {
            path,
            wipe_on_start: false,
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(
            reopened.get_behavioral(&key).unwrap().as_deref(),
            Some(b"durable".as_slice()),
        );
    }

    #[test]
    fn create_checkpoint_produces_an_openable_db_with_the_same_state() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        // The checkpoint must be a sibling of the store path, never a child (RocksDB hard-links SSTs).
        let checkpoint = dir.path().join("checkpoint");
        let key = behavioral_key();

        let store = CohortStore::open(&StoreConfig {
            path,
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|b| b.put::<Behavioral>(&key, b"snapshot"))
            .unwrap();
        store.create_checkpoint(&checkpoint).unwrap();

        let restored = CohortStore::open(&StoreConfig {
            path: checkpoint,
            wipe_on_start: false,
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(
            restored.get_behavioral(&key).unwrap().as_deref(),
            Some(b"snapshot".as_slice()),
        );
    }

    // RocksDB's Checkpoint::create_checkpoint creates the destination dir itself and requires
    // the leaf to NOT already exist: the parent must exist, the leaf must not.
    #[test]
    fn create_checkpoint_succeeds_when_only_the_parent_exists_and_the_leaf_does_not() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        let key = behavioral_key();
        store
            .write_batch(|b| b.put::<Behavioral>(&key, b"snapshot"))
            .unwrap();

        // Parent exists, leaf does not — the correct usage.
        let parent = dir.path().join("attempts");
        std::fs::create_dir_all(&parent).unwrap();
        let checkpoint = parent.join("attempt-0");
        store.create_checkpoint(&checkpoint).unwrap();

        let restored = CohortStore::open(&StoreConfig {
            path: checkpoint,
            wipe_on_start: false,
            ..StoreConfig::default()
        })
        .unwrap();
        assert_eq!(
            restored.get_behavioral(&key).unwrap().as_deref(),
            Some(b"snapshot".as_slice()),
        );
    }

    #[test]
    fn create_checkpoint_errors_when_the_destination_dir_already_exists() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        // Pre-create the leaf: RocksDB requires it to not exist.
        let checkpoint = dir.path().join("attempt-0");
        std::fs::create_dir_all(&checkpoint).unwrap();
        let err = store.create_checkpoint(&checkpoint).unwrap_err();
        assert!(
            matches!(err, StoreError::Backend { op, .. } if op == OP_CHECKPOINT),
            "pre-existing checkpoint dir must surface a backend checkpoint error, got: {err}",
        );
    }

    #[test]
    fn scan_behavioral_resumes_after_the_cursor_and_honors_the_limit_and_partition_bounds() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let key = |partition_id: u16, person: u128| {
            BehavioralKey::new(
                partition_id,
                7,
                Uuid::from_u128(person),
                LeafStateKey([0xAB; 16]),
            )
        };

        // Three keys in partition 5, one in partition 6 (must never surface for a p=5 scan).
        store
            .write_batch(|batch| {
                for person in 1..=3u128 {
                    batch.put::<Behavioral>(&key(5, person), format!("v{person}").as_bytes());
                }
                batch.put::<Behavioral>(&key(6, 9), b"other-partition");
            })
            .unwrap();

        let page1 = store.scan_behavioral(5, None, 2).unwrap();
        assert_eq!(page1.len(), 2);
        assert_eq!(page1[0].0, key(5, 1));
        assert_eq!(page1[0].1, b"v1");
        assert_eq!(page1[1].0, key(5, 2));

        let cursor = page1.last().unwrap().0.encode();
        let page2 = store.scan_behavioral(5, Some(&cursor), 10).unwrap();
        assert_eq!(page2.len(), 1, "only the remaining partition-5 key");
        assert_eq!(page2[0].0, key(5, 3));

        // A cursor at the partition's last key is exhausted.
        let last = page2.last().unwrap().0.encode();
        assert!(store
            .scan_behavioral(5, Some(&last), 10)
            .unwrap()
            .is_empty());

        assert!(
            store.scan_behavioral(9, None, 10).unwrap().is_empty(),
            "empty partition"
        );
    }

    fn behavioral_key_for(partition_id: u16, person: u128) -> BehavioralKey {
        BehavioralKey::new(
            partition_id,
            7,
            Uuid::from_u128(person),
            LeafStateKey([0xAB; 16]),
        )
    }

    /// Five partition-5 keys plus one partition-6 key a partition-5 scan must never surface.
    fn seed_p5_and_one_p6(batch: &mut BatchBuilder<'_>) {
        for person in 1..=5u128 {
            batch.put::<Behavioral>(
                &behavioral_key_for(5, person),
                format!("v{person}").as_bytes(),
            );
        }
        batch.put::<Behavioral>(&behavioral_key_for(6, 9), b"other-partition");
    }

    /// Flushes to SST so the scan hits on-disk index/filter blocks, not the memtable.
    fn flushed_p5_scan(
        config: &StoreConfig,
        seed: impl FnOnce(&mut BatchBuilder<'_>),
    ) -> Vec<(BehavioralKey, Vec<u8>)> {
        let store = CohortStore::open(config).unwrap();
        store.write_batch(seed).unwrap();
        store.flush().unwrap();

        let mut out = Vec::new();
        let mut cursor: Option<Vec<u8>> = None;
        loop {
            let page = store.scan_behavioral(5, cursor.as_deref(), 2).unwrap();
            let Some((last_key, _)) = page.last() else {
                break;
            };
            cursor = Some(last_key.encode().to_vec());
            out.extend(page);
        }
        out
    }

    /// Seeds several persons × several leaves in one partition plus neighbours in adjacent partitions,
    /// flushes to SST (so iteration hits on-disk prefix blocks, not the memtable where truncation is
    /// masked), and returns the store.
    fn seed_multi_person_flushed() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            tuned_block_options: true,
            ..StoreConfig::default()
        })
        .unwrap();
        store
            .write_batch(|batch| {
                for person in 1..=4u128 {
                    for leaf in 0..3u8 {
                        let key = BehavioralKey::new(
                            5,
                            7,
                            Uuid::from_u128(person),
                            LeafStateKey([leaf; 16]),
                        );
                        batch.put::<Behavioral>(&key, b"v");
                    }
                }
                // Neighbours in adjacent partitions the partition-5 scan must never surface.
                batch.put::<Behavioral>(&behavioral_key_for(4, 99), b"prev-partition");
                batch.put::<Behavioral>(&behavioral_key_for(6, 99), b"next-partition");
            })
            .unwrap();
        store.flush().unwrap();
        (dir, store)
    }

    #[test]
    fn scan_behavioral_crosses_every_person_prefix_in_the_partition() {
        // The regression this pins: with the fixed-prefix extractor in place, a partition-wide scan
        // must set total-order seek or it truncates at the first person's prefix boundary.
        let (_dir, store) = seed_multi_person_flushed();

        let mut all = Vec::new();
        let mut cursor: Option<Vec<u8>> = None;
        loop {
            let page = store.scan_behavioral(5, cursor.as_deref(), 2).unwrap();
            let Some((last, _)) = page.last() else {
                break;
            };
            cursor = Some(last.encode().to_vec());
            all.extend(page);
        }

        assert_eq!(
            all.len(),
            12,
            "4 persons × 3 leaves, crossing every person prefix"
        );
        let persons: std::collections::BTreeSet<u128> =
            all.iter().map(|(k, _)| k.person_id().as_u128()).collect();
        assert_eq!(
            persons,
            [1, 2, 3, 4].into_iter().collect(),
            "the scan reaches all four persons, not just the first prefix",
        );
        assert!(
            all.iter().all(|(k, _)| k.partition_id() == 5),
            "the adjacent-partition neighbours are excluded by the upper bound",
        );
    }

    #[test]
    fn scan_behavioral_prefix_returns_exactly_one_persons_leaves_in_lsk_order() {
        let (_dir, store) = seed_multi_person_flushed();
        let prefix = PersonPrefix::new(5, 7, Uuid::from_u128(2));

        let rows = store.scan_behavioral_prefix(prefix).unwrap();
        assert_eq!(rows.len(), 3, "only person 2's three leaves");
        assert!(
            rows.iter()
                .all(|(k, _)| k.person_id() == Uuid::from_u128(2)),
            "the scan never leaks past the 26-byte person prefix",
        );
        let lsks: Vec<[u8; 16]> = rows.iter().map(|(k, _)| k.lsk().0).collect();
        let mut sorted = lsks.clone();
        sorted.sort();
        assert_eq!(lsks, sorted, "leaves come back in lsk-byte order");
    }

    #[test]
    fn delete_partition_wipes_partitioned_cfs_but_preserves_the_schema_stamp() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let key = behavioral_key_for(5, 1);
        store
            .write_batch(|b| b.put::<Behavioral>(&key, b"state"))
            .unwrap();
        assert!(store.get_behavioral(&key).unwrap().is_some());

        store.delete_partition(5).unwrap();

        assert_eq!(
            store.get_behavioral(&key).unwrap(),
            None,
            "the partition's behavioral rows are reclaimed",
        );
        assert_eq!(
            store
                .get(Cf::Meta, META_SCHEMA_VERSION.0)
                .unwrap()
                .as_deref(),
            Some(STORE_SCHEMA_VERSION.to_be_bytes().as_slice()),
            "cf_meta is exempt from the partition wipe, so the schema guard survives a rebalance",
        );
    }

    #[test]
    fn tuned_block_options_preserve_scan_semantics_across_flushed_ssts() {
        // Partitioned filters + two-level index change SST metadata layout only, not scan order.
        let tuned = TempDir::new().unwrap();
        let plain = TempDir::new().unwrap();
        let tuned_scan = flushed_p5_scan(
            &StoreConfig {
                path: tuned.path().join("db"),
                tuned_block_options: true,
                compact_on_deletion: true,
                ..StoreConfig::default()
            },
            seed_p5_and_one_p6,
        );
        let plain_scan = flushed_p5_scan(
            &StoreConfig {
                path: plain.path().join("db"),
                tuned_block_options: false,
                compact_on_deletion: false,
                periodic_compaction_seconds: 0,
                ..StoreConfig::default()
            },
            seed_p5_and_one_p6,
        );

        assert_eq!(
            tuned_scan.len(),
            5,
            "all five partition-5 keys, the partition-6 key excluded by the upper bound",
        );
        assert_eq!(
            tuned_scan, plain_scan,
            "tuned partitioned-filter / two-level-index layout must not change prefix iteration",
        );
    }

    #[test]
    fn tuned_options_keep_tombstone_visibility_correct_across_compaction() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            tuned_block_options: true,
            compact_on_deletion: true,
            ..StoreConfig::default()
        })
        .unwrap();

        // Ten partition-5 keys → SST.
        store
            .write_batch(|batch| {
                for person in 1..=10u128 {
                    batch.put::<Behavioral>(&behavioral_key_for(5, person), b"v");
                }
            })
            .unwrap();
        store.flush().unwrap();

        // Delete the even persons → a second SST carrying the tombstones over the first.
        store
            .write_batch(|batch| {
                for person in (2..=10u128).step_by(2) {
                    batch.delete::<Behavioral>(&behavioral_key_for(5, person));
                }
            })
            .unwrap();
        store.flush().unwrap();

        // Force a physical compaction so the tombstones actually rewrite the SSTs, exercising the
        // compaction path instead of only the read-time merge iterator.
        store.db.compact_range_cf(
            store.cf(Cf::Behavioral).unwrap(),
            None::<&[u8]>,
            None::<&[u8]>,
        );

        let mut survivors = Vec::new();
        let mut cursor: Option<Vec<u8>> = None;
        loop {
            let page = store.scan_behavioral(5, cursor.as_deref(), 3).unwrap();
            let Some((last_key, _)) = page.last() else {
                break;
            };
            cursor = Some(last_key.encode().to_vec());
            survivors.extend(page.iter().map(|(key, _)| key.person_id().as_u128()));
        }
        assert_eq!(
            survivors,
            vec![1, 3, 5, 7, 9],
            "compaction drops the deleted evens and keeps the odds ordered and bounded",
        );
    }

    #[test]
    fn person_record_ttl_drops_ancient_keeps_fresh_and_malformed_and_never_touches_behavioral() {
        use crate::stage1::person_record::{PersonRecord, Stamp};
        use chrono::Utc;

        // A 30-day TTL against a fixed enough gap: `last_seen_ms = 0` is ~epoch, far older than any
        // real `now - 30d`, so it is ancient; a `last_seen_ms` at `now` is fresh.
        let now_ms = Utc::now().timestamp_millis();
        let fresh_ms = now_ms;
        let ancient_ms = 0;

        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            person_record_ttl_days: 30,
            compact_on_deletion: false,
            ..StoreConfig::default()
        })
        .unwrap();

        let record_bytes = |last_seen_ms: i64| {
            let mut record = PersonRecord::absent();
            record.last_seen_ms = last_seen_ms;
            record.stamp = Stamp::new(last_seen_ms, 0);
            record.encode()
        };

        let ancient_key = record_key(5, 1);
        let fresh_key = record_key(5, 2);
        // A malformed person-record value: the keyspace treats the value as opaque, so a raw put of
        // garbage bytes seeds a row the codec cannot decode.
        let malformed_key = record_key(5, 3);
        let malformed_value = b"not a person record";
        // An ancient behavioral row: the sweep owns its eviction, so the TTL filter must never touch it.
        let behavioral_key = BehavioralKey::new(5, 7, Uuid::from_u128(4), LeafStateKey([0xCD; 16]));

        store
            .write_batch(|b| {
                b.put::<PersonRecords>(&ancient_key, &record_bytes(ancient_ms));
                b.put::<PersonRecords>(&fresh_key, &record_bytes(fresh_ms));
                b.put::<PersonRecords>(&malformed_key, malformed_value);
                b.put::<Behavioral>(&behavioral_key, &record_bytes(ancient_ms));
            })
            .unwrap();
        store.flush().unwrap();

        // Force a physical compaction of both CFs so the filter actually runs over the SSTs.
        store.db.compact_range_cf(
            store.cf(Cf::PersonRecords).unwrap(),
            None::<&[u8]>,
            None::<&[u8]>,
        );
        store.db.compact_range_cf(
            store.cf(Cf::Behavioral).unwrap(),
            None::<&[u8]>,
            None::<&[u8]>,
        );

        assert_eq!(
            store.get_person_record(&ancient_key).unwrap(),
            None,
            "a record older than the TTL is dropped by compaction",
        );
        assert_eq!(
            store.get_person_record(&fresh_key).unwrap().as_deref(),
            Some(record_bytes(fresh_ms).as_slice()),
            "a record newer than the TTL survives",
        );
        assert_eq!(
            store.get_person_record(&malformed_key).unwrap().as_deref(),
            Some(malformed_value.as_slice()),
            "a malformed value is never TTL-dropped — it surfaces as a read-time decode error instead",
        );
        assert_eq!(
            store.get_behavioral(&behavioral_key).unwrap().as_deref(),
            Some(record_bytes(ancient_ms).as_slice()),
            "an ancient behavioral row is untouched: the TTL filter attaches to cf_person_records only",
        );
    }

    #[test]
    fn person_record_ttl_zero_installs_no_filter_so_ancient_records_survive() {
        use crate::stage1::person_record::{PersonRecord, Stamp};

        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            person_record_ttl_days: 0, // default: no compaction filter
            compact_on_deletion: false,
            ..StoreConfig::default()
        })
        .unwrap();

        let key = record_key(5, 1);
        let mut record = PersonRecord::absent();
        record.last_seen_ms = 0; // epoch-ancient
        record.stamp = Stamp::new(0, 0);
        let encoded = record.encode();

        store
            .write_batch(|b| b.put::<PersonRecords>(&key, &encoded))
            .unwrap();
        store.flush().unwrap();
        store.db.compact_range_cf(
            store.cf(Cf::PersonRecords).unwrap(),
            None::<&[u8]>,
            None::<&[u8]>,
        );

        assert_eq!(
            store.get_person_record(&key).unwrap().as_deref(),
            Some(encoded.as_slice()),
            "with TTL=0 no filter is installed, so even an ancient record survives compaction",
        );
    }

    #[test]
    fn stats_snapshot_reports_keys_and_cache_activity_after_reads() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            statistics_enabled: true,
            ..StoreConfig::default()
        })
        .unwrap();

        let key = |person: u128| {
            BehavioralKey::new(3, 7, Uuid::from_u128(person), LeafStateKey([0xAB; 16]))
        };
        store
            .write_batch(|batch| {
                for person in 1..=8u128 {
                    batch.put::<Behavioral>(&key(person), b"state");
                }
            })
            .unwrap();
        // Only SST reads exercise the block cache (memtable hits short-circuit it), so flush first.
        store.flush().unwrap();

        for person in 1..=8u128 {
            assert!(store.get_behavioral(&key(person)).unwrap().is_some());
        }

        let stats = store.stats_snapshot();
        assert_eq!(
            stats.per_cf.len(),
            Cf::ALL.len(),
            "one CfStats entry per column family",
        );
        let behavioral = stats
            .per_cf
            .iter()
            .find(|cf| cf.cf == Cf::Behavioral)
            .expect("Behavioral CF present in the snapshot");
        assert!(
            behavioral.num_keys > 0,
            "estimate-num-keys counts the written keys"
        );
        assert!(
            behavioral.sst_bytes > 0,
            "flushed behavioral keys occupy SST bytes"
        );
        assert!(
            stats.block_cache_hits + stats.block_cache_misses > 0,
            "reads against the flushed SSTs drove block-cache lookups: hits={}, misses={}",
            stats.block_cache_hits,
            stats.block_cache_misses,
        );
    }

    #[test]
    fn stats_snapshot_tickers_are_zero_when_statistics_disabled() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            statistics_enabled: false,
            ..StoreConfig::default()
        })
        .unwrap();
        let key = behavioral_key();
        store
            .write_batch(|b| b.put::<Behavioral>(&key, b"state"))
            .unwrap();
        store.flush().unwrap();
        assert!(store.get_behavioral(&key).unwrap().is_some());

        let stats = store.stats_snapshot();
        // Tickers read 0 with statistics off; size properties are not gated on statistics.
        assert_eq!(stats.block_cache_hits, 0);
        assert_eq!(stats.block_cache_misses, 0);
        let behavioral = stats
            .per_cf
            .iter()
            .find(|cf| cf.cf == Cf::Behavioral)
            .unwrap();
        assert!(
            behavioral.num_keys > 0,
            "size properties work without statistics"
        );
    }

    #[test]
    fn default_config_is_sane() {
        let config = StoreConfig::default();
        assert!(config.create_if_missing);
        assert!(config.block_cache_bytes > 0);
        assert!(config.write_buffer_bytes > 0);
        assert!(config.max_open_files > 0);
        assert!(config.statistics_enabled, "statistics default on");
        assert_eq!(
            config.read_sample_ratio, 64,
            "read latency sampling defaults to 1-in-64",
        );
        assert!(config.tuned_block_options);
        assert!(config.compact_on_deletion);
        assert!(config.compact_on_deletion_window > 0);
        assert!(config.compact_on_deletion_num_dels_trigger > 0);
        assert!(config.compact_on_deletion_ratio > 0.0 && config.compact_on_deletion_ratio <= 1.0);
        // Periodic compaction and the background-jobs cap are opt-in; `0` leaves RocksDB's own behavior.
        assert_eq!(config.periodic_compaction_seconds, 0);
        assert_eq!(config.max_background_jobs, 0);
    }

    #[test]
    fn read_sampler_fires_once_per_ratio() {
        // `ratio == 1` samples every read.
        assert!((0..4).all(|_| should_sample_read(1)));
        // Any 64 consecutive calls hold exactly one multiple of 64, so carry-over doesn't matter.
        let hits = (0..64).filter(|_| should_sample_read(64)).count();
        assert_eq!(hits, 1, "1-in-64 fires exactly once across 64 calls");
    }

    #[test]
    fn read_sample_ratio_floors_zero_at_one() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            read_sample_ratio: 0,
            ..StoreConfig::default()
        })
        .unwrap();
        // `0` would panic `next % ratio` in `should_sample_read`; `open()` clamps it to 1.
        assert!(store.get(Cf::Behavioral, b"missing").unwrap().is_none());
    }

    #[test]
    fn cohort_store_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<CohortStore>();
    }
}
