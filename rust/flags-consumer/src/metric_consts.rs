// Metric name constants for the flags CDC consumer.
//
// Convention: `flags_cdc_{domain}_{metric_name}` with low-cardinality labels.

pub const MESSAGES_RECEIVED: &str = "flags_cdc_messages_received_total";
pub const MESSAGES_PROCESSED: &str = "flags_cdc_messages_processed_total";
pub const MESSAGES_FILTERED: &str = "flags_cdc_messages_filtered_total";
pub const MESSAGES_SKIPPED: &str = "flags_cdc_messages_skipped_total";

pub const BATCH_SIZE: &str = "flags_cdc_batch_size";
pub const BATCH_PROCESS_DURATION_MS: &str = "flags_cdc_batch_process_duration_ms";

pub const DB_QUERY_DURATION_MS: &str = "flags_cdc_db_query_duration_ms";
pub const DB_RETRIES: &str = "flags_cdc_db_retries_total";
pub const DB_ERRORS: &str = "flags_cdc_db_errors_total";

pub const KAFKA_ERRORS: &str = "flags_cdc_kafka_errors_total";
pub const HEARTBEAT_WRITES: &str = "flags_cdc_heartbeat_writes_total";
