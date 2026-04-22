// ==== Batch Consumer metrics ====
/// Counter for messages received by the batch consumer, tagged by deserialization status
pub const BATCH_CONSUMER_MESSAGES_RECEIVED: &str = "kafka_batch_consumer_messages_received";

/// Histogram for the number of messages per batch processed by the batch consumer
pub const BATCH_CONSUMER_BATCH_SIZE: &str = "kafka_batch_consumer_batch_size";

/// rdkafka consumption errors received
pub const BATCH_CONSUMER_KAFKA_ERROR: &str = "kafka_batch_consumer_kafka_error";

/// Histogram for batch fill ratio (actual batch size / max batch size)
/// Values range from 0.0 to 1.0, where 1.0 means batch was full
pub const BATCH_CONSUMER_BATCH_FILL_RATIO: &str = "kafka_batch_consumer_batch_fill_ratio";

/// Histogram for time spent collecting a batch (in milliseconds)
/// Measures latency from start of batch collection to batch ready for processing
pub const BATCH_CONSUMER_BATCH_COLLECTION_DURATION_MS: &str =
    "kafka_batch_consumer_batch_collection_duration_ms";

pub const BATCH_CONSUMER_SEEK_ERROR: &str = "kafka_batch_consumer_seek_error";
pub const BATCH_CONSUMER_SEEK_DURATION_MS: &str = "kafka_batch_consumer_seek_duration_ms";

// ==== Watermark Consumer metrics ====
/// Counter for messages received by the watermark consumer, tagged by deserialization status
pub const WATERMARK_CONSUMER_MESSAGES_RECEIVED: &str = "kafka_watermark_consumer_messages_received";
/// Counter for partitions that have reached high-watermark
pub const WATERMARK_CONSUMER_PARTITIONS_COMPLETED: &str =
    "kafka_watermark_consumer_partitions_completed_total";
/// rdkafka consumption errors received by the watermark consumer
pub const WATERMARK_CONSUMER_KAFKA_ERROR: &str = "kafka_watermark_consumer_kafka_error";
/// Messages received from partitions not in the original assignment
pub const WATERMARK_CONSUMER_UNEXPECTED_PARTITION: &str =
    "kafka_watermark_consumer_unexpected_partition_total";

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
