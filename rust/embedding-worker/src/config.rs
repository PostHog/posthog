use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    // To other services, like ET, that want to take some action after a document is embedded and written to CH
    #[envconfig(default = "document_embedding_results")]
    pub response_topic: String,

    // To clickhouse
    #[envconfig(default = "clickhouse_document_embeddings")]
    pub output_topic: String,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    pub openai_api_key: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    #[envconfig(default = "1000")]
    pub max_events_per_batch: usize,

    #[envconfig(default = "10")]
    pub max_event_batch_wait_seconds: u64,

    // Per-request timeout for calls to the embedding provider, covering the whole
    // request (connect through response body). Bounds a slow/hung request so it
    // can't stall batch processing indefinitely.
    #[envconfig(default = "10")]
    pub embedding_request_timeout_seconds: u64,

    #[envconfig(from = "RECENT_IDS_STORE", default = "memory")]
    pub recent_ids_store: String,

    #[envconfig(
        from = "RECENT_IDS_DYNAMODB_TABLE",
        default = "embedding_worker_recently_seen"
    )]
    pub recent_ids_dynamodb_table: String,

    // How long a recorded document stays queryable. Defaults to 1 week, matching the
    // DynamoDB table's TTL; the worker writes this as each item's `expires_at` attribute.
    #[envconfig(from = "RECENT_IDS_TTL_SECONDS", default = "604800")]
    pub recent_ids_ttl_seconds: i64,

    // Optional region override for the DynamoDB client. Falls back to the standard AWS
    // provider chain when unset.
    #[envconfig(from = "RECENT_IDS_AWS_REGION")]
    pub aws_region: Option<String>,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Our consumer is used in a transaction, so we disable offset commits.
        ConsumerConfig::set_defaults("embedding-worker", "document_embeddings_input", false);

        Self::init_from_env()
    }
}
