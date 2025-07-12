use std::{net::SocketAddr, num::NonZeroU32};

use envconfig::Envconfig;
use health::HealthStrategy;
use tracing::Level;

#[derive(Debug, PartialEq, Clone)]
pub enum CaptureMode {
    Events,
    Recordings,
}

impl std::str::FromStr for CaptureMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "events" => Ok(CaptureMode::Events),
            "recordings" => Ok(CaptureMode::Recordings),
            _ => Err(format!("Unknown Capture Type: {s}")),
        }
    }
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "false")]
    pub print_sink: bool,

    #[envconfig(default = "127.0.0.1:3000")]
    pub address: SocketAddr,

    pub redis_url: String,
    pub otel_url: Option<String>,

    #[envconfig(default = "false")]
    pub overflow_enabled: bool,

    #[envconfig(default = "false")]
    pub overflow_preserve_partition_locality: bool,

    #[envconfig(default = "100")]
    pub overflow_per_second_limit: NonZeroU32,

    #[envconfig(default = "1000")]
    pub overflow_burst_limit: NonZeroU32,

    pub ingestion_force_overflow_by_token_distinct_id: Option<String>, // Comma-delimited keys

    pub drop_events_by_token_distinct_id: Option<String>, // "<token>:<distinct_id or *>,<distinct_id or *>;<token>..."

    #[envconfig(default = "false")]
    pub enable_historical_rerouting: bool,

    #[envconfig(default = "1")]
    pub historical_rerouting_threshold_days: i64,

    pub historical_tokens_keys: Option<String>, // "<token>:<distinct_id or *>,<distinct_id or *>;<token>..."

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "1.0")]
    pub otel_sampling_rate: f64,

    #[envconfig(default = "capture")]
    pub otel_service_name: String,

    // Used for integration tests
    #[envconfig(default = "true")]
    pub export_prometheus: bool,
    pub redis_key_prefix: Option<String>,

    #[envconfig(default = "events")]
    pub capture_mode: CaptureMode,

    pub concurrency_limit: Option<usize>,

    #[envconfig(default = "false")]
    pub s3_fallback_enabled: bool,
    pub s3_fallback_bucket: Option<String>,
    pub s3_fallback_endpoint: Option<String>,

    #[envconfig(default = "")]
    pub s3_fallback_prefix: String,

    #[envconfig(default = "ALL")]
    pub healthcheck_strategy: HealthStrategy,

    #[envconfig(default = "false")]
    pub is_mirror_deploy: bool,

    #[envconfig(default = "info")]
    pub log_level: Level,

    // generic env injection to sample behavior of interest for verbose logging
    #[envconfig(default = "0.0")]
    pub verbose_sample_percent: f32,
}

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic
    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes
    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds
    #[envconfig(default = "1000000")]
    pub kafka_producer_message_max_bytes: u32, // message.max.bytes - max kafka message size we will produce
    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd
    pub kafka_hosts: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_topic: String,
    #[envconfig(default = "events_plugin_ingestion_overflow")]
    pub kafka_overflow_topic: String,
    #[envconfig(default = "events_plugin_ingestion_historical")]
    pub kafka_historical_topic: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_client_ingestion_warning_topic: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_exceptions_topic: String,
    #[envconfig(default = "exceptions_ingestion")]
    pub kafka_heatmaps_topic: String,
    #[envconfig(default = "session_recording_snapshot_item_overflow")]
    pub kafka_replay_overflow_topic: String,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
    #[envconfig(default = "")]
    pub kafka_client_id: String,
    #[envconfig(default = "60000")]
    pub kafka_metadata_max_age_ms: u32,
    #[envconfig(default = "2")]
    pub kafka_producer_max_retries: u32,
    #[envconfig(default = "all")]
    pub kafka_producer_acks: String,
    #[envconfig(default = "60000")]
    pub kafka_topic_metadata_refresh_interval_ms: u32,
}
