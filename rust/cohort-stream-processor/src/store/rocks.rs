//! The RocksDB wrapper: one database per process, multi-CF atomic `WriteBatch`, async WAL.
//!
//! This is a bespoke wrapper directly on the `rocksdb` crate rather than an extension of
//! `rust/kafka-deduplicator/src/rocksdb/store.rs` (a deliberate deviation from TDD §2.5:308 —
//! see the PR description). The dedup store's shared static block-cache / write-buffer-manager
//! machinery exists to bound memory across *many* stores (one per partition); here there is one
//! DB per process, so this wrapper owns its resources directly, uses the `metrics` facade +
//! typed [`StoreError`] (not `MetricsHelper` + `anyhow`), and adds the merge operator the dedup
//! store never needed.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use rocksdb::{
    Cache, ColumnFamily, DBWithThreadMode, FlushOptions, Options, SingleThreaded, WriteBatch,
    WriteOptions,
};
use thiserror::Error;

use super::column_families::{self, Cf, OpaqueCf};
use super::keys::{self, PersonIndexKey, Stage2Key};
use super::secondary_index::{decode_person_index, IndexOp};
use crate::observability::metrics::{
    STORE_ERRORS_TOTAL, STORE_WRITE_BATCH_TOTAL, STORE_WRITE_DURATION_SECONDS,
};
use crate::stage1::key::{LeafStateKey, Stage1Key};

// Operation labels — shared between `StoreError::Backend { op }` and the metric `op` label.
const OP_OPEN: &str = "open";
const OP_GET: &str = "get";
const OP_WRITE_BATCH: &str = "write_batch";
const OP_DELETE_PARTITION: &str = "delete_partition";
const OP_FLUSH: &str = "flush";

// Sound defaults pending the §5.1 (M9) sizing measurement; not tuning knobs.
const DEFAULT_BLOCK_CACHE_BYTES: usize = 128 * 1024 * 1024; // 128 MB
const DEFAULT_WRITE_BUFFER_BYTES: usize = 64 * 1024 * 1024; // 64 MB per memtable
const DEFAULT_MAX_OPEN_FILES: i32 = 1024;

/// Resolved RocksDB settings. Mirrors the shape of kafka-deduplicator's `RocksDbConfig` minus
/// the shared statics. Env-var wiring into the service `Config` is PR 1.5/1.6; this PR ships
/// [`StoreConfig::default`].
#[derive(Debug, Clone)]
pub struct StoreConfig {
    pub path: PathBuf,
    pub block_cache_bytes: usize,
    pub write_buffer_bytes: usize,
    pub max_open_files: i32,
    pub create_if_missing: bool,
}

impl Default for StoreConfig {
    fn default() -> Self {
        Self {
            path: PathBuf::from("cohort-store"),
            block_cache_bytes: DEFAULT_BLOCK_CACHE_BYTES,
            write_buffer_bytes: DEFAULT_WRITE_BUFFER_BYTES,
            max_open_files: DEFAULT_MAX_OPEN_FILES,
            create_if_missing: true,
        }
    }
}

/// Errors from the state store. Mirrors `FilterError`'s `thiserror` shape. `Open` and `Backend`
/// both wrap `rocksdb::Error`, so the conversion is explicit per call site (no blanket `#[from]`).
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
}

/// Handle to the per-process state store. Cheaply cloneable (shares one `Arc<DB>`); clones share
/// the same database, so a partition worker can hold its own clone.
#[derive(Clone)]
pub struct CohortStore {
    // SingleThreaded: the CF set is fixed at open (we never create/drop a CF at runtime), so we
    // avoid MultiThreaded's per-`cf_handle` RwLock read + Arc clone. The DB is still `Sync`, so an
    // `Arc` clone is shared across partition workers.
    db: Arc<DBWithThreadMode<SingleThreaded>>,
}

