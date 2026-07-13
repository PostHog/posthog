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

    // Self-metrics push to PostHog's own metrics ingest — same env contract as the
    // Node.js services; off unless both URL and token are set.
    #[envconfig(from = "OTEL_METRICS_EXPORT_URL")]
    pub otel_metrics_export_url: Option<String>,

    #[envconfig(from = "OTEL_METRICS_EXPORT_TOKEN")]
    pub otel_metrics_export_token: Option<String>,

    #[envconfig(from = "OTEL_METRICS_EXPORT_INTERVAL_MS", default = "15000")]
    pub otel_metrics_export_interval_ms: u64,

    #[envconfig(from = "OTEL_SERVICE_NAME", default = "capture-logs")]
    pub otel_service_name: String,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
