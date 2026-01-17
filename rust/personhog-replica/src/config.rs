use envconfig::Envconfig;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;

use crate::vnode::{RoutingConfig, RoutingMode, VnodeConfigError, VnodeOwnership};

/// Person cache backend options.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PersonCacheBackend {
    /// No caching - all requests pass through directly to storage.
    None,
}

impl FromStr for PersonCacheBackend {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "none" | "disabled" | "passthrough" => Ok(Self::None),
            _ => Err(format!("Unknown person cache backend: {s}")),
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50051")]
    pub grpc_address: SocketAddr,

    /// Storage backend to use. Currently supported: "postgres"
    #[envconfig(default = "postgres")]
    pub storage_backend: String,

    /// Person cache backend. Controls whether person lookups are cached.
    /// Currently supported: "none" (passthrough, no caching)
    #[envconfig(default = "none")]
    pub person_cache_backend: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "0")]
    pub min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    #[envconfig(default = "5000")]
    pub statement_timeout_ms: u64,

    #[envconfig(default = "9100")]
    pub metrics_port: u16,

    /// Routing awareness mode. Controls how the service handles requests for vnodes
    /// it doesn't own.
    /// - "disabled" (default): No routing checks, serve all requests
    /// - "observe": Check routing, emit metrics on misroutes, still serve requests
    /// - "enforce": Check routing, emit metrics and reject misrouted requests
    #[envconfig(default = "disabled")]
    pub routing_mode: String,

    /// Path to the vnode configuration file (JSON format).
    /// Required when routing_mode is "observe" or "enforce".
    /// Example: /etc/personhog/vnodes.json
    #[envconfig(default = "")]
    pub vnode_config_path: String,

    /// Pod name for vnode ownership lookup.
    /// Typically set from the Kubernetes downward API (metadata.name).
    /// Required when routing_mode is "observe" or "enforce".
    #[envconfig(default = "")]
    pub pod_name: String,
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

    /// Parse the person cache backend configuration.
    /// Panics if the configured value is not recognized.
    pub fn person_cache(&self) -> PersonCacheBackend {
        self.person_cache_backend
            .parse()
            .unwrap_or_else(|e: String| panic!("{}", e))
    }

    /// Parse the routing mode configuration.
    /// Panics if the configured value is not recognized.
    pub fn routing_mode(&self) -> RoutingMode {
        self.routing_mode.parse().unwrap_or_else(|_| {
            panic!(
                "Unknown routing mode: {}. Supported: disabled, observe, enforce",
                self.routing_mode
            )
        })
    }

    /// Build the routing configuration from environment settings.
    ///
    /// Returns a disabled config if routing_mode is "disabled".
    /// Otherwise, loads the vnode ownership from the config file.
    ///
    /// Panics if routing is enabled but config file or pod name is missing/invalid.
    pub fn routing_config(&self) -> Result<RoutingConfig, VnodeConfigError> {
        let mode = self.routing_mode();

        if mode == RoutingMode::Disabled {
            return Ok(RoutingConfig::disabled());
        }

        // Routing is enabled, we need config file and pod name
        if self.vnode_config_path.is_empty() {
            panic!(
                "VNODE_CONFIG_PATH is required when routing_mode is '{}'",
                self.routing_mode
            );
        }

        if self.pod_name.is_empty() {
            panic!(
                "POD_NAME is required when routing_mode is '{}'",
                self.routing_mode
            );
        }

        let config_path = PathBuf::from(&self.vnode_config_path);
        let ownership = VnodeOwnership::load(&config_path, &self.pod_name)?;

        Ok(RoutingConfig::new(mode, ownership))
    }
}
