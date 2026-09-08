use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    /// Bind addresses, Kafka, body limits: the same settings as capture-logs.
    #[envconfig(nested = true)]
    pub base: capture_logs::config::Config,

    /// Shares the set of recently labelled metric series between pods. Unset
    /// means the series label gate runs with its local cache only.
    #[envconfig(from = "REDIS_URL")]
    pub redis_url: Option<String>,

    /// When false the gate still tracks series and reports metrics but leaves
    /// every row labelled, so the switch can flip once the metrics2 read path
    /// takes labels from the series rollup.
    #[envconfig(from = "METRICS_SERIES_LABEL_GATE_ENABLED", default = "false")]
    pub metrics_series_label_gate_enabled: bool,

    #[envconfig(from = "METRICS_SERIES_LABEL_INTERVAL_SECS", default = "1800")]
    pub metrics_series_label_interval_secs: u64,

    #[envconfig(from = "METRICS_SERIES_REDIS_TIMEOUT_MS", default = "250")]
    pub metrics_series_redis_timeout_ms: u64,

    /// The pull reads the whole recent series set, so it gets a longer budget
    /// than a single write batch.
    #[envconfig(from = "METRICS_SERIES_REDIS_SEED_TIMEOUT_MS", default = "5000")]
    pub metrics_series_redis_seed_timeout_ms: u64,

    #[envconfig(from = "METRICS_SERIES_REDIS_PULL_INTERVAL_SECS", default = "60")]
    pub metrics_series_redis_pull_interval_secs: u64,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        Self::init_from_env()
    }
}
