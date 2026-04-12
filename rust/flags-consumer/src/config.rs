use envconfig::Envconfig;
use std::time::Duration;

/// Configuration for the `flags-consumer` service.
///
/// The service talks to the dedicated `flags_read_store` PostgreSQL database.
/// Step 1 is a skeleton: the config exposes the DB URL, pool sizing, and
/// observability settings. Kafka, CDC, and consumer-specific knobs will be
/// added when the CDC consumer logic lands.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// DB URL for the dedicated flags read store.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/flags_read_store")]
    pub flags_read_store_database_url: String,

    /// Matches the behavioral_cohorts reader pool sizing in
    /// `rust/feature-flags/src/database_pools.rs:275`: a small pool with an
    /// aggressive statement timeout, since the read path is a single PK/GIN lookup.
    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    /// Keep this tight — the read path is a single PK/GIN lookup.
    #[envconfig(default = "1000")]
    pub statement_timeout_ms: u64,

    #[envconfig(default = "10")]
    pub pool_monitor_interval_secs: u64,

    #[envconfig(default = "9102")]
    pub metrics_port: u16,
}

impl Config {
    pub fn acquire_timeout(&self) -> Duration {
        Duration::from_secs(self.acquire_timeout_secs)
    }

    pub fn idle_timeout(&self) -> Option<Duration> {
        if self.idle_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.idle_timeout_secs))
        }
    }

    pub fn statement_timeout(&self) -> Option<u64> {
        if self.statement_timeout_ms == 0 {
            None
        } else {
            Some(self.statement_timeout_ms)
        }
    }
}
