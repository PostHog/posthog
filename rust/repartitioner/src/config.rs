use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // Kafka configuration
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    #[envconfig(default = "true")]
    pub kafka_consumer_auto_commit: bool,

    #[envconfig(default = "5000")]
    pub kafka_consumer_auto_commit_interval_ms: u32,

    // Producer configuration
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32,

    #[envconfig(default = "10")]
    pub kafka_producer_graceful_shutdown_secs: u64,

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32,

    #[envconfig(default = "10000000")]
    pub kafka_producer_queue_messages: u32,

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32,

    #[envconfig(default = "snappy")]
    pub kafka_compression_codec: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    // Service specific configuration
    #[envconfig(default = "repartitioner_v1")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "clickhouse_events_json")]
    pub kafka_source_topic: String,

    // Destination topic configuration
    #[envconfig(default = "propdefs_events_json")]
    pub kafka_destination_topic: String,

    #[envconfig(default = "propdefs_v1_by_team_id")]
    pub partition_key_compute_fn: String,

    // HTTP server configuration
    #[envconfig(default = "0.0.0.0:8080")]
    pub bind_address: String,

    #[envconfig(default = "false")]
    pub export_prometheus: bool,
}

impl Config {
    /// Initialize from environment variables (for production and tests)
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Config::init_from_env()
    }
}
