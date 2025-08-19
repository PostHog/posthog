use std::{fs, path::PathBuf, time::Duration};

use anyhow::Result;
use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // Kafka configuration
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "kafka-deduplicator")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "events")]
    pub kafka_consumer_topic: String,

    #[envconfig(default = "earliest")]
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

    // Output topic for deduplicated events (optional - if not set, events are only consumed for metrics)
    pub output_topic: Option<String>,

    // RocksDB storage configuration
    #[envconfig(default = "/tmp/deduplication-store")]
    pub store_path: String,

    #[envconfig(default = "1073741824")] // 1GB default
    pub max_store_capacity: u64,

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

    // HTTP server configuration
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "8080")]
    pub port: u16,

    // Checkpoint configuration - integrated from checkpoint::config
    #[envconfig(default = "300")] // 5 minutes in seconds
    pub checkpoint_interval_secs: u64,

    #[envconfig(default = "./checkpoints")]
    pub local_checkpoint_dir: String,

    pub s3_bucket: Option<String>,

    #[envconfig(default = "deduplication-checkpoints")]
    pub s3_key_prefix: String,

    #[envconfig(default = "10")]
    pub full_upload_interval: u32,

    #[envconfig(default = "us-east-1")]
    pub aws_region: String,

    #[envconfig(default = "5")]
    pub max_local_checkpoints: usize,

    #[envconfig(default = "300")] // 5 minutes in seconds
    pub s3_timeout_secs: u64,
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

    /// Get producer send timeout as Duration
    pub fn producer_send_timeout(&self) -> Duration {
        Duration::from_millis(self.kafka_producer_send_timeout_ms as u64)
    }

    /// Get checkpoint interval as Duration
    pub fn checkpoint_interval(&self) -> Duration {
        Duration::from_secs(self.checkpoint_interval_secs)
    }

    /// Get S3 timeout as Duration
    pub fn s3_timeout(&self) -> Duration {
        Duration::from_secs(self.s3_timeout_secs)
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
        config
    }
}
