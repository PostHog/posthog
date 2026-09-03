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

    /// Connect to Temporal without TLS. Only the local dev stack serves plaintext
    /// gRPC, so leaving this off keeps a missing certificate a boot failure.
    #[envconfig(from = "TEMPORAL_INSECURE", default = "false")]
    pub temporal_insecure: bool,

    #[envconfig(from = "TEMPORAL_SECRET_KEY", default = "")]
    pub temporal_secret_key: String,

    #[envconfig(
        from = "ERROR_TRACKING_LIFECYCLE_TASK_QUEUE",
        default = "error-tracking-lifecycle-task-queue"
    )]
    pub error_tracking_lifecycle_task_queue: String,

    /// Redis backing the per-team cap on issue-created workflows. It carries no
    /// default, so envconfig rejects a boot that does not set it.
    #[envconfig(from = "ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_REDIS_URL")]
    pub notifications_rate_limit_redis_url: String,

    /// Bucket size, and the tokens a team earns back per hour. Zero or less
    /// disables the limit.
    #[envconfig(
        from = "ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_PER_HOUR",
        default = "1000"
    )]
    pub notifications_rate_limit_per_hour: i64,

    #[envconfig(
        from = "ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_KEY_PREFIX",
        default = "@posthog/error-tracking-notifications-rate-limiter"
    )]
    pub notifications_rate_limit_key_prefix: String,

    /// Idle buckets expire after this long. A bucket always takes an hour to
    /// refill, so anything below 3600 is raised to 3600: a shorter TTL would
    /// drop a partly refilled bucket and hand the next caller a full one.
    #[envconfig(
        from = "ERROR_TRACKING_NOTIFICATIONS_RATE_LIMIT_BUCKET_TTL_SECONDS",
        default = "3600"
    )]
    pub notifications_rate_limit_bucket_ttl_seconds: u64,

    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,
}

impl NotificationsConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Commit only after notification handling succeeds. Failed handling should crash
        // before the offset is committed so Kafka redelivers the message on restart.
        ConsumerConfig::set_defaults(DEFAULT_CONSUMER_GROUP, DEFAULT_CONSUMER_TOPIC, false);
        Self::init_from_env()
    }
}
