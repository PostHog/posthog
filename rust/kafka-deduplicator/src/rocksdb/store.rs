use std::{
    path::{Path, PathBuf},
    sync::Arc,
};

use anyhow::{Context, Result};
use num_cpus;
use once_cell::sync::Lazy;
use rocksdb::{
    checkpoint::Checkpoint, BlockBasedOptions, BoundColumnFamily, Cache, ColumnFamilyDescriptor,
    DBWithThreadMode, MultiThreaded, Options, WriteBatch, WriteBufferManager, WriteOptions,
};
use std::time::Instant;

use crate::metrics::MetricsHelper;
use crate::rocksdb::metrics_consts::*;

#[derive(Debug, Clone)]
pub struct RocksDbStore {
    pub(crate) db: Arc<DBWithThreadMode<MultiThreaded>>,
    path_location: PathBuf,
    metrics: MetricsHelper,
}

// Shared block cache for all RocksDB instances (1GB default)
static SHARED_BLOCK_CACHE: Lazy<Arc<Cache>> = Lazy::new(|| {
    let cache_size = std::env::var("ROCKSDB_SHARED_CACHE_SIZE")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(2048 * 1024 * 1024); // 2GB default

    Arc::new(Cache::new_lru_cache(cache_size))
});

// Shared write buffer manager to limit total memory used for write buffers
static SHARED_WRITE_BUFFER_MANAGER: Lazy<Arc<WriteBufferManager>> = Lazy::new(|| {
    let total_write_buffer_size = std::env::var("ROCKSDB_TOTAL_WRITE_BUFFER_SIZE")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .unwrap_or(2048 * 1024 * 1024); // 2GB total for ALL stores

    // false = don't allow stall (we'll handle backpressure at Kafka level)
    Arc::new(WriteBufferManager::new_write_buffer_manager(
        total_write_buffer_size,
        false,
    ))
});

fn rocksdb_options() -> Options {
    let num_threads = std::cmp::max(2, num_cpus::get()); // Avoid setting to 0 or 1

    let mut opts = Options::default();
    opts.create_if_missing(true);
    opts.create_missing_column_families(true);

    // Level style compaction with universal style for TTL-like use case
    opts.set_compaction_style(rocksdb::DBCompactionStyle::Universal);

    // Optimize for point lookups (dedup check)
    let mut block_opts = BlockBasedOptions::default();
    // Set bloom filter to 10 bits per key, not approximate
    // Bloom filter is a probabilistic data structure that allows for fast lookups
    // but with a small probability of false positives, we will use this
    // to avoid full lookups
    block_opts.set_bloom_filter(10.0, false);
    block_opts.set_cache_index_and_filter_blocks(true);
    block_opts.set_pin_l0_filter_and_index_blocks_in_cache(true);

    // CRITICAL: Use shared block cache across all stores
    block_opts.set_block_cache(&SHARED_BLOCK_CACHE);

    opts.set_block_based_table_factory(&block_opts);

    // CRITICAL: Use shared write buffer manager to limit total memory
    opts.set_write_buffer_manager(&SHARED_WRITE_BUFFER_MANAGER);

    // Reduced memory budget per store (with 50 partitions per pod)
    opts.set_write_buffer_size(8 * 1024 * 1024); // Reduced to 8MB per memtable
    opts.set_max_write_buffer_number(2); // Max 2 buffers = 16MB per partition
    opts.set_target_file_size_base(64 * 1024 * 1024); // SST files ~64MB

    // Parallelism
    opts.increase_parallelism(num_threads as i32);
    opts.optimize_level_style_compaction(512 * 1024 * 1024); // 512MB

    // Reduce background IO impact
    opts.set_disable_auto_compactions(false);
    opts.set_max_open_files(100); // Reduced from 500 for 50 partitions per pod

    // CRITICAL: Disable mmap with many partitions to avoid virtual memory explosion
    opts.set_allow_mmap_reads(false);
    opts.set_allow_mmap_writes(false);

    opts
}

