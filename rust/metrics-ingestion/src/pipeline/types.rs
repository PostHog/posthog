use std::sync::Arc;

use ingestion_framework::{HasMessage, Headers, KafkaMessage};

pub const METRICS_OUTPUT: &str = "metrics";
/// Metrics has no per-team retention. ClickHouse applies its own default only when the header is missing.
pub const DEFAULT_METRICS_RETENTION_DAYS: u32 = 30;
pub const QUOTA_RESOURCE: &str = "metrics_mb_ingested";

#[derive(Debug, Clone)]
pub struct MetricsPipelineInput {
    pub message: Arc<KafkaMessage>,
}

/// `MetricsMessageContext`. Result handling reads the message from it for the DLQ.
#[derive(Debug, Clone)]
pub struct MetricsMessageContext {
    pub message: Arc<KafkaMessage>,
}

impl HasMessage for MetricsMessageContext {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}

/// The size headers, each a non-negative safe integer.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct MetricsSizes {
    pub bytes_uncompressed: u64,
    /// Sum of per-point sizes from `bytes_uncompressed_records`. 0 for batches from older producers.
    pub bytes_uncompressed_records: u64,
    pub bytes_compressed: u64,
    pub record_count: u64,
}

#[derive(Debug, Clone)]
pub struct MetricsIngestionMessage {
    pub message: Arc<KafkaMessage>,
    pub kafka_headers: Headers,
    pub token: String,
    pub team_id: i64,
    pub sizes: MetricsSizes,
}
