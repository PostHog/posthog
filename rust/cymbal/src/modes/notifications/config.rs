use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

/// Topic carrying error-tracking ingestion notifications. Overridable via
/// `KAFKA_CONSUMER_TOPIC`.
pub const DEFAULT_CONSUMER_TOPIC: &str = "error_tracking_ingestion_notifications";

/// Consumer group for the notifications mode. Overridable via
/// `KAFKA_CONSUMER_GROUP`.
pub const DEFAULT_CONSUMER_GROUP: &str = "error_tracking_ingestion_notifications";

/// Top-level config for notifications mode. Includes the downstream clients
/// needed for legacy side effects and opt-in Temporal workflow starts.
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

    /// Direct Temporal starts are disabled by default. When enabled with an empty
    /// allowlist, every team is routed to the issue-created workflow.
    #[envconfig(
        from = "ERROR_TRACKING_ISSUE_CREATED_WORKFLOW_ENABLED",
        default = "false"
    )]
    pub issue_created_workflow_enabled: bool,

    /// Comma-separated rollout allowlist. An empty value means all teams when
    /// `ERROR_TRACKING_ISSUE_CREATED_WORKFLOW_ENABLED` is true.
    #[envconfig(from = "ERROR_TRACKING_ISSUE_CREATED_WORKFLOW_TEAM_IDS", default = "")]
    pub issue_created_workflow_team_ids: String,

    #[envconfig(
        from = "ERROR_TRACKING_ISSUE_REOPENED_WORKFLOW_ENABLED",
        default = "false"
    )]
    pub issue_reopened_workflow_enabled: bool,

    #[envconfig(from = "ERROR_TRACKING_ISSUE_REOPENED_WORKFLOW_TEAM_IDS", default = "")]
    pub issue_reopened_workflow_team_ids: String,

    #[envconfig(
        from = "ERROR_TRACKING_ISSUE_SPIKING_WORKFLOW_ENABLED",
        default = "false"
    )]
    pub issue_spiking_workflow_enabled: bool,

    #[envconfig(from = "ERROR_TRACKING_ISSUE_SPIKING_WORKFLOW_TEAM_IDS", default = "")]
    pub issue_spiking_workflow_team_ids: String,

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
