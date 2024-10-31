use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(nested = true)]
    pub consumer: ConsumerConfig,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // These are unused for now, but useful while iterating in prod
    #[envconfig(default = "true")]
    pub skip_writes: bool,

    #[envconfig(default = "true")]
    pub skip_reads: bool,

    // cymbal makes HTTP get requests to auto-resolve sourcemaps - and follows redirects. To protect against SSRF, we only allow requests to public URLs by default
    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,

    #[envconfig(default = "30")]
    pub sourcemap_timeout_seconds: u64,

    #[envconfig(default = "100000000")] // 100MB - in prod, we should use closer to 1-10GB
    pub symbol_store_cache_max_bytes: usize,

    #[envconfig(default = "symbol_sets")]
    pub ss_bucket: String,

    #[envconfig(default = "sets")]
    pub ss_prefix: String,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        ConsumerConfig::set_defaults("error-tracking-rs", "exception_symbolification_events");
        Self::init_from_env()
    }
}
