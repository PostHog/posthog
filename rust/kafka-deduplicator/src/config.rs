use std::{path::PathBuf, time::Duration};

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

    #[envconfig(default = "false")]
    pub kafka_consumer_auto_commit: bool,

    // Kafka Producer configuration
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32,

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32,

    #[envconfig(default = "10000000")]
    pub kafka_producer_queue_messages: u32,

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32,

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

    #[envconfig(default = "30")] // 30 seconds
    pub shutdown_timeout_secs: u64,

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
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
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

    /// Get checkpoint interval as Duration
    pub fn checkpoint_interval(&self) -> Duration {
        Duration::from_secs(self.checkpoint_interval_secs)
    }

    /// Get S3 timeout as Duration
    pub fn s3_timeout(&self) -> Duration {
        Duration::from_secs(self.s3_timeout_secs)
    }

    /// Convert to custom ConsumerConfig for the kafka module
    pub fn to_consumer_config(&self) -> crate::kafka::config::ConsumerConfig {
        crate::kafka::config::ConsumerConfig::new(
            self.kafka_hosts.clone(),
            self.kafka_consumer_group.clone(),
            vec![self.kafka_consumer_topic.clone()],
        )
        .with_max_in_flight_messages(self.max_in_flight_messages)
        .with_max_in_flight_messages_per_partition(self.max_in_flight_messages_per_partition)
        .with_max_memory(self.max_memory_bytes)
        .with_worker_threads(self.worker_threads)
        .with_poll_timeout(self.poll_timeout())
        .with_shutdown_timeout(self.shutdown_timeout())
        .with_kafka_config("auto.offset.reset".to_string(), self.kafka_consumer_offset_reset.clone())
    }

    /// Convert to checkpoint config (for compatibility with existing checkpoint code)
    pub fn to_checkpoint_config(&self) -> crate::checkpoint::config::CheckpointConfig {
        crate::checkpoint::config::CheckpointConfig {
            checkpoint_interval: self.checkpoint_interval(),
            local_checkpoint_dir: self.local_checkpoint_dir.clone(),
            s3_bucket: self.s3_bucket.clone().unwrap_or_default(),
            s3_key_prefix: self.s3_key_prefix.clone(),
            full_upload_interval: self.full_upload_interval,
            aws_region: self.aws_region.clone(),
            max_local_checkpoints: self.max_local_checkpoints,
            s3_timeout: self.s3_timeout(),
        }
    }
}