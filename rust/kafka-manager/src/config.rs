use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3308")]
    pub port: u16,

    /// A pod that has not reported for this long is evicted from fleet state.
    /// Must comfortably exceed the clients' report interval (default 10s) so
    /// a single lost report does not flap the fleet view.
    #[envconfig(from = "POD_TTL_SECONDS", default = "60")]
    pub pod_ttl_seconds: u64,

    #[envconfig(from = "SWEEP_INTERVAL_SECONDS", default = "5")]
    pub sweep_interval_seconds: u64,
}
