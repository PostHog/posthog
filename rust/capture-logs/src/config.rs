use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    // management endpoint serves _readiness/_liveness/metrics
    #[envconfig(from = "MANAGEMENT_BIND_HOST", default = "::")]
    pub management_host: String,

    #[envconfig(from = "MANAGEMENT_BIND_PORT", default = "8080")]
    pub management_port: u16,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "4318")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    pub drop_events_by_token: Option<String>, // "<token>,<token>..."

    #[envconfig(from = "MAX_REQUEST_BODY_SIZE_BYTES", default = "2097152")] // 2MB (Axum default)
    pub max_request_body_size_bytes: usize,

    // Firehose buffers 1-64 MiB per delivery and base64 adds a third, so the Firehose route gets its
    // own, larger body cap. Decoded size is bounded separately by the endpoint.
    #[envconfig(from = "FIREHOSE_MAX_REQUEST_BODY_SIZE_BYTES", default = "8388608")] // 8 MiB
    pub firehose_max_request_body_size_bytes: usize,

    #[envconfig(from = "MAX_BACKFILL_DAYS", default = "0")]
    pub max_backfill_days: u32,

    // Tokens that may use the Vercel drain route, or "*" for all. Unset keeps the route closed.
    pub vercel_drain_enabled_tokens: Option<String>, // "<token>,<token>..." or "*"
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
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
    #[envconfig(default = "ingestion-traces")]
    pub kafka_traces_topic: String,
    #[envconfig(default = "ingestion-metrics")]
    pub kafka_metrics_topic: String,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
    #[envconfig(default = "")]
    pub kafka_client_id: String,
    #[envconfig(default = "2")]
    pub kafka_producer_max_retries: u32,
    #[envconfig(default = "all")]
    pub kafka_producer_acks: String,
    // interval between metadata refreshes from the Kafka brokers
    #[envconfig(default = "20000")]
    pub kafka_topic_metadata_refresh_interval_ms: u32,
    // default is 3x metadata refresh interval so we maintain that here
    #[envconfig(default = "60000")]
    pub kafka_metadata_max_age_ms: u32,

    // Traces-cluster overrides (consumed by capture-logs). When unset, the
    // traces producer reuses the corresponding `kafka_*` value above.
    pub kafka_traces_hosts: Option<String>,
    pub kafka_traces_tls: Option<bool>,
    pub kafka_traces_client_id: Option<String>,
    pub kafka_traces_compression_codec: Option<String>,
    pub kafka_traces_producer_acks: Option<String>,
    pub kafka_traces_producer_linger_ms: Option<u32>,
    pub kafka_traces_producer_queue_mib: Option<u32>,
    pub kafka_traces_message_timeout_ms: Option<u32>,
    pub kafka_traces_producer_message_max_bytes: Option<u32>,
    pub kafka_traces_producer_max_retries: Option<u32>,
    pub kafka_traces_topic_metadata_refresh_interval_ms: Option<u32>,
    pub kafka_traces_metadata_max_age_ms: Option<u32>,

    // Metrics-cluster overrides (consumed by capture-logs). When unset, the
    // metrics producer reuses the corresponding `kafka_*` value above.
    pub kafka_metrics_hosts: Option<String>,
    pub kafka_metrics_tls: Option<bool>,
    pub kafka_metrics_client_id: Option<String>,
    pub kafka_metrics_compression_codec: Option<String>,
    pub kafka_metrics_producer_acks: Option<String>,
    pub kafka_metrics_producer_linger_ms: Option<u32>,
    pub kafka_metrics_producer_queue_mib: Option<u32>,
    pub kafka_metrics_message_timeout_ms: Option<u32>,
    pub kafka_metrics_producer_message_max_bytes: Option<u32>,
    pub kafka_metrics_producer_max_retries: Option<u32>,
    pub kafka_metrics_topic_metadata_refresh_interval_ms: Option<u32>,
    pub kafka_metrics_metadata_max_age_ms: Option<u32>,
}
