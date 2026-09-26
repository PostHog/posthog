// ==== Deduplication-specific metrics ====
/// Tags: topic, status=success|failure
pub const DUPLICATE_EVENTS_PUBLISHED_COUNTER: &str = "duplicate_events_published_total";

pub const PRODUCER_SEND_DURATION_HISTOGRAM: &str = "producer_send_duration_seconds";

/// Tags: pipeline, result_type, and optionally reason and lib
pub const DEDUPLICATION_RESULT_COUNTER: &str = "deduplication_result_total";

pub const BATCH_PROCESSING_DURATION_HISTOGRAM: &str = "batch_processing_duration_seconds";

pub const BATCH_SIZE_HISTOGRAM: &str = "batch_size_events";

/// Percentage of duplicates in the last batch only, not a running rate
pub const DUPLICATE_RATE_GAUGE: &str = "duplicate_rate_percentage";

// ==== Timestamp deduplication metrics ====
pub const TIMESTAMP_DEDUP_UNIQUE_UUIDS_HISTOGRAM: &str = "timestamp_dedup_unique_uuids";

pub const TIMESTAMP_DEDUP_SIMILARITY_SCORE_HISTOGRAM: &str = "timestamp_dedup_similarity_score";

pub const TIMESTAMP_DEDUP_DIFFERENT_FIELDS_HISTOGRAM: &str = "timestamp_dedup_different_fields";

pub const TIMESTAMP_DEDUP_DIFFERENT_PROPERTIES_HISTOGRAM: &str =
    "timestamp_dedup_different_properties";

pub const TIMESTAMP_DEDUP_PROPERTIES_SIMILARITY_HISTOGRAM: &str =
    "timestamp_dedup_properties_similarity_score";

pub const TIMESTAMP_DEDUP_FIELD_DIFFERENCES_COUNTER: &str =
    "timestamp_dedup_field_differences_total";

// ==== Cleanup operations metrics ====
pub const CLEANUP_OPERATIONS_COUNTER: &str = "cleanup_operations_total";

pub const CLEANUP_DURATION_HISTOGRAM: &str = "cleanup_duration_seconds";

pub const CLEANUP_BYTES_FREED_HISTOGRAM: &str = "cleanup_bytes_freed";

pub const CHECKPOINT_SIZE_HISTOGRAM: &str = "checkpoint_size_bytes";

pub const CHECKPOINT_FILE_COUNT_HISTOGRAM: &str = "checkpoint_file_count";

pub const CHECKPOINT_DURATION_HISTOGRAM: &str = "checkpoint_duration_seconds";

/// Tags: result=success|error|skipped, cause=..., export=...
pub const CHECKPOINT_WORKER_STATUS_COUNTER: &str = "checkpoint_worker_status";

/// Tags: result=success|error|cancelled
/// When result=cancelled, additional tag: cause=rebalance|shutdown|unknown
pub const CHECKPOINT_UPLOAD_DURATION_HISTOGRAM: &str = "checkpoint_upload_duration_seconds";

/// Tags: result=success|error|cancelled|unavailable
/// When result=cancelled, additional tag: cause=rebalance|shutdown|unknown
pub const CHECKPOINT_UPLOADS_COUNTER: &str = "checkpoint_upload_status";

/// Tags: status=success|error|cancelled
pub const CHECKPOINT_FILE_DOWNLOADS_COUNTER: &str = "checkpoint_file_downloads_status";

/// Tags: status=success|error|cancelled
pub const CHECKPOINT_FILE_UPLOADS_COUNTER: &str = "checkpoint_file_uploads_status";

/// Tags: file=added|replaced|retained
pub const CHECKPOINT_PLAN_FILE_TRACKED_COUNTER: &str = "checkpoint_plan_file_tracked";

/// Only measured on success
pub const CHECKPOINT_FILE_FETCH_HISTOGRAM: &str = "checkpoint_file_fetch_seconds";

/// Only measured on success.
/// The individual file ops are parallelized - we're measuring total elapsed time for the fanout
pub const CHECKPOINT_BATCH_FETCH_STORE_HISTOGRAM: &str =
    "checkpoint_batch_file_fetch_and_store_seconds";

/// Only measured on success
pub const CHECKPOINT_FILE_FETCH_STORE_HISTOGRAM: &str = "checkpoint_file_fetch_and_store_seconds";

/// Only measured on success
pub const CHECKPOINT_LIST_METADATA_HISTOGRAM: &str = "checkpoint_list_metadata_seconds";

