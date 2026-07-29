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

    /// Redis holding the billing quota-limit sorted sets that `ee/billing/quota_limiting.py`
    /// writes under `@posthog/quota-limits/<resource>`. Falls back to `REDIS_URL`. When neither
    /// is set the service does not enforce quota at all, so a deployment that has not been given
    /// a Redis keeps accepting over-quota traffic exactly as it did before.
    pub quota_limiting_redis_url: Option<String>,

    pub redis_url: Option<String>,

    /// Killswitch for the capture-side quota rejection, leaving enforcement to the consumer.
    #[envconfig(from = "QUOTA_LIMITING_ENABLED", default = "true")]
    pub quota_limiting_enabled: bool,

    #[envconfig(from = "QUOTA_LIMITING_REFRESH_INTERVAL_SECONDS", default = "30")]
    pub quota_limiting_refresh_interval_seconds: u64,

    /// Advertised in `Retry-After` when a request is rejected for being over quota.
    ///
    /// This is a bounded poll interval rather than the limit's true expiry, which is available
    /// as the sorted-set score. A billing limit runs until the end of the billing period, so
    /// the true expiry can be weeks away, but it is also lifted the moment a customer raises
    /// their limit. Advertising the real expiry would leave a recovered project dark for the
    /// rest of the period, so clients are told to check back on an interval instead.
    #[envconfig(from = "QUOTA_LIMITING_RETRY_AFTER_SECONDS", default = "900")]
    pub quota_limiting_retry_after_seconds: u64,

    pub redis_key_prefix: Option<String>,

    #[envconfig(from = "REDIS_RESPONSE_TIMEOUT_MS", default = "1000")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(from = "REDIS_CONNECTION_TIMEOUT_MS", default = "3000")]
    pub redis_connection_timeout_ms: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }

    pub fn quota_redis_url(&self) -> Option<&str> {
        self.quota_limiting_redis_url
            .as_deref()
            .or(self.redis_url.as_deref())
    }
}
