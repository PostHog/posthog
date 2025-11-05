use std::{fs, path::PathBuf, time::Duration};

use anyhow::{Context, Result};
use bytesize::ByteSize;
use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // Kafka configuration
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "kafka-deduplicator")]
    pub kafka_consumer_group: String,

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

    #[envconfig(default = "120")] // 120 seconds (2 minutes)
    pub flush_interval_secs: u64,

    // HTTP server configuration
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "8000")]
    pub port: u16,

    // Checkpoint configuration - integrated from checkpoint::config
    #[envconfig(default = "1800")] // 30 minutes in seconds
    pub checkpoint_interval_secs: u64,

    #[envconfig(default = "900")] // 15 minutes in seconds
    pub checkpoint_cleanup_interval_secs: u64,

    #[envconfig(default = "1")] // delete local checkpoints older than this
    pub max_checkpoint_retention_hours: u32,

    #[envconfig(default = "8")] // max concurrent checkpoints to perform on single node
    pub max_concurrent_checkpoints: usize,

    #[envconfig(default = "200")]
    pub checkpoint_gate_interval_millis: u64,

    #[envconfig(default = "10")]
    pub checkpoint_worker_shutdown_timeout_secs: u64,

    #[envconfig(default = "1")]
    pub checkpoints_per_partition: usize,

    #[envconfig(default = "/tmp/checkpoints")]
    pub local_checkpoint_dir: String,

    pub s3_bucket: Option<String>,

    #[envconfig(default = "deduplication-checkpoints")]
    pub s3_key_prefix: String,

    // how often to perform a full checkpoint vs. incremental
    // if 0, then we will always do full uploads
    #[envconfig(default = "0")]
    pub checkpoint_full_upload_interval: u32,

    // number of hours prior to "now" that the checkpoint import mechanism
    // will search for valid checkpoint attempts in a DR recovery scenario
    #[envconfig(default = "24")]
    pub checkpoint_import_window_hours: u32,

    #[envconfig(default = "us-east-1")]
    pub aws_region: String,

    #[envconfig(default = "120")] // 2 minutes
    pub s3_operation_timeout_secs: u64,

    #[envconfig(default = "20")] // 20 seconds
    pub s3_attempt_timeout_secs: u64,

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

    #[envconfig(default = "false")]
    pub enable_pprof: bool,
}

impl Config {
    /// Initialize from environment variables (for production and tests)
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
    }

    /// Validate configuration settings
    pub fn validate(&self) -> Result<()> {
        // Check store path is writable
        if let Err(e) = fs::create_dir_all(&self.store_path) {
            return Err(anyhow::anyhow!(
                "Cannot create RocksDB store directory '{}' for consumer group '{}': {}",
                self.store_path,
                self.kafka_consumer_group,
                e
            ));
        }

        // Check if we can write to the directory
        let test_file = self.store_path_buf().join(".write_test");
        if let Err(e) = fs::write(&test_file, b"test") {
            return Err(anyhow::anyhow!(
                "RocksDB store path '{}' is not writable for consumer group '{}': {}",
                self.store_path,
                self.kafka_consumer_group,
                e
            ));
        }
        fs::remove_file(test_file).ok();

        // Validate checkpoint path if S3 is configured
        if let Some(ref bucket) = self.s3_bucket {
            if let Err(e) = fs::create_dir_all(&self.local_checkpoint_dir) {
                return Err(anyhow::anyhow!(
                    "Cannot create local checkpoint directory '{}' for S3 bucket '{}': {}",
                    self.local_checkpoint_dir,
                    bucket,
                    e
                ));
            }
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

    /// Get flush interval as Duration
    pub fn flush_interval(&self) -> Duration {
        Duration::from_secs(self.flush_interval_secs)
    }

    /// Get cleanup interval as Duration
    pub fn cleanup_interval(&self) -> Duration {
        Duration::from_secs(self.cleanup_interval_secs)
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
                return Err(anyhow::anyhow!(
                    "Storage capacity cannot be negative: {}",
                    s
                ));
            }
            if float_val > u64::MAX as f64 {
                return Err(anyhow::anyhow!(
                    "Storage capacity exceeds maximum value: {}",
                    s
                ));
            }
            return Ok(float_val as u64);
        }

        // Try as raw integer
        s.parse::<u64>()
            .with_context(|| format!("Failed to parse storage capacity: '{s}'. Expected format: raw bytes, scientific notation, or units (1Gi, 1GB)"))
    }

    /// Get checkpoint interval as Duration
    pub fn checkpoint_interval(&self) -> Duration {
        Duration::from_secs(self.checkpoint_interval_secs)
    }

    /// Get local stale checkpoint cleanup scan interval as Duration
    pub fn checkpoint_cleanup_interval(&self) -> Duration {
        Duration::from_secs(self.checkpoint_cleanup_interval_secs)
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
}
