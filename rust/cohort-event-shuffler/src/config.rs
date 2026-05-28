//! Service configuration, loaded from environment variables via `envconfig`
//! (pattern mirrors `rust/feature-flags/src/config.rs`).
//!
//! The skeleton only needs the observability bind address. The Kafka consumer/producer
//! settings and the `posthog_cohort` polling interval are added in PR 1.1 (TDD §6.1) as
//! the consume → re-key → produce path is implemented.

use envconfig::Envconfig;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// Host for the observability HTTP server (`/_health`, `/_ready`, `/metrics`).
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    /// Port for the observability HTTP server. Overridden by the Helm values in PR 1.11.
    #[envconfig(default = "3322")]
    pub bind_port: u16,

    /// Install the Prometheus recorder and expose `/metrics`.
    #[envconfig(default = "true")]
    pub export_prometheus: bool,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }
}
