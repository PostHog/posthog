use envconfig::Envconfig;

use common_kafka::config::KafkaConfig;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3302")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub database_url: String,

    #[envconfig(default = "30")]
    pub cleanup_interval_secs: u64,

    // The cleanup task needs to have special knowledge of the queue it's cleaning up. This is so it
    // can do things like flush the proper app_metrics or plugin_log_entries, and so it knows what
    // to expect in the job's payload JSONB column.
    #[envconfig(default = "webhooks")]
    pub mode: String,

    #[envconfig(default = "false")]
    pub hog_mode: bool,

    #[envconfig(default = "clickhouse_app_metrics")]
    pub app_metrics_topic: String,

    #[envconfig(default = "clickhouse_app_metrics2")]
    pub app_metrics2_topic: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,
}

impl Config {
    pub fn bind(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}