impl RocksDbStore {
    pub fn new<P: AsRef<Path>>(
        path: P,
        cf_descriptors: Vec<ColumnFamilyDescriptor>,
        metrics: MetricsHelper,
    ) -> Result<Self> {
        let path_ref = path.as_ref();
        let opts = rocksdb_options();

        let db =
            DBWithThreadMode::<MultiThreaded>::open_cf_descriptors(&opts, path_ref, cf_descriptors)
                .context("Failed to open RocksDB")?;

        Ok(Self {
            db: Arc::new(db),
            path_location: path_ref.to_path_buf(),
            metrics,
        })
    }

    pub fn get(&self, cf_name: &str, key: &[u8]) -> Result<Option<Vec<u8>>> {
        let start_time = Instant::now();

        // Track read operation with column family label
        self.metrics
            .counter(ROCKSDB_READ_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let cf = self.get_cf_handle(cf_name)?;
        let result = self
            .db
            .get_cf(&cf, key)
            .context("Failed to get key from RocksDB");

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_READ_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    pub fn multi_get(&self, cf_name: &str, keys: Vec<&[u8]>) -> Result<Vec<Option<Vec<u8>>>> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_READ_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.multi_get_internal(cf_name, keys);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_MULTI_GET_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn multi_get_internal(&self, cf_name: &str, keys: Vec<&[u8]>) -> Result<Vec<Option<Vec<u8>>>> {
        let cf = self.get_cf_handle(cf_name)?;

        let keys_with_cf: Vec<_> = keys.iter().map(|k| (&cf, k)).collect();
        let results = self.db.multi_get_cf(keys_with_cf);

        results
            .into_iter()
            .map(|r| r.context("Failed to get key"))
            .collect()
    }

    pub fn put(&self, cf_name: &str, key: &[u8], value: &[u8]) -> Result<()> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_WRITE_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.put_internal(cf_name, key, value);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_WRITE_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn put_internal(&self, cf_name: &str, key: &[u8], value: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db.put_cf(&cf, key, value).context("Failed to put key")
    }

    pub fn put_batch(&self, cf_name: &str, entries: Vec<(&[u8], &[u8])>) -> Result<()> {
        let start_time = Instant::now();
        let batch_size = entries.len();
        self.metrics
            .counter(ROCKSDB_BATCH_WRITE_OPERATIONS_COUNTER)
            .with_label("column_family", cf_name)
            .increment(1);

        let result = self.put_batch_internal(cf_name, entries);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_BATCH_WRITE_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_ok() {
            // Track successful batch size
            self.metrics
                .histogram(ROCKSDB_BATCH_SIZE_HISTOGRAM)
                .with_label("column_family", cf_name)
                .record(batch_size as f64);
        } else {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn put_batch_internal(&self, cf_name: &str, entries: Vec<(&[u8], &[u8])>) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        let mut batch = WriteBatch::default();
        for (key, value) in entries {
            batch.put_cf(&cf, key, value);
        }
        let mut write_opts = WriteOptions::default();
        write_opts.set_sync(false);
        self.db
            .write_opt(batch, &write_opts)
            .context("Failed to put batch")
    }

    pub fn delete_range(&self, cf_name: &str, start: &[u8], end: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db
            .delete_range_cf(&cf, start, end)
            .context("Failed to delete range")
    }

    pub fn delete(&self, cf_name: &str, key: &[u8]) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db.delete_cf(&cf, key).context("Failed to delete key")
    }

    pub fn get_cf_handle(&self, cf_name: &str) -> Result<Arc<BoundColumnFamily<'_>>> {
        self.db
            .cf_handle(cf_name)
            .context("Column family not found")
    }

    pub fn get_db_size(&self, cf_name: &str) -> Result<u64> {
        let cf = self.get_cf_handle(cf_name)?;
        // Try to get SST files size
        let sst_size = self
            .db
            .property_int_value_cf(&cf, "rocksdb.total-sst-files-size")?
            .unwrap_or(0);

        Ok(sst_size)
    }

    /// Update database metrics (size, SST file count, etc.)
    /// This should be called periodically to emit current database state
    pub fn update_db_metrics(&self, cf_name: &str) -> Result<()> {
        // Update database size metric with column family label
        let db_size = self.get_db_size(cf_name)?;
        self.metrics
            .gauge(ROCKSDB_SIZE_BYTES_GAUGE)
            .with_label("column_family", cf_name)
            .set(db_size as f64);

        // Update SST file count with column family label
        let sst_files = self.get_sst_file_names(cf_name)?;
        self.metrics
            .gauge(ROCKSDB_SST_FILES_COUNT_GAUGE)
            .with_label("column_family", cf_name)
            .set(sst_files.len() as f64);

        Ok(())
    }

    pub fn flush_cf(&self, cf_name: &str) -> Result<()> {
        let start_time = Instant::now();

        let result = self.flush_cf_internal(cf_name);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_FLUSH_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn flush_cf_internal(&self, cf_name: &str) -> Result<()> {
        let mut flush_opts = rocksdb::FlushOptions::default();
        flush_opts.set_wait(true);
        let cf = self.get_cf_handle(cf_name)?;
        self.db
            .flush_cf_opt(&cf, &flush_opts)
            .context("Failed to flush")
    }

    pub fn compact_cf(&self, cf_name: &str) -> Result<()> {
        let start_time = Instant::now();

        let result = self.compact_cf_internal(cf_name);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_COMPACTION_DURATION_HISTOGRAM)
            .with_label("column_family", cf_name)
            .record(duration.as_secs_f64());

        result
    }

    fn compact_cf_internal(&self, cf_name: &str) -> Result<()> {
        let cf = self.get_cf_handle(cf_name)?;
        self.db.compact_range_cf(&cf, None::<&[u8]>, None::<&[u8]>);
        Ok(())
    }

    /// Create an incremental checkpoint at the specified path
    /// This creates a point-in-time snapshot that can be used for recovery
    pub fn create_checkpoint<P: AsRef<Path>>(&self, checkpoint_path: P) -> Result<()> {
        let start_time = Instant::now();
        self.metrics
            .counter(ROCKSDB_CHECKPOINT_OPERATIONS_COUNTER)
            .increment(1);

        let result = self.create_checkpoint_internal(checkpoint_path);

        let duration = start_time.elapsed();
        self.metrics
            .histogram(ROCKSDB_CHECKPOINT_DURATION_HISTOGRAM)
            .record(duration.as_secs_f64());

        if result.is_err() {
            self.metrics.counter(ROCKSDB_ERRORS_COUNTER).increment(1);
        }

        result
    }

    fn create_checkpoint_internal<P: AsRef<Path>>(&self, checkpoint_path: P) -> Result<()> {
        let checkpoint = Checkpoint::new(&self.db).context("Failed to create checkpoint object")?;

        checkpoint
            .create_checkpoint(checkpoint_path)
            .context("Failed to create checkpoint")
    }

    /// Get the database path location
    pub fn get_path(&self) -> &PathBuf {
        &self.path_location
    }

    /// Get current SST file names for tracking incremental changes
    pub fn get_sst_file_names(&self, cf_name: &str) -> Result<Vec<String>> {
        let live_files = self
            .db
            .live_files()
            .context("Failed to get live files metadata")?;

        Ok(live_files
            .into_iter()
            .filter(|f| f.column_family_name == cf_name)
            .map(|f| f.name)
            .collect())
    }

    /// Compare SST files between two sets to find differences
    pub fn compute_sst_delta(old_files: &[String], new_files: &[String]) -> SstDelta {
        let old_set: std::collections::HashSet<&String> = old_files.iter().collect();
        let new_set: std::collections::HashSet<&String> = new_files.iter().collect();

        let added_files: Vec<String> = new_set
            .difference(&old_set)
            .map(|s| s.to_string())
            .collect();

        let removed_files: Vec<String> = old_set
            .difference(&new_set)
            .map(|s| s.to_string())
            .collect();

        let unchanged_files: Vec<String> = old_set
            .intersection(&new_set)
            .map(|s| s.to_string())
            .collect();

        SstDelta {
            added_files,
            removed_files,
            unchanged_files,
        }
    }
}

/// Delta between two SST file sets
#[derive(Debug, Clone)]
pub struct SstDelta {
    pub added_files: Vec<String>,
    pub removed_files: Vec<String>,
    pub unchanged_files: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const TEST_CF: &str = "test_cf";

