// ==== Deduplication-specific metrics ====
/// Counter for duplicate events published to Kafka (with status label: success/failure)
pub const DUPLICATE_EVENTS_PUBLISHED_COUNTER: &str = "duplicate_events_published_total";

/// Histogram for Kafka producer send duration
pub const PRODUCER_SEND_DURATION_HISTOGRAM: &str = "producer_send_duration_seconds";

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
/// Tags: result=success|error|skipped, cause=..., export=...
pub const CHECKPOINT_WORKER_STATUS_COUNTER: &str = "checkpoint_worker_status";

/// Histogram for checkpoint upload duration
/// Tags: result=success|error|cancelled
/// When result=cancelled, additional tag: cause=rebalance|shutdown|unknown
pub const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";

/// Counter for checkpoint upload outcome status
/// Tags: result=success|error|cancelled|unavailable
/// When result=cancelled, additional tag: cause=rebalance|shutdown|unknown
pub const CHECKPOINT_UPLOADS_COUNTER: &str = "checkpoint_upload_status";

/// Counter for checkpoint file downloads outcome status
/// Tags: status=success|error|cancelled
pub const CHECKPOINT_FILE_DOWNLOADS_COUNTER: &str = "checkpoint_file_downloads_status";

/// Counter for checkpoint file uploads outcome status
/// Tags: status=success|error|cancelled
pub const CHECKPOINT_FILE_UPLOADS_COUNTER: &str = "checkpoint_file_uploads_status";

/// Counter for checkpoint files tracked in each attempt plan tagged by action taken
pub const CHECKPOINT_PLAN_FILE_TRACKED_COUNTER: &str = "checkpoint_plan_file_tracked";

/// Histogram for checkpoint metadata file fetch duration; only measured on success
pub const CHECKPOINT_FILE_FETCH_HISTOGRAM: &str = "checkpoint_file_fetch_seconds";

/// Histogram for checkpoint total batch download_files duration; only measured on success.
/// The individual file ops are parallelized - we're measuring total elapsed time for the fanout
pub const CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM: &str =
    "checkpoint_batch_file_fetch_and_store_seconds";

/// Histogram for checkpoint file download and store duration; only measured on success
pub const CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM: &str = "checkpoint_file_fetch_and_store_seconds";

/// Histogram for checkpoint metadata file list duration; only measured on success
pub const CHECKPOINT_LIST_METADATA_HISTOGRAM: &str = "checkpoint_list_metadata_seconds";

/// Histogram for total checkpoint import duration from start to completion
/// This measures the end-to-end time for import_checkpoint_for_topic_partition_cancellable,
/// including listing checkpoints, downloading metadata files, downloading all SST files,
/// and any fallback attempts. Tags: result=success|failed|cancelled|timeout
pub const CHECKPOINT_IMPORT_DURATION_HISTOGRAM: &str = "checkpoint_import_duration_seconds";

/// Histogram for per-checkpoint-attempt duration during import
/// This measures the time for each individual checkpoint attempt (downloading one checkpoint's files).
/// Multiple attempts may occur if earlier checkpoints fail. Tags: result=success|failed
pub const CHECKPOINT_IMPORT_ATTEMPT_DURATION_HISTOGRAM: &str =
    "checkpoint_import_attempt_duration_seconds";

/// Record outcomes for attempts to restore checkpoints
/// when local store is missing after Kafka rebalances
pub const REBALANCE_CHECKPOINT_IMPORT_COUNTER: &str = "rebalance_checkpoint_import_total";

/// Counter for immediate cleanup of checkpoint imports after cancellation or ownership loss.
/// This counts directories cleaned up immediately rather than waiting for orphan cleaner.
/// Tags: result=success|failed
pub const CHECKPOINT_IMPORT_CANCELLED_CLEANUP_COUNTER: &str =
    "checkpoint_import_cancelled_cleanup_total";

// ==== Store Manager Diagnostics ====
/// Histogram for store creation duration (in milliseconds)
pub const STORE_CREATION_DURATION_MS: &str = "store_creation_duration_ms";

/// Counter for store creation events by outcome (success/failure)
pub const STORE_CREATION_EVENTS: &str = "store_creation_events_total";

/// Gauge for active store count
pub const ACTIVE_STORE_COUNT: &str = "active_store_count";

/// Gauge for number of overlapping rebalances in progress
/// Value > 0 means rebalance async work is ongoing; used to block orphan cleanup
pub const REBALANCING_COUNT: &str = "rebalancing_count";

