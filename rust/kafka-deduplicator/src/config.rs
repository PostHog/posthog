use std::{fs, path::PathBuf, time::Duration};

use anyhow::{Context, Result};
use bytesize::ByteSize;
use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

/// Pipeline type for the deduplicator service.
///
/// Each pipeline type handles a different event format:
/// - `IngestionEvents`: Events from capture (CapturedEvent/RawEvent format)
/// - `ClickhouseEvents`: Events from ingestion pipeline (ClickhouseEvent format)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, strum_macros::EnumString)]
#[strum(serialize_all = "snake_case")]
pub enum PipelineType {
    #[default]
    IngestionEvents,
    ClickhouseEvents,
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    /// Pipeline type determines the event format and processing logic.
    /// Valid values: "ingestion_events" (default), "clickhouse_events"
    #[envconfig(default = "ingestion_events")]
    pub pipeline_type: PipelineType,

    // Kafka configuration
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "kafka-deduplicator")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "10485760")] // 10MB
    pub kafka_consumer_max_partition_fetch_bytes: u32,

    #[envconfig(default = "10000")] // 10 seconds
    pub kafka_topic_metadata_refresh_interval_ms: u32,

    #[envconfig(default = "30000")] // 30 seconds
    pub kafka_metadata_max_age_ms: u32,

    // Session timeout: how long broker waits for heartbeats before declaring consumer dead.
    // With static membership (group.instance.id), broker holds partition assignments for this
    // duration after a consumer disappears. Should be longer than typical pod restart time.
    #[envconfig(default = "60000")] // 60 seconds - covers slow pod restarts
    pub kafka_session_timeout_ms: u32,

    // Heartbeat interval: how often consumer sends heartbeats to broker.
    // With 60s session timeout and 5s heartbeat, 12 heartbeats can miss before timeout.
    #[envconfig(default = "5000")] // 5 seconds
    pub kafka_heartbeat_interval_ms: u32,

    // supplied by k8s deploy env, used as part of kafka
    // consumer client ID for sticky partition mappings
    #[envconfig(from = "HOSTNAME")]
    pub pod_hostname: Option<String>,

    #[envconfig(default = "events")]
    pub kafka_consumer_topic: String,

    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    // Kafka Producer configuration
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32,

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32,

    #[envconfig(default = "10000000")]
    pub kafka_producer_queue_messages: u32,

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32,

    #[envconfig(default = "5000")] // 5 seconds
    pub kafka_producer_send_timeout_ms: u32,

    #[envconfig(default = "snappy")]
    pub kafka_compression_codec: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    // Output topic for deduplicated events (optional - if not set, events are only consumed for metrics)
    pub output_topic: Option<String>,

    // Topic for publishing duplicate detection results (optional)
    pub duplicate_events_topic: Option<String>,

    // RocksDB storage configuration
    #[envconfig(default = "/tmp/deduplication-store")]
    pub store_path: String,

    #[envconfig(default = "1073741824")]
    // 1GB default, supports: raw bytes, scientific notation (9.663676416e+09), or units (9Gi, 1GB)
    pub max_store_capacity: String,

    #[envconfig(default = "120")]
    // 2 minutes default - interval for checking and cleaning up old data when capacity is exceeded
    pub cleanup_interval_secs: u64,

    #[envconfig(default = "900")]
    // 15 minutes default - minimum staleness (no recent WAL activity) before orphan directories can be deleted
    pub orphan_cleanup_min_staleness_secs: u64,

    #[envconfig(default = "16")]
    // Max parallel directory deletions during rebalance cleanup (bounded scatter-gather)
    pub rebalance_cleanup_parallelism: usize,

    // Consumer processing configuration
    #[envconfig(default = "100")]
    pub max_in_flight_messages: usize,

    #[envconfig(default = "100")]
    pub max_in_flight_messages_per_partition: usize,

    #[envconfig(default = "67108864")] // 64MB default
    pub max_memory_bytes: usize,

    #[envconfig(default = "4")]
    pub worker_threads: usize,

    #[envconfig(default = "1")] // 1 second
    pub poll_timeout_secs: u64,

    #[envconfig(default = "60")] // 60 seconds
    pub shutdown_timeout_secs: u64,

    #[envconfig(default = "5")] // 5 seconds
    pub commit_interval_secs: u64,

    #[envconfig(default = "5000")] // 5000 messages (increased from 1000 for higher throughput)
    pub kafka_consumer_batch_size: usize,

    #[envconfig(default = "200")] // 200ms (reduced from 500ms for lower latency)
    pub kafka_consumer_batch_timeout_ms: u64,

    // Timeout for consumer.seek_partitions() after checkpoint import (seconds)
    #[envconfig(default = "5")]
    pub kafka_consumer_seek_timeout_secs: u64,

    // Kafka consumer fetch settings for throughput optimization
    #[envconfig(default = "1048576")] // 1MB minimum fetch size
    pub kafka_consumer_fetch_min_bytes: u32,

    #[envconfig(default = "52428800")] // 50MB maximum fetch size
    pub kafka_consumer_fetch_max_bytes: u32,

    #[envconfig(default = "100")] // 100ms wait when min bytes not reached
    pub kafka_consumer_fetch_wait_max_ms: u32,

    #[envconfig(default = "100000")] // 100K messages to queue for prefetching
    pub kafka_consumer_queued_min_messages: u32,

    #[envconfig(default = "102400")] // 100MB max bytes to prefetch (value is in KB)
    pub kafka_consumer_queued_max_messages_kbytes: u32,

    #[envconfig(default = "300000")]
    // 5 minutes - max time between poll() calls before consumer leaves group
    pub kafka_max_poll_interval_ms: u32,

    // Partition worker channel buffer size for pipeline parallelism
    #[envconfig(default = "10")]
    pub partition_worker_channel_buffer_size: usize,

    #[envconfig(default = "120")] // 120 seconds (2 minutes)
    pub flush_interval_secs: u64,

    // HTTP server configuration
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "8000")]
    pub port: u16,

    //// Checkpoint configuration ////

    // Checkpoint S3 remote storage bucket. If set, this also
    // enables local successful checkpoints to be exported to S3
    pub s3_bucket: Option<String>,

    // Checkpoint S3 remote storage key prefix
    #[envconfig(default = "deduplication-checkpoints")]
    pub s3_key_prefix: String,

    pub aws_region: Option<String>,

    #[envconfig(default = "120")] // 2 minutes
    pub s3_operation_timeout_secs: u64,

    #[envconfig(default = "20")] // 20 seconds
    pub s3_attempt_timeout_secs: u64,

    /// Maximum number of retries for S3 operations before giving up.
    /// Works in conjunction with s3_operation_timeout which provides the total retry budget.
    #[envconfig(default = "3")]
    pub s3_max_retries: usize,

    /// S3 endpoint URL (for non-AWS S3-compatible stores like MinIO)
    pub s3_endpoint: Option<String>,

    /// S3 access key (for local dev without IAM role)
    pub s3_access_key_id: Option<String>,

    /// S3 secret key (for local dev without IAM role)
    pub s3_secret_access_key: Option<String>,

    /// Force path-style S3 URLs (required for MinIO)
    #[envconfig(default = "false")]
    pub s3_force_path_style: bool,

    // Checkpoint configuration - integrated from checkpoint::config
    #[envconfig(default = "1800")] // 30 minutes in seconds
    pub checkpoint_interval_secs: u64,

    // max checkpoint attempts to perform on a single pod at once. each
    // concurrent attempt is against a different locally assigned partition
    #[envconfig(default = "8")]
    pub max_concurrent_checkpoints: usize,

    #[envconfig(default = "200")]
    pub checkpoint_gate_interval_millis: u64,

    #[envconfig(default = "10")]
    pub checkpoint_worker_shutdown_timeout_secs: u64,

    #[envconfig(default = "1")]
    pub checkpoints_per_partition: usize,

    // Base directory where local checkpoints are created.
    // cleaned up on success or failure
    #[envconfig(default = "/tmp/local_checkpoints")]
    pub local_checkpoint_dir: String,

    // how often to perform a full checkpoint vs. incremental
    // if 0, then we will always do full uploads
    #[envconfig(default = "0")]
    pub checkpoint_full_upload_interval: u32,

    // Whether to enable checkpoint import from remote storage
    #[envconfig(default = "false")]
    pub checkpoint_import_enabled: bool,

    // Whether to enable export to remote storage
    // on successful local checkpoint attempts
    #[envconfig(default = "false")]
    pub checkpoint_export_enabled: bool,

    // Number of historical recent checkpoints to attempt to import
    // as fallbacks when most recent download fails or files are corrupted
    #[envconfig(default = "10")]
    pub checkpoint_import_attempt_depth: usize,

    // number of hours prior to "now" that the checkpoint import mechanism
    // will search for valid checkpoint attempts in a DR recovery scenario
    #[envconfig(default = "24")]
    pub checkpoint_import_window_hours: u32,

    // Maximum concurrent S3 file downloads during checkpoint import
    // Limits memory usage by bounding the number of in-flight HTTP connections
    // Critical during rebalance when many partitions are assigned simultaneously
    // Higher values speed up rebalance; streaming bounds memory per download to ~8KB
    #[envconfig(default = "1000")]
    pub max_concurrent_checkpoint_file_downloads: usize,

    // Maximum concurrent S3 file uploads during checkpoint export
    // Less critical than downloads since uploads are bounded by max_concurrent_checkpoints
    #[envconfig(default = "1000")]
    pub max_concurrent_checkpoint_file_uploads: usize,

    // Maximum time allowed for a complete checkpoint import for a single partition (seconds).
    // This includes listing checkpoints, downloading metadata, and downloading all files.
    // Should be less than kafka max.poll.interval.ms to prevent consumer group kicks.
    #[envconfig(default = "240")]
    pub checkpoint_partition_import_timeout_secs: u64,

    //// End checkpoint configuration ////
    /// Fail-open mode: bypass all deduplication and forward events directly to output topic.
    /// When enabled, the deduplicator skips store operations, checkpoint import/export,
    /// and treats all events as unique. Use as an emergency kill switch when the
    /// deduplication store is causing issues.
    #[envconfig(default = "false")]
    pub fail_open: bool,

    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    // OpenTelemetry configuration
    #[envconfig(from = "OTEL_EXPORTER_OTLP_ENDPOINT")]
    pub otel_url: Option<String>,

    #[envconfig(from = "OTEL_TRACES_SAMPLER_ARG", default = "0.001")]
    pub otel_sampling_rate: f64,

    #[envconfig(from = "OTEL_SERVICE_NAME", default = "posthog-kafka-deduplicator")]
    pub otel_service_name: String,

    #[envconfig(from = "OTEL_LOG_LEVEL", default = "info")]
    pub otel_log_level: tracing::Level,
}

