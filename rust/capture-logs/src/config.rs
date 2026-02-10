use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

use capture::config::KafkaConfig;

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

    #[envconfig(from = "DATABASE_URL", default = "")]
    pub database_url: String,

    #[envconfig(from = "TEAM_RESOLVER_CACHE_TTL_SECS", default = "300")]
    pub team_resolver_cache_ttl_secs: u64,

    #[envconfig(from = "TEAM_RESOLVER_MAX_POOL_SIZE", default = "5")]
    pub team_resolver_max_pool_size: u32,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
