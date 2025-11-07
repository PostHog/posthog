use envconfig::Envconfig;

use capture::config::KafkaConfig;

#[derive(Envconfig, Clone)]
pub struct Config {
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
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        Ok(res)
    }
}
