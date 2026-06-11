//! The RocksDB wrapper: one database per process, multi-CF atomic `WriteBatch`, async WAL.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, histogram};
use rocksdb::{
    Cache, ColumnFamily, DBWithThreadMode, Direction, FlushOptions, IteratorMode, Options,
    ReadOptions, SingleThreaded, WriteBatch, WriteOptions,
};
use thiserror::Error;

use super::column_families::{self, Cf, OpaqueCf};
use super::keys::{
    self, MergeAppliedKey, MergeDrainKey, PendingTransferKey, PersonIndexKey, Stage2Key,
    TombstoneKey,
};
use super::secondary_index::{decode_person_index, IndexOp};
use crate::observability::metrics::{
    STORE_ERRORS_TOTAL, STORE_WRITE_BATCH_TOTAL, STORE_WRITE_DURATION_SECONDS,
};
use crate::stage1::key::{LeafStateKey, Stage1Key};

// Shared between `StoreError::Backend { op }` and the metric `op` label.
const OP_OPEN: &str = "open";
const OP_DESTROY: &str = "destroy";
const OP_GET: &str = "get";
const OP_MULTI_GET: &str = "multi_get";
const OP_WRITE_BATCH: &str = "write_batch";
const OP_DELETE_PARTITION: &str = "delete_partition";
const OP_FLUSH: &str = "flush";
const OP_SCAN: &str = "scan";

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
    /// Destroy any existing database at `path` before opening.
    pub wipe_on_start: bool,
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

/// Handle to the per-process state store. Cheaply cloneable (`Arc<DB>`).
#[derive(Clone)]
pub struct CohortStore {
    db: Arc<DBWithThreadMode<SingleThreaded>>,
}

impl CohortStore {
    /// Open the column families at `config.path`, creating them if missing. If `wipe_on_start` is
    /// set and a database exists, it is destroyed first.
    pub fn open(config: &StoreConfig) -> Result<Self, StoreError> {
        let cache = Cache::new_lru_cache(config.block_cache_bytes);
        let db_opts = db_options(config);

        if config.wipe_on_start && config.path.exists() {
            // `destroy` requires the DB be closed; it is, since we have not opened it yet.
            DBWithThreadMode::<SingleThreaded>::destroy(&db_opts, &config.path).map_err(
                |source| {
                    counter!(STORE_ERRORS_TOTAL, "op" => OP_DESTROY).increment(1);
                    StoreError::Open {
                        path: config.path.clone(),
                        source,
                    }
                },
            )?;
        }

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

        Ok(Self { db: Arc::new(db) })
    }

    /// Read a raw value from any CF.
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