/// This measures the end-to-end time for import_checkpoint_for_topic_partition_cancellable,
/// including listing checkpoints, downloading metadata files, downloading all SST files,
/// and any fallback attempts. Tags: result=success|failed|cancelled|timeout
pub const CHECKPOINT_IMPORT_DURATION_HISTOGRAM: &str = "checkpoint_import_duration_seconds";

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
pub const STORE_CREATION_DURATION_MS: &str = "store_creation_duration_ms";

/// Tags: outcome=success|failure|duplicate_on_restore
pub const STORE_CREATION_EVENTS: &str = "store_creation_events_total";

pub const ACTIVE_STORE_COUNT: &str = "active_store_count";

/// Value > 0 means rebalance async work is ongoing; used to block orphan cleanup
pub const REBALANCING_COUNT: &str = "rebalancing_count";

// ==== Partition Ownership Tracking ====

/// Updated on every ownership change for real-time visibility
pub const OWNED_PARTITIONS_COUNT: &str = "owned_partitions_count";

/// Incremented from the ASSIGN callback
pub const PARTITION_OWNERSHIP_ADDED: &str = "partition_ownership_added_total";

/// Incremented from the REVOKE callback
pub const PARTITION_OWNERSHIP_REMOVED: &str = "partition_ownership_removed_total";

/// Labels: topic, partition, op (assign|revoke)
/// Use this to track rebalance activity per partition for debugging and alerting
pub const REBALANCE_PARTITION_STATE_CHANGE: &str = "rebalance_partition_state_change_total";

/// Incremented when a new rebalance starts before async setup completes
pub const REBALANCE_ASYNC_SETUP_CANCELLED: &str = "rebalance_async_setup_cancelled_total";

/// Counter for partitions skipped during store creation (no longer owned)
/// Labels: reason (not_owned, cancelled)
pub const PARTITION_STORE_SETUP_SKIPPED: &str = "partition_store_setup_skipped_total";

/// Counter for partitions where checkpoint import failed and we fell back to empty store
/// Labels: reason (no_importer | import_failed | import_cancelled | unknown)
/// This is an important metric for alerting - indicates degraded deduplication quality
pub const PARTITION_STORE_FALLBACK_EMPTY: &str = "partition_store_fallback_empty_total";

/// Counter for local store restore attempts during rebalance.
/// Labels: result (fresh | stale | missing | corrupt)
/// `fresh` means local metadata was valid and S3 import was skipped.
pub const LOCAL_STORE_RESTORE_COUNTER: &str = "local_store_restore_total";

/// Counter for messages dropped because no store was registered for the partition
/// Labels: topic, partition
/// This is expected during rebalances due to rdkafka message buffering
pub const MESSAGES_DROPPED_NO_STORE: &str = "messages_dropped_no_store_total";

/// Excludes expected store-not-found errors
/// Labels: topic, partition, error_type
pub const BATCH_PROCESSING_ERROR: &str = "batch_processing_error_total";

// ==== Rebalance Resume ====

pub const REBALANCE_RESUME_SKIPPED_NO_OWNED: &str = "rebalance_resume_skipped_no_owned_total";

/// Labels: event_type (assign|revoke)
/// With cooperative-sticky protocol, the broker triggers rebalances for all consumers
/// when any group membership changes, even if partitions don't move. This tracks
/// how many of these empty rebalances we short-circuit.
pub const REBALANCE_EMPTY_SKIPPED: &str = "rebalance_empty_skipped_total";

/// Measures total time for parallel scatter-gather deletion of unowned partition directories.
/// Use to monitor cleanup performance and detect I/O bottlenecks blocking consumption resume.
pub const REBALANCE_DIRECTORY_CLEANUP_DURATION_HISTOGRAM: &str =
    "rebalance_directory_cleanup_duration_seconds";

// ==== Partition Batch Processing Diagnostics ====
pub const PARTITION_BATCH_PROCESSING_DURATION_MS: &str = "partition_batch_processing_duration_ms";

pub const ROCKSDB_MULTI_GET_DURATION_MS: &str = "rocksdb_multi_get_duration_ms";

pub const ROCKSDB_PUT_BATCH_DURATION_MS: &str = "rocksdb_put_batch_duration_ms";

pub const KAFKA_PRODUCER_SEND_DURATION_MS: &str = "kafka_producer_send_duration_ms";

/// Parsing is fanned out over rayon, so this is total elapsed time, not CPU time
pub const EVENT_PARSING_DURATION_MS: &str = "event_parsing_duration_ms";

// ==== Fail-open mode metrics ====
/// Counts events forwarded with deduplication bypassed
pub const FAIL_OPEN_EVENTS_PASSED_THROUGH: &str = "fail_open_events_passed_through_total";
