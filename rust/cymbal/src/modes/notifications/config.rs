use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

/// Topic carrying error-tracking ingestion notifications. Overridable via
/// `KAFKA_CONSUMER_TOPIC`.
pub const DEFAULT_CONSUMER_TOPIC: &str = "error_tracking_ingestion_notifications";

/// Consumer group for the notifications mode. Overridable via
/// `KAFKA_CONSUMER_GROUP`.
pub const DEFAULT_CONSUMER_GROUP: &str = "error_tracking_ingestion_notifications";

/// Top-level config for notifications mode.
#[derive(Envconfig, Clone)]
pub struct NotificationsConfig {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    /// HTTP bind port for liveness, readiness, and Prometheus metrics.
    #[envconfig(from = "METRICS_PORT", default = "9102")]
    pub metrics_port: u16,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,

    #[envconfig(from = "TEMPORAL_HOST", default = "")]
    pub temporal_host: String,

    #[envconfig(from = "TEMPORAL_PORT", default = "7233")]
    pub temporal_port: u16,

    #[envconfig(from = "TEMPORAL_NAMESPACE", default = "")]
    pub temporal_namespace: String,

    #[envconfig(from = "TEMPORAL_CLIENT_CERT", default = "")]
    pub temporal_client_cert: String,

    #[envconfig(from = "TEMPORAL_CLIENT_KEY", default = "")]
    pub temporal_client_key: String,

    #[envconfig(from = "TEMPORAL_SECRET_KEY", default = "")]
    pub temporal_secret_key: String,

    #[envconfig(
        from = "ERROR_TRACKING_LIFECYCLE_TASK_QUEUE",
        default = "error-tracking-lifecycle-task-queue"
    )]
    pub error_tracking_lifecycle_task_queue: String,
}

impl NotificationsConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Commit only after notification handling succeeds. Failed handling should crash
        // before the offset is committed so Kafka redelivers the message on restart.
        ConsumerConfig::set_defaults(DEFAULT_CONSUMER_GROUP, DEFAULT_CONSUMER_TOPIC, false);
        Self::init_from_env()
    }
}