    /// Batch-read several `cf_stage1` values in one call, preserving input order.
    pub fn multi_get_stage1(&self, keys: &[Stage1Key]) -> Result<Vec<Option<Vec<u8>>>, StoreError> {
        let handle = self.cf(Cf::Stage1)?;
        let encoded: Vec<_> = keys.iter().map(Stage1Key::encode).collect();
        self.db
            .multi_get_cf(encoded.iter().map(|key| (handle, key.as_slice())))
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

    /// Apply writes across CFs in one atomic `WriteBatch`.
    pub fn write_batch<F>(&self, build: F) -> Result<(), StoreError>
    where
        F: FnOnce(&mut BatchBuilder<'_>),
    {
        let mut builder = BatchBuilder {
            batch: WriteBatch::default(),
            stage1: self.cf(Cf::Stage1)?,
            person_index: self.cf(Cf::PersonIndex)?,
            stage2: self.cf(Cf::Stage2)?,
            merge_drains_applied: self.cf(Cf::MergeDrainsApplied)?,
            pending_transfers: self.cf(Cf::PendingTransfers)?,
            merge_applied: self.cf(Cf::MergeApplied)?,
            merge_tombstones: self.cf(Cf::MergeTombstones)?,
        };
        build(&mut builder);
        self.commit(builder.batch, OP_WRITE_BATCH)
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

    /// Scan one partition's `cf_pending_transfers` slice, returning `(key, value)` in key order.
    pub fn scan_pending_transfers(
        &self,
        partition_id: u16,
    ) -> Result<Vec<(PendingTransferKey, Vec<u8>)>, StoreError> {
        let (start, end) = keys::partition_range(partition_id);
        let handle = self.cf(Cf::PendingTransfers)?;

        let mut read_opts = ReadOptions::default();
        read_opts.set_iterate_upper_bound(end);
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
            out.push((PendingTransferKey::decode(&key_bytes)?, value.to_vec()));
        }
        Ok(out)
    }

    /// Reclaim all state for one partition on rebalance.
    pub fn delete_partition(&self, partition_id: u16) -> Result<(), StoreError> {
        let (start, end) = keys::partition_range(partition_id);
        let mut batch = WriteBatch::default();
        for cf in Cf::ALL {
            let handle = self.cf(cf)?;
            batch.delete_range_cf(handle, start.as_slice(), end.as_slice());
        }
        self.commit(batch, OP_DELETE_PARTITION)
    }

    /// Flush all CF memtables to SST. Checkpoint path and tests only.
    pub fn flush(&self) -> Result<(), StoreError> {
        let handles = [
            self.cf(Cf::Stage1)?,
            self.cf(Cf::PersonIndex)?,
            self.cf(Cf::Stage2)?,
            self.cf(Cf::MergeDrainsApplied)?,
            self.cf(Cf::PendingTransfers)?,
            self.cf(Cf::MergeApplied)?,
            self.cf(Cf::MergeTombstones)?,
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

/// Typed builder for a multi-CF [`WriteBatch`].
pub struct BatchBuilder<'db> {
    batch: WriteBatch,
    stage1: &'db ColumnFamily,
    person_index: &'db ColumnFamily,
    stage2: &'db ColumnFamily,
    merge_drains_applied: &'db ColumnFamily,
    pending_transfers: &'db ColumnFamily,
    merge_applied: &'db ColumnFamily,
    merge_tombstones: &'db ColumnFamily,
}

impl BatchBuilder<'_> {
    pub fn put_stage1(&mut self, key: &Stage1Key, value: &[u8]) {
        self.batch.put_cf(self.stage1, key.encode(), value);
    }

    pub fn delete_stage1(&mut self, key: &Stage1Key) {
        self.batch.delete_cf(self.stage1, key.encode());
    }

    /// Read-free append/remove on the person's index.
    pub fn merge_person_index(&mut self, key: &PersonIndexKey, op: IndexOp) {
        self.batch
            .merge_cf(self.person_index, key.encode(), op.encode());
    }

    /// Whole-key delete of a person's index entry.
    pub fn delete_person_index(&mut self, key: &PersonIndexKey) {
        self.batch.delete_cf(self.person_index, key.encode());
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

    /// Stage the redirect tombstone for a merged-away person.
    pub fn put_tombstone(&mut self, key: &TombstoneKey, value: &[u8]) {
        self.batch
            .put_cf(self.merge_tombstones, key.encode(), value);
    }

    /// Raw put by pre-encoded key bytes. Restricted to [`OpaqueCf`].
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
    use tempfile::TempDir;
    use uuid::Uuid;

    fn stage1_key() -> Stage1Key {
        Stage1Key {
            partition_id: 3,
            team_id: 7,
            leaf_state_key: LeafStateKey([0xAB; 16]),
            person_id: Uuid::from_u128(1),
        }
    }

    #[test]
    fn wipe_on_start_clears_existing_state_and_is_a_noop_when_off() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("db");
        let key = stage1_key();

        // Seed a value, then close the database (drop the only handle).
        {
            let store = CohortStore::open(&StoreConfig {
                path: path.clone(),
                ..StoreConfig::default()
            })
            .unwrap();
            store.write_batch(|b| b.put_stage1(&key, b"state")).unwrap();
            assert_eq!(
                store.get_stage1(&key).unwrap().as_deref(),
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
                store.get_stage1(&key).unwrap().as_deref(),
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
            assert_eq!(store.get_stage1(&key).unwrap(), None);
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
        assert_eq!(store.get_stage1(&stage1_key()).unwrap(), None);
    }

    #[test]
    fn multi_get_stage1_preserves_order_and_reports_absent_keys() {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();

        let present = |person: u128, lsk: u8| Stage1Key {
            partition_id: 3,
            team_id: 7,
            leaf_state_key: LeafStateKey([lsk; 16]),
            person_id: Uuid::from_u128(person),
        };
        let a = present(1, 0xA0);
        let b = present(2, 0xB0);
        let absent = present(9, 0xFF);
        store
            .write_batch(|batch| {
                batch.put_stage1(&a, b"alpha");
                batch.put_stage1(&b, b"bravo");
            })
            .unwrap();

        // Order: present, absent, present — the absent key must surface as a `None` hole, not shift
        // the others.
        let results = store.multi_get_stage1(&[a, absent, b]).unwrap();
        assert_eq!(results.len(), 3);
        assert_eq!(results[0].as_deref(), Some(b"alpha".as_slice()));
        assert_eq!(results[1], None);
        assert_eq!(results[2].as_deref(), Some(b"bravo".as_slice()));

        assert!(
            store.multi_get_stage1(&[]).unwrap().is_empty(),
            "an empty key set reads no values",
        );
    }

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
