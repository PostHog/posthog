//! Service configuration, loaded from environment variables via `envconfig`
//! (pattern mirrors `rust/feature-flags/src/config.rs` and the shuffler's `config.rs`).
//!
//! PR 1.3 adds the Postgres reader and filter-catalog refresh knobs. The Kafka topics/consumer
//! groups, RocksDB path and tuning, sweep interval + `safety_margin_ms`, S3 checkpoint
//! settings, cascade caps, and kill-switch list are added by their respective Phase 1–3 PRs
//! (TDD §6) as each subsystem is wired in.

use std::time::Duration;

use common_database::PoolConfig;
use envconfig::Envconfig;

const POOL_NAME: &str = "posthog_cohort";

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// Host for the observability HTTP server (`/_health`, `/_ready`, `/metrics`).
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    /// Port for the observability HTTP server. Overridden by the Helm values in PR 1.11.
    #[envconfig(default = "3323")]
    pub bind_port: u16,

    /// Install the Prometheus recorder and expose `/metrics`.
    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    // ── Postgres (posthog_cohort realtime filter catalog) ─────────────────
    /// DSN for the main PostHog database that owns `posthog_cohort`.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub pg_acquire_timeout_secs: u64,

    /// Statement timeout for the catalog SELECT (ms). `0` → database default.
    #[envconfig(default = "5000")]
    pub pg_statement_timeout_ms: u64,

    // ── Filter catalog refresh ────────────────────────────────────────────
    #[envconfig(default = "300")]
    pub filter_catalog_refresh_secs: u64,

    #[envconfig(default = "60")]
    pub filter_catalog_refresh_jitter_secs: u64,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn filter_catalog_refresh_interval(&self) -> Duration {
        Duration::from_secs(self.filter_catalog_refresh_secs)
    }

    pub fn filter_catalog_refresh_jitter(&self) -> Duration {
        Duration::from_secs(self.filter_catalog_refresh_jitter_secs)
    }

    fn pg_statement_timeout(&self) -> Option<u64> {
        (self.pg_statement_timeout_ms != 0).then_some(self.pg_statement_timeout_ms)
    }

    /// Pool config for the catalog reader: small (defaults min 1 / max 5) since the only query
    /// is the periodic `SELECT … FROM posthog_cohort` refresh.
    pub fn pool_config(&self) -> PoolConfig {
        PoolConfig {
            min_connections: self.min_pg_connections,
            max_connections: self.max_pg_connections,
            acquire_timeout: Duration::from_secs(self.pg_acquire_timeout_secs),
            idle_timeout: Some(Duration::from_secs(300)),
            test_before_acquire: true,
            statement_timeout_ms: self.pg_statement_timeout(),
            pool_name: Some(POOL_NAME.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> Config {
        Config {
            bind_host: "0.0.0.0".to_string(),
            bind_port: 3323,
            export_prometheus: true,
            database_url: "postgres://posthog:posthog@localhost:5432/posthog".to_string(),
            min_pg_connections: 1,
            max_pg_connections: 5,
            pg_acquire_timeout_secs: 10,
            pg_statement_timeout_ms: 5000,
            filter_catalog_refresh_secs: 300,
            filter_catalog_refresh_jitter_secs: 60,
        }
    }

    #[test]
    fn refresh_interval_and_jitter_map_from_seconds() {
        let config = test_config();
        assert_eq!(
            config.filter_catalog_refresh_interval(),
            Duration::from_secs(300)
        );
        assert_eq!(
            config.filter_catalog_refresh_jitter(),
            Duration::from_secs(60)
        );
    }

    #[test]
    fn statement_timeout_zero_means_database_default() {
        let mut config = test_config();
        config.pg_statement_timeout_ms = 0;
        assert!(config.pool_config().statement_timeout_ms.is_none());
    }

    #[test]
    fn pool_config_uses_the_named_pool() {
        let config = test_config();
        assert_eq!(config.pool_config().pool_name.as_deref(), Some(POOL_NAME));
    }
}
