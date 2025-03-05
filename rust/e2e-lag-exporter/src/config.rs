use envconfig::Envconfig;
use std::time::Duration;
use tracing::Level;

#[derive(Envconfig, Debug, Clone)]
pub struct Config {
    #[envconfig(from = "KAFKA_HOSTS", default = "kafka:9092")]
    pub kafka_hosts: String,

    #[envconfig(from = "KAFKA_CONSUMERGROUP")]
    pub kafka_consumer_group: String,

    #[envconfig(from = "KAFKA_TOPIC")]
    pub kafka_topic: String,

    #[envconfig(from = "KAFKA_TLS", default = "false")]
    pub kafka_tls: bool,

    #[envconfig(from = "LOG_LEVEL", default = "info")]
    pub log_level: Level,

    #[envconfig(from = "METRICS_PORT", default = "9090")]
    pub metrics_port: u16,

    #[envconfig(from = "CHECK_INTERVAL_MS", default = "20000")]
    pub lag_check_interval_ms: u64,
}

impl Config {
    pub fn lag_check_interval(&self) -> Duration {
        Duration::from_millis(self.lag_check_interval_ms)
    }
}
