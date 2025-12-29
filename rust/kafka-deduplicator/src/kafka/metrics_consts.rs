// ==== Kafka Consumer metrics ====
/// Gauge for number of messages currently being processed
pub const KAFKA_CONSUMER_IN_FLIGHT_MESSAGES: &str = "kafka_consumer_in_flight_messages";

/// Gauge for total memory used by in-flight messages (bytes)
pub const KAFKA_CONSUMER_IN_FLIGHT_MEMORY_BYTES: &str = "kafka_consumer_in_flight_memory_bytes";

/// Gauge for available permits in the semaphore controlling concurrent processing
pub const KAFKA_CONSUMER_AVAILABLE_PERMITS: &str = "kafka_consumer_available_permits";

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

/// Counter for message completions with status label (acked/nacked/auto_nacked)
pub const MESSAGES_COMPLETED: &str = "kafka_messages_completed_total";

/// Histogram for message processing duration in milliseconds (from receipt to ack/nack)
pub const MESSAGE_COMPLETION_DURATION: &str = "kafka_message_processing_duration_ms";

/// Gauge for the highest committed offset per partition
pub const PARTITION_LAST_COMMITTED_OFFSET: &str = "kafka_partition_last_committed_offset";

/// Counter for out-of-order completions
pub const OUT_OF_ORDER_COMPLETIONS: &str = "kafka_out_of_order_completions_total";

/// Counter for messages force-cleared during partition revocation
pub const MESSAGES_FORCE_CLEARED: &str = "kafka_messages_force_cleared_total";

/// Counter for completion channel send failures
pub const COMPLETION_CHANNEL_FAILURES: &str = "kafka_completion_channel_failures_total";

/// Counter for messages skipped from revoked partitions
pub const MESSAGES_SKIPPED_REVOKED: &str = "kafka_messages_skipped_revoked_total";

/// Counter for messages received by the batch consumer, tagged by deserialization status
pub const BATCH_CONSUMER_MESSAGES_RECEIVED: &str = "kafka_batch_consumer_messages_received";

/// Histogram for the number of messages per batch processed by the batch consumer
pub const BATCH_CONSUMER_BATCH_SIZE: &str = "kafka_batch_consumer_batch_size";

/// rdkafka consumption errors received
pub const BATCH_CONSUMER_KAFKA_ERROR: &str = "kafka_batch_consumer_kafka_error";

pub const BATCH_CONSUMER_MESSAGE_ERROR: &str = "kafka_batch_consumer_message_error";

/// Histogram for batch fill ratio (actual batch size / max batch size)
/// Values range from 0.0 to 1.0, where 1.0 means batch was full
pub const BATCH_CONSUMER_BATCH_FILL_RATIO: &str = "kafka_batch_consumer_batch_fill_ratio";

/// Histogram for time spent collecting a batch (in milliseconds)
/// Measures latency from start of batch collection to batch ready for processing
pub const BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS: &str =
    "kafka_batch_consumer_batch_collection_duration_ms";

// ==== Partition Worker metrics ====
/// Counter for partition worker channel backpressure events
/// Incremented when route_batch has to wait because the worker channel is full
pub const PARTITION_WORKER_BACKPRESSURE_TOTAL: &str = "kafka_partition_worker_backpressure_total";

/// Histogram for time spent waiting due to partition worker backpressure (in milliseconds)
pub const PARTITION_WORKER_BACKPRESSURE_WAIT_MS: &str =
    "kafka_partition_worker_backpressure_wait_ms";

// ==== Offset Tracker metrics ====
/// Counter for out-of-order batch processing events
/// Incremented when a batch completes with a batch_id lower than or equal to the last processed batch_id
pub const OFFSET_TRACKER_OUT_OF_ORDER_BATCH: &str = "kafka_offset_tracker_out_of_order_batch_total";

/// Counter for offset commits skipped during rebalancing
pub const OFFSET_TRACKER_COMMITS_SKIPPED_REBALANCING: &str =
    "kafka_offset_tracker_commits_skipped_rebalancing_total";