// ==== Partition Ownership Tracking ====

/// Gauge for currently owned partition count
/// Updated on every ownership change for real-time visibility
pub const OWNED_PARTITIONS_COUNT: &str = "owned_partitions_count";

/// Counter for partitions added to ownership (ASSIGN callback)
pub const PARTITION_OWNERSHIP_ADDED: &str = "partition_ownership_added_total";

/// Counter for partitions removed from ownership (REVOKE callback)
pub const PARTITION_OWNERSHIP_REMOVED: &str = "partition_ownership_removed_total";

/// Counter for partition state changes from Kafka rebalance (assign/revoke)
/// Labels: topic, partition, op (assign|revoke)
/// Use this to track rebalance activity per partition for debugging and alerting
pub const REBALANCE_PARTITION_STATE_CHANGE: &str = "rebalance_partition_state_change_total";

/// Counter for async setup cancellations
/// Incremented when a new rebalance starts before async setup completes
pub const REBALANCE_ASYNC_SETUP_CANCELLED: &str = "rebalance_async_setup_cancelled_total";

/// Counter for partitions skipped during store creation (no longer owned)
/// Labels: reason (not_owned, cancelled)
pub const PARTITION_STORE_SETUP_SKIPPED: &str = "partition_store_setup_skipped_total";

/// Counter for partitions where checkpoint import failed and we fell back to empty store
/// Labels: reason (no_importer | import_failed | import_cancelled | unknown)
/// This is an important metric for alerting - indicates degraded deduplication quality
pub const PARTITION_STORE_FALLBACK_EMPTY: &str = "partition_store_fallback_empty_total";

/// Counter for messages dropped because no store was registered for the partition
/// Labels: topic, partition
/// This is expected during rebalances due to rdkafka message buffering
pub const MESSAGES_DROPPED_NO_STORE: &str = "messages_dropped_no_store_total";

/// Counter for batch processing errors (excluding expected store-not-found errors)
/// Labels: topic, partition, error_type
pub const BATCH_PROCESSING_ERROR: &str = "batch_processing_error_total";

// ==== Rebalance Resume ====

/// Counter for Resume commands skipped entirely (no owned partitions)
pub const REBALANCE_RESUME_SKIPPED_NO_OWNED: &str = "rebalance_resume_skipped_no_owned_total";

/// Counter for empty rebalances skipped (cooperative-sticky no-ops)
/// Labels: event_type (assign|revoke)
/// With cooperative-sticky protocol, the broker triggers rebalances for all consumers
/// when any group membership changes, even if partitions don't move. This tracks
/// how many of these empty rebalances we short-circuit.
pub const REBALANCE_EMPTY_SKIPPED: &str = "rebalance_empty_skipped_total";

/// Histogram for partition directory cleanup duration at end of rebalance cycle.
/// Measures total time for parallel scatter-gather deletion of unowned partition directories.
/// Use to monitor cleanup performance and detect I/O bottlenecks blocking consumption resume.
pub const REBALANCE_DIRECTORY_CLEANUP_DURATION_HISTOGRAM: &str =
    "rebalance_directory_cleanup_duration_seconds";

// ==== Partition Batch Processing Diagnostics ====
/// Histogram for partition batch processing duration (in milliseconds)
pub const PARTITION_BATCH_PROCESSING_DURATION_MS: &str = "partition_batch_processing_duration_ms";

/// Histogram for RocksDB multi_get duration (in milliseconds)
pub const ROCKSDB_MULTI_GET_DURATION_MS: &str = "rocksdb_multi_get_duration_ms";

/// Histogram for RocksDB put_batch duration (in milliseconds)
pub const ROCKSDB_PUT_BATCH_DURATION_MS: &str = "rocksdb_put_batch_duration_ms";

/// Histogram for Kafka producer send duration (in milliseconds)
pub const KAFKA_PRODUCER_SEND_DURATION_MS: &str = "kafka_producer_send_duration_ms";

/// Histogram for event parsing duration using rayon (in milliseconds)
pub const EVENT_PARSING_DURATION_MS: &str = "event_parsing_duration_ms";

// ==== Fail-open mode metrics ====
/// Counter for events passed through in fail-open mode (deduplication bypassed)
pub const FAIL_OPEN_EVENTS_PASSED_THROUGH: &str = "fail_open_events_passed_through_total";
