//! Metric name constants for the preprocess pipeline, kept in one place so the
//! vocabulary stays aligned with the Node.js ingestion pipeline.

/// Per-header presence counter emitted while parsing Kafka event headers.
/// Labels: `header`, `status` (`present`/`absent`). Mirrors the Node.js
/// `kafka_header_status_total` metric.
pub const KAFKA_HEADER_STATUS: &str = "kafka_header_status_total";

/// Dry-run verdicts: what the preprocess pipeline *would* have done, without
/// enforcing it. Labels: `step`, `result` (`drop`/`dlq`/`redirect`), `details`.
pub const PREPROCESS_DRYRUN_RESULTS: &str = "ingestion_preprocess_dryrun_results";

/// Count of messages the preprocess pipeline rerouted to the overflow topic.
/// Mirrors the Node.js `ingestion_overflowing_messages_total`.
pub const OVERFLOWING_MESSAGES: &str = "ingestion_overflowing_messages_total";
