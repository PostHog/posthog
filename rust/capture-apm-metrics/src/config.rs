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

    /// Total time the service waits at startup for the series cache seed. When
    /// it runs out the service starts with the pages read so far.
    #[envconfig(from = "METRICS_SERIES_REDIS_SEED_TIMEOUT_MS", default = "15000")]
    pub metrics_series_redis_seed_timeout_ms: u64,

    /// Budget for one periodic pull. Each pull reads only the series labelled
    /// since the previous one, so it is much smaller than the seed.
    #[envconfig(from = "METRICS_SERIES_REDIS_PULL_TIMEOUT_MS", default = "5000")]
    pub metrics_series_redis_pull_timeout_ms: u64,

    #[envconfig(from = "METRICS_SERIES_REDIS_PULL_INTERVAL_SECS", default = "60")]
    pub metrics_series_redis_pull_interval_secs: u64,

    /// Caps on the local series cache, in entries. Ingestion input drives the
    /// cache, so without them a caller with a valid token shape and changing
    /// labels could grow it without limit.
    #[envconfig(from = "METRICS_SERIES_CACHE_MAX_ENTRIES", default = "20000000")]
    pub metrics_series_cache_max_entries: usize,

    #[envconfig(
        from = "METRICS_SERIES_CACHE_MAX_ENTRIES_PER_TOKEN",
        default = "2000000"
    )]
    pub metrics_series_cache_max_entries_per_token: usize,
}

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let config = Self::init_from_env()?;
        // A zero pull interval panics the puller task, which would stop
        // cross-pod convergence while the service keeps serving traffic.
        if config.metrics_series_redis_pull_interval_secs == 0 {
            return Err(envconfig::Error::ParseError {
                name: "METRICS_SERIES_REDIS_PULL_INTERVAL_SECS",
            });
        }
        Ok(config)
    }
}