impl Config {
    /// Initialize from environment variables (for production and tests)
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
    }

    /// Validate configuration settings
    pub fn validate(&self) -> Result<()> {
        fs::create_dir_all(&self.store_path).with_context(|| {
            format!(
                "Cannot create RocksDB store directory '{}' for consumer group '{}'",
                self.store_path, self.kafka_consumer_group
            )
        })?;

        let test_file = self.store_path_buf().join(".write_test");
        fs::write(&test_file, b"test").with_context(|| {
            format!(
                "RocksDB store path '{}' is not writable for consumer group '{}'",
                self.store_path, self.kafka_consumer_group
            )
        })?;
        fs::remove_file(test_file).ok();

        if let Some(ref bucket) = self.s3_bucket {
            fs::create_dir_all(&self.local_checkpoint_dir).with_context(|| {
                format!(
                    "Cannot create local checkpoint directory '{}' for S3 bucket '{}'",
                    self.local_checkpoint_dir, bucket
                )
            })?;
        }

        Ok(())
    }

    /// Get RocksDB storage path as PathBuf
    pub fn store_path_buf(&self) -> PathBuf {
        PathBuf::from(&self.store_path)
    }

    /// Get server bind address
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }

    /// Get poll timeout as Duration
    pub fn poll_timeout(&self) -> Duration {
        Duration::from_secs(self.poll_timeout_secs)
    }

    /// Get shutdown timeout as Duration
    pub fn shutdown_timeout(&self) -> Duration {
        Duration::from_secs(self.shutdown_timeout_secs)
    }

    /// Get commit interval as Duration
    pub fn commit_interval(&self) -> Duration {
        Duration::from_secs(self.commit_interval_secs)
    }

    /// Get kafka consumer batch timeout as Duration
    pub fn kafka_consumer_batch_timeout(&self) -> Duration {
        Duration::from_millis(self.kafka_consumer_batch_timeout_ms)
    }

    /// Get kafka consumer seek timeout as Duration (for seek_partitions after checkpoint import)
    pub fn kafka_consumer_seek_timeout(&self) -> Duration {
        Duration::from_secs(self.kafka_consumer_seek_timeout_secs)
    }

    /// Get flush interval as Duration
    pub fn flush_interval(&self) -> Duration {
        Duration::from_secs(self.flush_interval_secs)
    }

    /// Get cleanup interval as Duration
    pub fn cleanup_interval(&self) -> Duration {
        Duration::from_secs(self.cleanup_interval_secs)
    }

    /// Get orphan cleanup minimum staleness as Duration
    pub fn orphan_cleanup_min_staleness(&self) -> Duration {
        Duration::from_secs(self.orphan_cleanup_min_staleness_secs)
    }

    /// Get producer send timeout as Duration
    pub fn producer_send_timeout(&self) -> Duration {
        Duration::from_millis(self.kafka_producer_send_timeout_ms as u64)
    }

    /// Parse storage capacity from various formats:
    /// - Raw bytes: "1073741824"
    /// - Scientific notation: "9.663676416e+09"
    /// - Kubernetes units: "9Gi", "500Mi", "1Ki"
    /// - Decimal units: "1GB", "500MB", "1KB"
    pub fn parse_storage_capacity(&self) -> Result<u64> {
        let s = self.max_store_capacity.trim();

        // First try to parse as ByteSize (handles Gi, Mi, KB, MB, etc.)
        if let Ok(size) = s.parse::<ByteSize>() {
            return Ok(size.as_u64());
        }

        // Handle scientific notation (e.g., "9.663676416e+09")
        if s.contains('e') || s.contains('E') {
            let float_val: f64 = s
                .parse()
                .with_context(|| format!("Failed to parse scientific notation: {s}"))?;
            if float_val < 0.0 {
                return Err(anyhow::anyhow!("Storage capacity cannot be negative: {s}"));
            }
            if float_val > u64::MAX as f64 {
                return Err(anyhow::anyhow!(
                    "Storage capacity exceeds maximum value: {s}"
                ));
            }
            return Ok(float_val as u64);
        }

        // Try as raw integer
        s.parse::<u64>()
            .with_context(|| format!("Failed to parse storage capacity: '{s}'. Expected format: raw bytes, scientific notation, or units (1Gi, 1GB)"))
    }

    // Check multiple conditions for safe checkpoint export enablement
    pub fn checkpoint_export_enabled(&self) -> bool {
        self.checkpoint_export_enabled
            && self.s3_bucket.is_some()
            && (self.s3_endpoint.is_some() || self.aws_region.is_some())
    }

    // Check multiple conditions for safe checkpoint import enablement
    pub fn checkpoint_import_enabled(&self) -> bool {
        self.checkpoint_import_enabled
            && self.s3_bucket.is_some()
            && (self.s3_endpoint.is_some() || self.aws_region.is_some())
    }

    /// Get checkpoint interval as Duration
    pub fn checkpoint_interval(&self) -> Duration {
        Duration::from_secs(self.checkpoint_interval_secs)
    }

    pub fn checkpoint_gate_interval(&self) -> Duration {
        Duration::from_millis(self.checkpoint_gate_interval_millis)
    }

    pub fn checkpoint_worker_shutdown_timeout(&self) -> Duration {
        Duration::from_secs(self.checkpoint_worker_shutdown_timeout_secs)
    }

    /// Get S3 per-operation (including all retries) timeout as Duration
    pub fn s3_operation_timeout(&self) -> Duration {
        Duration::from_secs(self.s3_operation_timeout_secs)
    }

    /// Get S3 per-attempt timeout as Duration
    pub fn s3_attempt_timeout(&self) -> Duration {
        Duration::from_secs(self.s3_attempt_timeout_secs)
    }

    /// Get checkpoint partition import timeout as Duration
    pub fn checkpoint_partition_import_timeout(&self) -> Duration {
        Duration::from_secs(self.checkpoint_partition_import_timeout_secs)
    }

    /// Build Kafka consumer configuration for the group-based batch consumer.
    /// Applies all relevant env-configured settings (connection, TLS, fetch/queued,
    /// group membership, sticky assignment, offset reset).
    pub fn build_batch_consumer_config(&self) -> rdkafka::ClientConfig {
        use crate::kafka::config::ConsumerConfigBuilder;

        ConsumerConfigBuilder::for_batch_consumer(&self.kafka_hosts, &self.kafka_consumer_group)
            .with_tls(self.kafka_tls)
            .with_max_partition_fetch_bytes(self.kafka_consumer_max_partition_fetch_bytes)
            .with_topic_metadata_refresh_interval_ms(self.kafka_topic_metadata_refresh_interval_ms)
            .with_metadata_max_age_ms(self.kafka_metadata_max_age_ms)
            .with_sticky_partition_assignment(self.pod_hostname.as_deref())
            .with_offset_reset(&self.kafka_consumer_offset_reset)
            .with_fetch_min_bytes(self.kafka_consumer_fetch_min_bytes)
            .with_fetch_max_bytes(self.kafka_consumer_fetch_max_bytes)
            .with_fetch_wait_max_ms(self.kafka_consumer_fetch_wait_max_ms)
            .with_queued_min_messages(self.kafka_consumer_queued_min_messages)
            .with_queued_max_messages_kbytes(self.kafka_consumer_queued_max_messages_kbytes)
            .with_max_poll_interval_ms(self.kafka_max_poll_interval_ms)
            .with_session_timeout_ms(self.kafka_session_timeout_ms)
            .with_heartbeat_interval_ms(self.kafka_heartbeat_interval_ms)
            .build()
    }

    /// Build Kafka consumer configuration for the assign-only watermark consumer.
    /// Applies only connection, TLS, and fetch/queued settings — no group-coordination
    /// options (session, heartbeat, max.poll, sticky, offset reset).
    pub fn build_watermark_consumer_config(&self, group_id: &str) -> rdkafka::ClientConfig {
        use crate::kafka::config::ConsumerConfigBuilder;

        ConsumerConfigBuilder::for_watermark_consumer(&self.kafka_hosts, group_id)
            .with_tls(self.kafka_tls)
            .with_max_partition_fetch_bytes(self.kafka_consumer_max_partition_fetch_bytes)
            .with_topic_metadata_refresh_interval_ms(self.kafka_topic_metadata_refresh_interval_ms)
            .with_metadata_max_age_ms(self.kafka_metadata_max_age_ms)
            .with_fetch_min_bytes(self.kafka_consumer_fetch_min_bytes)
            .with_fetch_max_bytes(self.kafka_consumer_fetch_max_bytes)
            .with_fetch_wait_max_ms(self.kafka_consumer_fetch_wait_max_ms)
            .with_queued_min_messages(self.kafka_consumer_queued_min_messages)
            .with_queued_max_messages_kbytes(self.kafka_consumer_queued_max_messages_kbytes)
            .build()
    }

    /// Build Kafka producer configuration
    pub fn build_producer_config(&self) -> rdkafka::ClientConfig {
        let mut config = rdkafka::ClientConfig::new();
        config
            .set("bootstrap.servers", &self.kafka_hosts)
            .set(
                "message.timeout.ms",
                self.kafka_message_timeout_ms.to_string(),
            )
            .set(
                "queue.buffering.max.messages",
                self.kafka_producer_queue_messages.to_string(),
            )
            .set(
                "queue.buffering.max.ms",
                self.kafka_producer_linger_ms.to_string(),
            )
            .set("compression.type", &self.kafka_compression_codec);

        if self.kafka_tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_storage_capacity_raw_bytes() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test raw bytes
        config.max_store_capacity = "1073741824".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1073741824);

        config.max_store_capacity = "0".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 0);

        config.max_store_capacity = "1234567890".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1234567890);
    }

    #[test]
    fn test_parse_storage_capacity_scientific_notation() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test scientific notation
        config.max_store_capacity = "9.663676416e+09".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 9663676416);

        config.max_store_capacity = "1e9".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1000000000);

        config.max_store_capacity = "1.5e10".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 15000000000);

        config.max_store_capacity = "2.5E9".to_string(); // Capital E
        assert_eq!(config.parse_storage_capacity().unwrap(), 2500000000);
    }

    #[test]
    fn test_parse_storage_capacity_kubernetes_units() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test Kubernetes binary units (base 1024)
        config.max_store_capacity = "1Ki".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1024);

        config.max_store_capacity = "1Mi".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1024 * 1024);

        config.max_store_capacity = "1Gi".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1024 * 1024 * 1024);

        config.max_store_capacity = "9Gi".to_string();
        assert_eq!(
            config.parse_storage_capacity().unwrap(),
            9 * 1024 * 1024 * 1024
        );

        config.max_store_capacity = "500Mi".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 500 * 1024 * 1024);

        // With B suffix
        config.max_store_capacity = "1GiB".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1024 * 1024 * 1024);
    }

    #[test]
    fn test_parse_storage_capacity_decimal_units() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test decimal units (base 1000)
        config.max_store_capacity = "1KB".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1000);

        config.max_store_capacity = "1MB".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1000 * 1000);

        config.max_store_capacity = "1GB".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1000 * 1000 * 1000);

        config.max_store_capacity = "500MB".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 500 * 1000 * 1000);
    }

    #[test]
    fn test_parse_storage_capacity_whitespace() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test with whitespace
        config.max_store_capacity = "  1Gi  ".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 1024 * 1024 * 1024);

        config.max_store_capacity = " 9.663676416e+09 ".to_string();
        assert_eq!(config.parse_storage_capacity().unwrap(), 9663676416);
    }

    #[test]
    fn test_parse_storage_capacity_errors() {
        let mut config = Config::init_with_defaults().unwrap();

        // Test invalid formats
        config.max_store_capacity = "invalid".to_string();
        assert!(config.parse_storage_capacity().is_err());

        config.max_store_capacity = "-1".to_string();
        assert!(config.parse_storage_capacity().is_err());

        config.max_store_capacity = "-1e9".to_string();
        assert!(config.parse_storage_capacity().is_err());

        config.max_store_capacity = "".to_string();
        assert!(config.parse_storage_capacity().is_err());
    }

    #[test]
    fn test_checkpoint_export_enabled() {
        let mut config = Config::init_with_defaults().unwrap();

        // All disabled by default (no bucket, no endpoint, no region)
        config.checkpoint_export_enabled = true;
        assert!(!config.checkpoint_export_enabled());

        // Flag disabled - should be false regardless of other settings
        config.checkpoint_export_enabled = false;
        config.s3_bucket = Some("test-bucket".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(!config.checkpoint_export_enabled());

        // Production AWS: region + bucket (no endpoint)
        config.checkpoint_export_enabled = true;
        config.s3_bucket = Some("test-bucket".to_string());
        config.aws_region = Some("us-east-1".to_string());
        config.s3_endpoint = None;
        assert!(config.checkpoint_export_enabled());

        // Local dev MinIO: endpoint + bucket (no region)
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = None;
        assert!(config.checkpoint_export_enabled());

        // Local dev MinIO with region: endpoint + bucket + region
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(config.checkpoint_export_enabled());

        // Missing bucket - should be false
        config.s3_bucket = None;
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(!config.checkpoint_export_enabled());

        // Missing both endpoint and region - should be false
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = None;
        config.aws_region = None;
        assert!(!config.checkpoint_export_enabled());
    }

    #[test]
    fn test_checkpoint_import_enabled() {
        let mut config = Config::init_with_defaults().unwrap();

        // All disabled by default (no bucket, no endpoint, no region)
        config.checkpoint_import_enabled = true;
        assert!(!config.checkpoint_import_enabled());

        // Flag disabled - should be false regardless of other settings
        config.checkpoint_import_enabled = false;
        config.s3_bucket = Some("test-bucket".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(!config.checkpoint_import_enabled());

        // Production AWS: region + bucket (no endpoint)
        config.checkpoint_import_enabled = true;
        config.s3_bucket = Some("test-bucket".to_string());
        config.aws_region = Some("us-east-1".to_string());
        config.s3_endpoint = None;
        assert!(config.checkpoint_import_enabled());

        // Local dev MinIO: endpoint + bucket (no region)
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = None;
        assert!(config.checkpoint_import_enabled());

        // Local dev MinIO with region: endpoint + bucket + region
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(config.checkpoint_import_enabled());

        // Missing bucket - should be false
        config.s3_bucket = None;
        config.s3_endpoint = Some("http://localhost:9000".to_string());
        config.aws_region = Some("us-east-1".to_string());
        assert!(!config.checkpoint_import_enabled());

        // Missing both endpoint and region - should be false
        config.s3_bucket = Some("test-bucket".to_string());
        config.s3_endpoint = None;
        config.aws_region = None;
        assert!(!config.checkpoint_import_enabled());
    }
}
