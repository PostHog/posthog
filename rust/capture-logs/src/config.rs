use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;

use capture::config::KafkaConfig;
use capture::emergency_kafka_fallback::EmergencyKafkaFallback;

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
}

impl Config {
    pub fn init_with_defaults() -> anyhow::Result<Self> {
        let mut res = Self::init_from_env()?;
        if let Some(fallback) = EmergencyKafkaFallback::from_env(&std::env::vars().collect())? {
            fallback.apply_to_kafka(&mut res.kafka);
            fallback.log_active();
        }
        Ok(res)
    }
}
