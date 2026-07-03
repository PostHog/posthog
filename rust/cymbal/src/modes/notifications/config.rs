use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

/// Topic carrying error-tracking ingestion notifications. Overridable via
/// `KAFKA_CONSUMER_TOPIC`.
pub const DEFAULT_CONSUMER_TOPIC: &str = "error_tracking_ingestion_notifications";

/// Consumer group for the notifications mode. Overridable via
/// `KAFKA_CONSUMER_GROUP`.
pub const DEFAULT_CONSUMER_GROUP: &str = "error_tracking_ingestion_notifications";

/// Top-level config for notifications mode. Keep this narrow: only Kafka,
/// Postgres, signal emission, and the metrics server.
#[derive(Envconfig, Clone)]
pub struct NotificationsConfig {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Keep this low: each Cymbal pod owns its own sqlx pool, regardless of DATABASE_URL routing.
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    #[envconfig(default = "")]
    pub internal_api_secret: String,

    /// HTTP bind port for liveness, readiness, and Prometheus metrics.
    #[envconfig(from = "METRICS_PORT", default = "9102")]
    pub metrics_port: u16,

    // Internal API for signal emission.
    #[envconfig(default = "")]
    pub signals_api_base_url: String,

    #[envconfig(default = "document_embeddings_input")]
    pub embedding_worker_topic: String,

    #[envconfig(default = "cdp_internal_events")]
    pub internal_events_topic: String,

    // Optional override for the brokers used to produce `cdp_internal_events`.
    #[envconfig(from = "CYMBAL_CYCLOTRON_KAFKA_HOSTS")]
    pub cyclotron_kafka_hosts: Option<String>,

    // Optional TLS override for the cyclotron producer.
    #[envconfig(from = "CYMBAL_CYCLOTRON_KAFKA_TLS")]
    pub cyclotron_kafka_tls: Option<bool>,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,
}

impl NotificationsConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Commit only after notification handling succeeds. Failed handling should crash
        // before the offset is committed so Kafka redelivers the message on restart.
        ConsumerConfig::set_defaults(DEFAULT_CONSUMER_GROUP, DEFAULT_CONSUMER_TOPIC, false);
        Self::init_from_env()
    }
}
