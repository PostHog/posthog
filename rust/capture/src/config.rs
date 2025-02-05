use std::{net::SocketAddr, num::NonZeroU32};

use envconfig::Envconfig;
use health::HealthStrategy;

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

    #[envconfig(default = "100")]
    pub overflow_per_second_limit: NonZeroU32,

    #[envconfig(default = "1000")]
    pub overflow_burst_limit: NonZeroU32,

    pub overflow_forced_keys: Option<String>, // Coma-delimited keys
    pub dropped_keys: Option<String>, // "<token>:<distinct_id or *>,<distinct_id or *>;<token>..."

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
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            print_sink: false,
            address: "127.0.0.1:3000".parse().unwrap(),
            redis_url: String::new(),
            otel_url: None,
            overflow_enabled: false,
            overflow_per_second_limit: NonZeroU32::new(100).unwrap(),
            overflow_burst_limit: NonZeroU32::new(1000).unwrap(),
            overflow_forced_keys: None,
            dropped_keys: None,
            kafka: KafkaConfig {
                kafka_producer_linger_ms: 20,
                kafka_producer_queue_mib: 400,
                kafka_message_timeout_ms: 20000,
                kafka_producer_message_max_bytes: 1000000,
                kafka_compression_codec: String::new(),
                kafka_hosts: String::new(),
                kafka_topic: String::new(),
                kafka_historical_topic: String::new(),
                kafka_client_ingestion_warning_topic: String::new(),
                kafka_exceptions_topic: String::new(),
                kafka_heatmaps_topic: String::new(),
                kafka_replay_overflow_topic: String::new(),
                kafka_tls: false,
                kafka_client_id: String::new(),
                kafka_metadata_max_age_ms: 60000,
                kafka_producer_max_retries: 2,
                kafka_producer_acks: String::new(),
            },
            otel_sampling_rate: 1.0,
            otel_service_name: String::new(),
            export_prometheus: true,
            redis_key_prefix: None,
            capture_mode: CaptureMode::Events,
            concurrency_limit: None,
            s3_fallback_enabled: false,
            s3_fallback_bucket: None,
            s3_fallback_endpoint: None,
            s3_fallback_prefix: String::new(),
            healthcheck_strategy: HealthStrategy::All,
        }
    }
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
    #[envconfig(default = "events_plugin_ingestion_historical")]
    pub kafka_historical_topic: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_client_ingestion_warning_topic: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_exceptions_topic: String,
    #[envconfig(default = "events_plugin_ingestion")]
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
}
