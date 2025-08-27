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

// ==== Kafka Consumer metrics ====
/// Gauge for number of messages currently being processed
pub const KAFKA_CONSUMER_IN_FLIGHT_MESSAGES: &str = "kafka_consumer_in_flight_messages";

/// Gauge for total memory used by in-flight messages (bytes)
pub const KAFKA_CONSUMER_IN_FLIGHT_MEMORY_BYTES: &str = "kafka_consumer_in_flight_memory_bytes";

// ==== Partition Health metrics ====
/// Gauge for pending completions per partition (queue depth)
pub const PARTITION_PENDING_COMPLETIONS: &str = "kafka_partition_pending_completions";

/// Gauge for the offset gap size when gaps are detected
pub const PARTITION_OFFSET_GAP_SIZE: &str = "kafka_partition_offset_gap_size";

/// Counter for offset gap detection events
pub const PARTITION_OFFSET_GAP_DETECTED: &str = "kafka_partition_offset_gap_detected_total";

/// Gauge for seconds since last successful commit per partition
pub const PARTITION_SECONDS_SINCE_LAST_COMMIT: &str = "kafka_partition_seconds_since_last_commit";

/// Counter for messages that were auto-nacked due to being dropped
pub const MESSAGES_AUTO_NACKED: &str = "kafka_messages_auto_nacked_total";

/// Histogram for message completion processing time
pub const MESSAGE_COMPLETION_DURATION: &str = "kafka_message_completion_duration_seconds";

/// Gauge for the highest committed offset per partition
pub const PARTITION_LAST_COMMITTED_OFFSET: &str = "kafka_partition_last_committed_offset";

/// Counter for out-of-order completions
pub const OUT_OF_ORDER_COMPLETIONS: &str = "kafka_out_of_order_completions_total";
