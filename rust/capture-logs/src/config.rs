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

    // When set, tokens are validated against posthog_team (cached, fail-open)
    // and unknown tokens get 401 instead of a silent consumer-side drop.
    // Unset = no validation, today's behavior.
    #[envconfig(from = "TOKEN_VALIDATION_DATABASE_URL")]
    pub token_validation_database_url: Option<String>,

    #[envconfig(from = "TOKEN_CACHE_CAPACITY", default = "100000")]
    pub token_cache_capacity: u64,

    #[envconfig(from = "TOKEN_CACHE_TTL_SECS", default = "300")]
    pub token_cache_ttl_secs: u64,

    #[envconfig(from = "MAX_REQUEST_BODY_SIZE_BYTES", default = "2097152")] // 2MB (Axum default)
    pub max_request_body_size_bytes: usize,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