impl CohortStore {
    /// Open (creating if missing) the three state column families at `config.path`.
    pub fn open(config: &StoreConfig) -> Result<Self, StoreError> {
        let cache = Cache::new_lru_cache(config.block_cache_bytes);
        let db_opts = db_options(config);
        let descriptors = column_families::descriptors(config, &cache);

        let db = DBWithThreadMode::<SingleThreaded>::open_cf_descriptors(
            &db_opts,
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

        // RocksDB clones and retains `cache` for the DB's lifetime via its `OptionsMustOutliveDB`
        // mechanism (the cache lives in each CF descriptor's block options), so dropping the
        // local here is safe — no need to keep it in the struct.
        Ok(Self { db: Arc::new(db) })
    }

    /// Read a raw value from any CF. `cf_person_index` reads are collapsed through the merge
    /// operator by RocksDB; prefer [`CohortStore::get_person_index`] there to decode the set.
    pub fn get(&self, cf: Cf, key: &[u8]) -> Result<Option<Vec<u8>>, StoreError> {
        let handle = self.cf(cf)?;
        self.db.get_cf(handle, key).map_err(|source| {
            counter!(STORE_ERRORS_TOTAL, "op" => OP_GET).increment(1);
            StoreError::Backend { op: OP_GET, source }
        })
    }

    /// Read the opaque Stage 1 record for a key (typed value codec lands in PR 1.6).
    pub fn get_stage1(&self, key: &Stage1Key) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Stage1, &key.encode())
    }

    /// Read the opaque Stage 2 record for a key (typed value codec lands in PR 2.1).
    pub fn get_stage2(&self, key: &Stage2Key) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Stage2, &key.encode())
    }

    /// Read a person's Stage 1 leaf-state keys. A missing key (or empty merge result) decodes to
    /// an empty vec — "no states". Returns owned `Vec` now; widens to `SmallVec` in PR 1.6 with a
    /// one-line signature change (the on-disk packed format is the real contract).
    pub fn get_person_index(&self, key: &PersonIndexKey) -> Result<Vec<LeafStateKey>, StoreError> {
        Ok(self
            .get(Cf::PersonIndex, &key.encode())?
            .map(|bytes| decode_person_index(&bytes))
            .unwrap_or_default())
    }

    /// Apply a set of writes across the three CFs in a single atomic `WriteBatch`. One WAL record
    /// makes the batch all-or-nothing across CFs even though the WAL is async (§2.5:301,309).
    pub fn write_batch<F>(&self, build: F) -> Result<(), StoreError>
    where
        F: FnOnce(&mut BatchBuilder<'_>),
    {
        let mut builder = BatchBuilder {
            batch: WriteBatch::default(),
            stage1: self.cf(Cf::Stage1)?,
            person_index: self.cf(Cf::PersonIndex)?,
            stage2: self.cf(Cf::Stage2)?,
        };
        build(&mut builder);
        self.commit(builder.batch, OP_WRITE_BATCH)
    }

    /// Reclaim all state for one partition on rebalance (§2.5:300). Fans a `delete_range` over
    /// every CF in one atomic batch, so a crash can't leave one CF's partition state orphaned.
    /// (The caller — the rebalance handler — is worker scope, PR 1.5.)
    pub fn delete_partition(&self, partition_id: u16) -> Result<(), StoreError> {
        let (start, end) = keys::partition_range(partition_id);
        let mut batch = WriteBatch::default();
        for cf in Cf::ALL {
            let handle = self.cf(cf)?;
            batch.delete_range_cf(handle, start.as_slice(), end.as_slice());
        }
        self.commit(batch, OP_DELETE_PARTITION)
    }

    /// Flush all CF memtables to SST. Atomic across CFs (`set_atomic_flush`). Used by the
    /// checkpoint path (PR 3.5) and tests; not on the hot path.
    pub fn flush(&self) -> Result<(), StoreError> {
        let handles = [
            self.cf(Cf::Stage1)?,
            self.cf(Cf::PersonIndex)?,
            self.cf(Cf::Stage2)?,
        ];
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

    fn cf(&self, cf: Cf) -> Result<&ColumnFamily, StoreError> {
        self.db
            .cf_handle(cf.as_str())
            .ok_or(StoreError::UnknownColumnFamily(cf.as_str()))
    }

    fn commit(&self, batch: WriteBatch, op: &'static str) -> Result<(), StoreError> {
        let mut write_opts = WriteOptions::default();
        // Async WAL (§2.5:309); durability comes from the checkpoint cadence + Kafka replay.
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

/// Typed builder for a multi-CF [`WriteBatch`], handed to the [`CohortStore::write_batch`]
/// closure. Holds the three CF handles up front (borrowed `&ColumnFamily`, which is
/// `AsColumnFamilyRef`) so the closure can mix writes across CFs without re-resolving handles.
pub struct BatchBuilder<'db> {
    batch: WriteBatch,
    stage1: &'db ColumnFamily,
    person_index: &'db ColumnFamily,
    stage2: &'db ColumnFamily,
}

impl BatchBuilder<'_> {
    /// Stage the opaque Stage 1 record for `key`.
    pub fn put_stage1(&mut self, key: &Stage1Key, value: &[u8]) {
        self.batch.put_cf(self.stage1, key.encode(), value);
    }

    /// Stage a deletion of `key` from `cf_stage1`.
    pub fn delete_stage1(&mut self, key: &Stage1Key) {
        self.batch.delete_cf(self.stage1, key.encode());
    }

    /// Stage an append/remove of a leaf-state key on the person's secondary index. Read-free: the
    /// merge operator resolves it at compaction/read time (§2.5:301).
    pub fn merge_person_index(&mut self, key: &PersonIndexKey, op: IndexOp) {
        self.batch
            .merge_cf(self.person_index, key.encode(), op.encode());
    }

    /// Stage the opaque Stage 2 record for `key`.
    pub fn put_stage2(&mut self, key: &Stage2Key, value: &[u8]) {
        self.batch.put_cf(self.stage2, key.encode(), value);
    }

    /// Escape hatch for a raw put by pre-encoded key bytes. Only opaque-value CFs are addressable
    /// via [`OpaqueCf`] — `cf_person_index` is merge-only and not an `OpaqueCf` variant, so a raw
    /// put to it cannot be constructed (it won't compile), protecting the merge operator's value
    /// format.
    pub fn put_raw(&mut self, cf: OpaqueCf, key: &[u8], value: &[u8]) {
        let handle = match cf {
            OpaqueCf::Stage1 => self.stage1,
            OpaqueCf::Stage2 => self.stage2,
        };
        self.batch.put_cf(handle, key, value);
    }
}

fn db_options(config: &StoreConfig) -> Options {
    let mut opts = Options::default();
    opts.create_if_missing(config.create_if_missing);
    opts.create_missing_column_families(true);
    // Makes a multi-CF checkpoint a consistent point-in-time across cf_stage1/cf_person_index/
    // cf_stage2 (PR 3.5 depends on this). Does NOT affect WriteBatch atomicity — the WAL already
    // makes one batch all-or-nothing across CFs. One harmless line now.
    opts.set_atomic_flush(true);
    opts.set_max_open_files(config.max_open_files);
    // Disable mmap to bound virtual memory on shared PVC storage (matches kafka-deduplicator).
    opts.set_allow_mmap_reads(false);
    opts.set_allow_mmap_writes(false);
    opts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_is_sane() {
        let config = StoreConfig::default();
        assert!(config.create_if_missing);
        assert!(config.block_cache_bytes > 0);
        assert!(config.write_buffer_bytes > 0);
        assert!(config.max_open_files > 0);
    }

    /// `CohortStore` must stay `Send + Sync` so a single store can be cloned across partition
    /// workers — the property the `SingleThreaded` DB (still `Sync`) is chosen to preserve. This
    /// is a compile-time guard: it fails to compile if a future non-`Sync` field is added.
    #[test]
    fn cohort_store_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<CohortStore>();
    }
}
