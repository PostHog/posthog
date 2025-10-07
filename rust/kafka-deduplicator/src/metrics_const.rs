// ==== Deduplication-specific metrics ====
/// Counter for the number of duplicate events found
pub const DUPLICATE_EVENTS_TOTAL_COUNTER: &str = "duplicate_events_total";

/// Counter for the number of unique events processed
pub const UNIQUE_EVENTS_TOTAL_COUNTER: &str = "unique_events_total";

/// Counter for deduplication results broken down by result type, dedup type, and reason
pub const DEDUPLICATION_RESULT_COUNTER: &str = "deduplication_result_total";

/// Histogram for batch processing duration
pub const BATCH_PROCESSING_DURATION_HISTOGRAM: &str = "batch_processing_duration_seconds";

/// Histogram for batch size (number of events per batch)
pub const BATCH_SIZE_HISTOGRAM: &str = "batch_size_events";

/// Gauge for duplicate rate (percentage of duplicates in last batch)
pub const DUPLICATE_RATE_GAUGE: &str = "duplicate_rate_percentage";

// ==== Timestamp deduplication metrics ====
/// Histogram for number of unique UUIDs seen for the same timestamp
pub const TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM: &str = "timestamp_dedup_unique_uuids";

/// Histogram for similarity score in timestamp deduplication
pub const TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM: &str = "timestamp_dedup_similarity_score";

/// Histogram for number of different fields in timestamp deduplication
pub const TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM: &str = "timestamp_dedup_different_fields";

/// Histogram for number of different properties in timestamp deduplication
pub const TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM: &str =
    "timestamp_dedup_different_properties";

/// Histogram for properties similarity score in timestamp deduplication
pub const TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM: &str =
    "timestamp_dedup_properties_similarity_score";

/// Counter for specific fields that differ in timestamp deduplication
pub const TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER: &str =
    "timestamp_dedup_field_differences_total";

// ==== UUID deduplication metrics ====
/// Histogram for timestamp variance in milliseconds for UUID duplicates
pub const UUID_DEDUP_TIMESTAMP_VARIANCE_HISTOGRAM: &str = "uuid_dedup_timestamp_variance_ms";

/// Histogram for number of unique timestamps seen for the same UUID
pub const UUID_DEDUP_UNIQUE_TIMESTAMPS_HISTOGRAM: &str = "uuid_dedup_unique_timestamps";

/// Histogram for similarity score in UUID deduplication
pub const UUID_DEDUP_SIMILARITY_SCORE_HISTOGRAM: &str = "uuid_dedup_similarity_score";

/// Histogram for number of different fields in UUID deduplication
pub const UUID_DEDUP_DIFFERENT_FIELDS_HISTOGRAM: &str = "uuid_dedup_different_fields";

/// Histogram for number of different properties in UUID deduplication
pub const UUID_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM: &str = "uuid_dedup_different_properties";

/// Histogram for properties similarity score in UUID deduplication
pub const UUID_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM: &str =
    "uuid_dedup_properties_similarity_score";

/// Counter for specific fields that differ in UUID deduplication
pub const UUID_DEDUP_FIELD_DIFFERENCES_COUNTER: &str = "uuid_dedup_field_differences_total";

// ==== Cleanup operations metrics ====
/// Counter for cleanup operations performed
pub const CLEANUP_OPERATIONS_COUNTER: &str = "cleanup_operations_total";

/// Histogram for cleanup duration
pub const CLEANUP_DURATION_HISTOGRAM: &str = "cleanup_duration_seconds";

/// Histogram for bytes freed during cleanup
pub const CLEANUP_BYTES_FREED_HISTOGRAM: &str = "cleanup_bytes_freed";

/// Histogram for checkpoint size in bytes
pub const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";

/// Histogram for checkpoint file count
pub const CHECKPOINT_FILE_COUNT_HISTOGRAM: &str = "checkpoint_file_count";

/// Histogram for checkpoint duration in seconds
pub const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";

/// Counter for checkpoint worker status
pub const CHECKPOINT_WORKER_STATUS_COUNTER: &str = "checkpoint_worker_status";

/// Counter for the number of checkpoint directories found
pub const CHECKPOINT_CLEANER_DIRS_FOUND: &str = "checkpoint_cleaner_dirs_found";

/// Counter for the number of checkpoint directories deleted
pub const CHECKPOINT_CLEANER_DELETE_ATTEMPTS: &str = "checkpoint_cleaner_delete_attempts";

/// Counts number of times a StoreManager lookup by partition
/// finds no associated DeduplicationStore, meaning ownership
/// has changed across a rebalance or other event asynchronously
pub const CHECKPOINT_STORE_NOT_FOUND_COUNTER: &str = "checkpoint_store_not_found";
