use std::sync::atomic::{AtomicUsize, Ordering};

use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

// TODO - I'm just too lazy to pipe this all the way through the resolve call stack
pub static FRAME_CONTEXT_LINES: AtomicUsize = AtomicUsize::new(15);

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "clickhouse_events_json")]
    pub events_topic: String,

    #[envconfig(default = "clickhouse_error_tracking_issue_fingerprint")]
    pub issue_overrides_topic: String,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // cymbal makes HTTP get requests to auto-resolve sourcemaps - and follows redirects. To protect against SSRF, we only allow requests to public URLs by default
    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,

    #[envconfig(default = "30")]
    pub sourcemap_timeout_seconds: u64,

    #[envconfig(default = "100000000")] // 100MB - in prod, we should use closer to 1-10GB
    pub symbol_store_cache_max_bytes: usize,

    #[envconfig(default = "http://127.0.0.1:19000")] // minio
    pub object_storage_endpoint: String,

    #[envconfig(default = "symbol_sets")]
    pub object_storage_bucket: String,

    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,

    #[envconfig(default = "object_storage_root_user")]
    pub object_storage_access_key_id: String,

    #[envconfig(default = "object_storage_root_password")]
    pub object_storage_secret_access_key: String,

    #[envconfig(default = "symbolsets")]
    pub ss_prefix: String,

    #[envconfig(default = "100000")]
    pub frame_cache_size: u64,

    #[envconfig(default = "600")]
    pub frame_cache_ttl_seconds: u64,

    // When we resolve a frame, we put it in PG, so other instances of cymbal can
    // use it, or so we can re-use it after a restart. This is the TTL for that,
    // after this many minutes we'll discard saved resolution results and re-resolve
    // TODO - 10 minutes is too short for production use, it's only twice as long as
    // our in-memory caching. We should do at least an hour once we release
    #[envconfig(default = "10")]
    pub frame_result_ttl_minutes: u32,

    // Maximum number of lines of pre and post context to get per frame
    #[envconfig(default = "15")]
    pub context_line_count: usize,

    #[envconfig(default = "1000")]
    pub max_events_per_batch: usize,

    #[envconfig(default = "10")]
    pub max_event_batch_wait_seconds: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        // Our consumer is used in a transaction, so we disable offset commits.
        ConsumerConfig::set_defaults(
            "error-tracking-rs",
            "exception_symbolification_events",
            false,
        );
        let res = Self::init_from_env()?;
        init_global_state(&res);
        Ok(res)
    }
}

pub fn init_global_state(config: &Config) {
    FRAME_CONTEXT_LINES.store(config.context_line_count, Ordering::Relaxed);
}
