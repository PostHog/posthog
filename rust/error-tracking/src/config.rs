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

    #[envconfig(default = "300")]
    pub team_cache_ttl_secs: u64,

    #[envconfig(default = "10000")]
    pub team_cache_capacity: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        ConsumerConfig::set_defaults("error-tracking-rs", "exceptions_ingestions");
        Self::init_from_env()
    }
}
