//! The RocksDB wrapper: one database per process, multi-CF atomic `WriteBatch`, async WAL.
//!
//! Bespoke rather than reusing `kafka-deduplicator`'s store: that one shards static block-cache /
//! write-buffer machinery across many per-partition stores, whereas there is one DB per process
//! here, so this wrapper owns its resources directly and adds the `cf_person_index` merge operator.

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

// Shared between `StoreError::Backend { op }` and the metric `op` label.
const OP_OPEN: &str = "open";
const OP_GET: &str = "get";
const OP_WRITE_BATCH: &str = "write_batch";
const OP_DELETE_PARTITION: &str = "delete_partition";
const OP_FLUSH: &str = "flush";

const DEFAULT_BLOCK_CACHE_BYTES: usize = 128 * 1024 * 1024;
const DEFAULT_WRITE_BUFFER_BYTES: usize = 64 * 1024 * 1024;
const DEFAULT_MAX_OPEN_FILES: i32 = 1024;

/// Resolved RocksDB settings.
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

/// Errors from the state store. `Open` and `Backend` both wrap `rocksdb::Error`, so conversion is
/// explicit per call site (no blanket `#[from]`).
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

/// Handle to the per-process state store. Cheaply cloneable (`Arc<DB>`), so each partition worker
/// can hold its own clone over one shared database.
#[derive(Clone)]
pub struct CohortStore {
    // `SingleThreaded` (vs `MultiThreaded`) avoids a per-`cf_handle` RwLock read + Arc clone, since
    // the CF set is fixed at open. The DB is still `Sync`, so the `Arc` is shared across workers.
    db: Arc<DBWithThreadMode<SingleThreaded>>,
}

impl CohortStore {
    /// Open the three state column families at `config.path`, creating them if missing.
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

        // RocksDB retains `cache` for the DB's lifetime (`OptionsMustOutliveDB`), so dropping the
        // local here is safe.
        Ok(Self { db: Arc::new(db) })
    }

    /// Read a raw value from any CF. For `cf_person_index` prefer [`CohortStore::get_person_index`],
    /// which decodes the merge-collapsed set.
    pub fn get(&self, cf: Cf, key: &[u8]) -> Result<Option<Vec<u8>>, StoreError> {
        let handle = self.cf(cf)?;
        self.db.get_cf(handle, key).map_err(|source| {
            counter!(STORE_ERRORS_TOTAL, "op" => OP_GET).increment(1);
            StoreError::Backend { op: OP_GET, source }
        })
    }

    pub fn get_stage1(&self, key: &Stage1Key) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Stage1, &key.encode())
    }

    pub fn get_stage2(&self, key: &Stage2Key) -> Result<Option<Vec<u8>>, StoreError> {
        self.get(Cf::Stage2, &key.encode())
    }

    /// A missing key (or empty merge result) decodes to an empty vec — "no states".
    pub fn get_person_index(&self, key: &PersonIndexKey) -> Result<Vec<LeafStateKey>, StoreError> {
        Ok(self
            .get(Cf::PersonIndex, &key.encode())?
            .map(|bytes| decode_person_index(&bytes))
            .unwrap_or_default())
    }

    /// Apply writes across the three CFs in one `WriteBatch`. The single WAL record keeps the batch
    /// all-or-nothing across CFs even though the WAL is async.
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

    /// Reclaim all state for one partition on rebalance. The per-CF `delete_range`s share one batch
    /// so a crash can't leave one CF's partition state orphaned.
    pub fn delete_partition(&self, partition_id: u16) -> Result<(), StoreError> {
        let (start, end) = keys::partition_range(partition_id);
        let mut batch = WriteBatch::default();
        for cf in Cf::ALL {
            let handle = self.cf(cf)?;
            batch.delete_range_cf(handle, start.as_slice(), end.as_slice());
        }
        self.commit(batch, OP_DELETE_PARTITION)
    }

    /// Flush all CF memtables to SST, atomic across CFs (`set_atomic_flush`). Checkpoint path and
    /// tests only, not the hot path.
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
        // Async WAL; durability comes from the checkpoint cadence + Kafka replay.
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

/// Typed builder for a multi-CF [`WriteBatch`], handed to the [`CohortStore::write_batch`] closure.
/// Holds the three CF handles up front so the closure can mix writes without re-resolving them.
pub struct BatchBuilder<'db> {
    batch: WriteBatch,
    stage1: &'db ColumnFamily,
    person_index: &'db ColumnFamily,
    stage2: &'db ColumnFamily,
}

impl BatchBuilder<'_> {
    pub fn put_stage1(&mut self, key: &Stage1Key, value: &[u8]) {
        self.batch.put_cf(self.stage1, key.encode(), value);
    }

    pub fn delete_stage1(&mut self, key: &Stage1Key) {
        self.batch.delete_cf(self.stage1, key.encode());
    }

    /// Read-free append/remove on the person's index; the merge operator resolves it at
    /// compaction/read time.
    pub fn merge_person_index(&mut self, key: &PersonIndexKey, op: IndexOp) {
        self.batch
            .merge_cf(self.person_index, key.encode(), op.encode());
    }

    pub fn put_stage2(&mut self, key: &Stage2Key, value: &[u8]) {
        self.batch.put_cf(self.stage2, key.encode(), value);
    }

    /// Raw put by pre-encoded key bytes. Restricted to [`OpaqueCf`]: `cf_person_index` is merge-only
    /// and absent from that enum, so a raw put to it cannot compile.
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
    // Makes a multi-CF checkpoint a consistent point-in-time across CFs. Does NOT affect WriteBatch
    // atomicity — the WAL already covers that.
    opts.set_atomic_flush(true);
    opts.set_max_open_files(config.max_open_files);
    // Disable mmap to bound virtual memory on shared PVC storage.
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

    /// Compile-time guard: `CohortStore` must stay `Send + Sync` to be shared across workers.
    #[test]
    fn cohort_store_is_send_and_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<CohortStore>();
    }
}
