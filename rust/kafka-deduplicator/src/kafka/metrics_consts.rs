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
