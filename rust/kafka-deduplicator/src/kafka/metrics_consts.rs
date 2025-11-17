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

/// rdkafka consumption errors received
pub const BATCH_CONSUMER_KAFKA_ERRORS: &str = "kafka_batch_consumer_kafka_errors";