    fn create_test_store() -> (RocksDbStore, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let metrics = MetricsHelper::new().with_label("test", "true");
        let store = RocksDbStore::new(temp_dir.path(), vec![cf_descriptor], metrics).unwrap();
        (store, temp_dir)
    }

    #[test]
    fn test_store_creation() {
        let (store, _temp_dir) = create_test_store();

        // Verify we can get the column family handle
        let cf_handle = store.get_cf_handle(TEST_CF);
        assert!(cf_handle.is_ok());
    }

    #[test]
    fn test_put_and_multi_get() {
        let (store, _temp_dir) = create_test_store();

        let key1 = b"key1";
        let key2 = b"key2";
        let value1 = b"value1";
        let value2 = b"value2";

        // Put values
        store.put(TEST_CF, key1, value1).unwrap();
        store.put(TEST_CF, key2, value2).unwrap();

        // Multi-get
        let keys = vec![key1.as_slice(), key2.as_slice()];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), value1);
        assert_eq!(results[1].as_ref().unwrap(), value2);
    }

    #[test]
    fn test_multi_get_missing_keys() {
        let (store, _temp_dir) = create_test_store();

        let key1 = b"existing_key";
        let key2 = b"missing_key";
        let value1 = b"value1";

        // Put only one key
        store.put(TEST_CF, key1, value1).unwrap();

        // Multi-get both keys
        let keys = vec![key1.as_slice(), key2.as_slice()];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), value1);
        assert!(results[1].is_none());
    }

    #[test]
    fn test_put_batch() {
        let (store, _temp_dir) = create_test_store();

        let entries = vec![
            (b"key1".as_slice(), b"value1".as_slice()),
            (b"key2".as_slice(), b"value2".as_slice()),
            (b"key3".as_slice(), b"value3".as_slice()),
        ];

        // Batch put
        store.put_batch(TEST_CF, entries.clone()).unwrap();

        // Verify all entries were stored
        let keys: Vec<&[u8]> = entries.iter().map(|(k, _)| *k).collect();
        let results = store.multi_get(TEST_CF, keys).unwrap();

        for (i, (_, expected_value)) in entries.iter().enumerate() {
            assert_eq!(results[i].as_ref().unwrap(), expected_value);
        }
    }

    #[test]
    fn test_delete_range() {
        let (store, _temp_dir) = create_test_store();

        // Put some keys
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();
        store.put(TEST_CF, b"key3", b"value3").unwrap();
        store.put(TEST_CF, b"key4", b"value4").unwrap();

        // Delete range key2 to key4 (exclusive)
        store.delete_range(TEST_CF, b"key2", b"key4").unwrap();

        // Check what remains
        let keys = vec![
            b"key1".as_slice(),
            b"key2".as_slice(),
            b"key3".as_slice(),
            b"key4".as_slice(),
        ];
        let results = store.multi_get(TEST_CF, keys).unwrap();

        assert!(results[0].is_some()); // key1 should remain
        assert!(results[1].is_none()); // key2 should be deleted
        assert!(results[2].is_none()); // key3 should be deleted
        assert!(results[3].is_some()); // key4 should remain (exclusive end)
    }

    #[test]
    fn test_invalid_column_family() {
        let (store, _temp_dir) = create_test_store();

        let result = store.put("nonexistent_cf", b"key", b"value");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Column family not found"));
    }

    #[test]
    fn test_empty_multi_get() {
        let (store, _temp_dir) = create_test_store();

        let keys: Vec<&[u8]> = vec![];
        let results = store.multi_get(TEST_CF, keys).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn test_empty_put_batch() {
        let (store, _temp_dir) = create_test_store();

        let entries: Vec<(&[u8], &[u8])> = vec![];
        let result = store.put_batch(TEST_CF, entries);
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_checkpoint() {
        let (store, _temp_dir) = create_test_store();

        // Add some data
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();

        // Create checkpoint
        let checkpoint_dir = TempDir::new().unwrap();
        let checkpoint_path = checkpoint_dir.path().join("checkpoint");

        let result = store.create_checkpoint(&checkpoint_path);
        assert!(result.is_ok());

        // Verify checkpoint directory was created and contains data
        assert!(checkpoint_path.exists());
        assert!(checkpoint_path.is_dir());
    }

    #[test]
    fn test_checkpoint_recovery() {
        let temp_dir = TempDir::new().unwrap();
        let original_path = temp_dir.path().join("original");
        let checkpoint_path = temp_dir.path().join("checkpoint");

        // Create original store and add data
        {
            let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
            let original_store =
                RocksDbStore::new(&original_path, vec![cf_descriptor], MetricsHelper::new())
                    .unwrap();

            original_store.put(TEST_CF, b"key1", b"value1").unwrap();
            original_store.put(TEST_CF, b"key2", b"value2").unwrap();

            // Create checkpoint
            original_store.create_checkpoint(&checkpoint_path).unwrap();
        } // Drop original store

        // Open new store from checkpoint
        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let recovered_store =
            RocksDbStore::new(&checkpoint_path, vec![cf_descriptor], MetricsHelper::new()).unwrap();

        // Verify data is recovered
        let keys = vec![b"key1".as_slice(), b"key2".as_slice()];
        let results = recovered_store.multi_get(TEST_CF, keys).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].as_ref().unwrap(), b"value1");
        assert_eq!(results[1].as_ref().unwrap(), b"value2");
    }

    #[test]
    fn test_get_sst_file_names() {
        let (store, _temp_dir) = create_test_store();

        // Add some data to create SST files
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();

        // Force flush to create SST files
        store.flush_cf(TEST_CF).unwrap();

        // Get SST file names
        let sst_files = store.get_sst_file_names(TEST_CF).unwrap();

        // Should have at least one SST file after flush
        assert!(!sst_files.is_empty());

        // All file names should end with .sst
        for file_name in &sst_files {
            assert!(file_name.ends_with(".sst"));
        }
    }

    #[test]
    fn test_compute_sst_delta() {
        let old_files = vec![
            "000001.sst".to_string(),
            "000002.sst".to_string(),
            "000003.sst".to_string(),
        ];

        let new_files = vec![
            "000002.sst".to_string(), // unchanged
            "000003.sst".to_string(), // unchanged
            "000004.sst".to_string(), // added
            "000005.sst".to_string(), // added
        ];

        let delta = RocksDbStore::compute_sst_delta(&old_files, &new_files);

        assert_eq!(delta.added_files.len(), 2);
        assert!(delta.added_files.contains(&"000004.sst".to_string()));
        assert!(delta.added_files.contains(&"000005.sst".to_string()));

        assert_eq!(delta.removed_files.len(), 1);
        assert!(delta.removed_files.contains(&"000001.sst".to_string()));

        assert_eq!(delta.unchanged_files.len(), 2);
        assert!(delta.unchanged_files.contains(&"000002.sst".to_string()));
        assert!(delta.unchanged_files.contains(&"000003.sst".to_string()));
    }

    #[test]
    fn test_sst_delta_tracking_with_checkpoints() {
        let temp_dir = TempDir::new().unwrap();
        let db_path = temp_dir.path().join("db");
        let checkpoint1_path = temp_dir.path().join("checkpoint1");
        let checkpoint2_path = temp_dir.path().join("checkpoint2");

        let cf_descriptor = ColumnFamilyDescriptor::new(TEST_CF, Options::default());
        let store = RocksDbStore::new(&db_path, vec![cf_descriptor], MetricsHelper::new()).unwrap();

        // Phase 1: Add initial data
        store.put(TEST_CF, b"key1", b"value1").unwrap();
        store.put(TEST_CF, b"key2", b"value2").unwrap();
        store.flush_cf(TEST_CF).unwrap();

        let sst_files_phase1 = store.get_sst_file_names(TEST_CF).unwrap();
        store.create_checkpoint(&checkpoint1_path).unwrap();

        // Phase 2: Add more data
        store.put(TEST_CF, b"key3", b"value3").unwrap();
        store.put(TEST_CF, b"key4", b"value4").unwrap();
        store.flush_cf(TEST_CF).unwrap();

        let sst_files_phase2 = store.get_sst_file_names(TEST_CF).unwrap();
        store.create_checkpoint(&checkpoint2_path).unwrap();

        // Compute delta between phases
        let delta = RocksDbStore::compute_sst_delta(&sst_files_phase1, &sst_files_phase2);

        // Should have some changes (either added files or unchanged files)
        // The exact number depends on compaction behavior, but total should be consistent
        let total_delta_files =
            delta.added_files.len() + delta.unchanged_files.len() + delta.removed_files.len();
        let total_phase2_files = sst_files_phase2.len();

        // Delta should account for all files in phase2 (either added or unchanged)
        assert!(total_delta_files >= total_phase2_files || sst_files_phase2.is_empty());
    }
}
