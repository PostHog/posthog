use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

/// Topic carrying error-tracking ingestion notifications. Overridable via
/// `KAFKA_CONSUMER_TOPIC`.
pub const DEFAULT_CONSUMER_TOPIC: &str = "error-tracking-ingestion-notifications";

/// Consumer group for the notifications mode. Overridable via
/// `KAFKA_CONSUMER_GROUP`.
pub const DEFAULT_CONSUMER_GROUP: &str = "error-tracking-ingestion-notifications";

/// Top-level config for notifications mode. Owns only what a read-and-log
/// consumer needs: a Kafka client, a single-topic consumer, and the metrics
/// server port — none of the processing-only knobs.
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
}

impl NotificationsConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // We only read and log, so at-most-once delivery is fine — let the
        // consumer auto-commit stored offsets.
        ConsumerConfig::set_defaults(DEFAULT_CONSUMER_GROUP, DEFAULT_CONSUMER_TOPIC, true);
        Self::init_from_env()
    }
}
