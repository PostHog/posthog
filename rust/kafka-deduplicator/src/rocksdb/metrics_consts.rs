// ==== RocksDB generic metrics ====
/// Histogram for RocksDB read operation duration
pub const ROCKSDB_READ_DURATION_HISTOGRAM: &str = "rocksdb_read_duration_seconds";

/// Histogram for RocksDB write operation duration
pub const ROCKSDB_WRITE_DURATION_HISTOGRAM: &str = "rocksdb_write_duration_seconds";

/// Histogram for RocksDB multi_get operation duration
pub const ROCKSDB_MULTI_GET_DURATION_HISTOGRAM: &str = "rocksdb_multi_get_duration_seconds";

/// Histogram for RocksDB batch write operation duration
pub const ROCKSDB_BATCH_WRITE_DURATION_HISTOGRAM: &str = "rocksdb_batch_write_duration_seconds";

/// Histogram for RocksDB batch size
pub const ROCKSDB_BATCH_SIZE_HISTOGRAM: &str = "rocksdb_batch_size";

/// Gauge for current database size in bytes
pub const ROCKSDB_SIZE_BYTES_GAUGE: &str = "rocksdb_size_bytes";

/// Counter for RocksDB read operations
pub const ROCKSDB_READ_OPERATIONS_COUNTER: &str = "rocksdb_read_operations_total";

/// Counter for RocksDB write operations
pub const ROCKSDB_WRITE_OPERATIONS_COUNTER: &str = "rocksdb_write_operations_total";

/// Counter for RocksDB batch write operations
pub const ROCKSDB_BATCH_WRITE_OPERATIONS_COUNTER: &str = "rocksdb_batch_write_operations_total";

/// Histogram for RocksDB flush operation duration
pub const ROCKSDB_FLUSH_DURATION_HISTOGRAM: &str = "rocksdb_flush_duration_seconds";

/// Histogram for RocksDB compaction operation duration
pub const ROCKSDB_COMPACTION_DURATION_HISTOGRAM: &str = "rocksdb_compaction_duration_seconds";

/// Histogram for RocksDB checkpoint creation duration
pub const ROCKSDB_CHECKPOINT_DURATION_HISTOGRAM: &str = "rocksdb_checkpoint_duration_seconds";

/// Counter for RocksDB checkpoint operations
pub const ROCKSDB_CHECKPOINT_OPERATIONS_COUNTER: &str = "rocksdb_checkpoint_operations_total";

/// Gauge for number of SST files
pub const ROCKSDB_SST_FILES_COUNT_GAUGE: &str = "rocksdb_sst_files_count";

/// Counter for RocksDB errors
pub const ROCKSDB_ERRORS_COUNTER: &str = "rocksdb_errors_total";
