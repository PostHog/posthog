// ==== Deduplication-specific metrics ====
/// Counter for the number of duplicate events found
pub const DUPLICATE_EVENTS_TOTAL_COUNTER: &str = "duplicate_events_total";

/// Counter for the number of unique events processed
pub const UNIQUE_EVENTS_TOTAL_COUNTER: &str = "unique_events_total";

/// Histogram for batch processing duration
pub const BATCH_PROCESSING_DURATION_HISTOGRAM: &str = "batch_processing_duration_seconds";

/// Histogram for batch size (number of events per batch)
pub const BATCH_SIZE_HISTOGRAM: &str = "batch_size_events";

/// Gauge for duplicate rate (percentage of duplicates in last batch)
pub const DUPLICATE_RATE_GAUGE: &str = "duplicate_rate_percentage";

/// Counter for cleanup operations performed
pub const CLEANUP_OPERATIONS_COUNTER: &str = "cleanup_operations_total";

/// Histogram for cleanup duration
pub const CLEANUP_DURATION_HISTOGRAM: &str = "cleanup_duration_seconds";

/// Histogram for bytes freed during cleanup
pub const CLEANUP_BYTES_FREED_HISTOGRAM: &str = "cleanup_bytes_freed";

// ==== RocksDB generic metrics ====
/// Histogram for RocksDB read operation duration
pub const ROCKSDB_READ_DURATION_HISTOGRAM: &str = "rocksdb_read_duration_seconds";

/// Histogram for RocksDB write operation duration
pub const ROCKSDB_WRITE_DURATION_HISTOGRAM: &str = "rocksdb_write_duration_seconds";

/// Histogram for RocksDB multi_get operation duration
pub const ROCKSDB_MULTI_GET_DURATION_HISTOGRAM: &str = "rocksdb_multi_get_duration_seconds";

/// Histogram for RocksDB batch write operation duration
pub const ROCKSDB_BATCH_WRITE_DURATION_HISTOGRAM: &str = "rocksdb_batch_write_duration_seconds";

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
