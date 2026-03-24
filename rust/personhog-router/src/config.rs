use std::fmt;
use std::str::FromStr;

use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RouterMode {
    /// Replica-only mode: all requests go to personhog-replica.
    Replica,
    /// Leader mode: person writes and strong reads go to leader pods
    /// via etcd-coordinated partition routing. Everything else goes to replica.
    Leader,
}

impl fmt::Display for RouterMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RouterMode::Replica => write!(f, "replica"),
            RouterMode::Leader => write!(f, "leader"),
        }
    }
}

impl FromStr for RouterMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "replica" => Ok(RouterMode::Replica),
            "leader" => Ok(RouterMode::Leader),
            other => Err(format!(
                "unknown router mode '{other}', expected 'replica' or 'leader'"
            )),
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50052")]
    pub grpc_address: SocketAddr,

    /// Router mode: "replica" (default) or "leader"
    #[envconfig(default = "replica")]
    pub router_mode: RouterMode,

    /// URL of the personhog-replica backend
    #[envconfig(default = "http://127.0.0.1:50051")]
    pub replica_url: String,

    /// Timeout for backend requests in milliseconds
    #[envconfig(default = "5000")]
    pub backend_timeout_ms: u64,

    #[envconfig(default = "9101")]
    pub metrics_port: u16,

    /// Maximum number of retry attempts for transient backend errors (0 = no retries)
    #[envconfig(default = "3")]
    pub max_retries: u32,

    /// Initial backoff delay in milliseconds before the first retry
    #[envconfig(default = "25")]
    pub initial_backoff_ms: u64,

    /// Maximum backoff delay in milliseconds (caps exponential growth)
    #[envconfig(default = "500")]
    pub max_backoff_ms: u64,

    /// Interval between HTTP/2 keepalive pings sent by the gRPC server (0 = disabled)
    #[envconfig(default = "30")]
    pub grpc_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack before considering the connection dead
    #[envconfig(default = "10")]
    pub grpc_keepalive_timeout_secs: u64,

    /// Interval between HTTP/2 keepalive pings sent to the replica backend (0 = disabled)
    #[envconfig(default = "30")]
    pub backend_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack from the replica backend
    #[envconfig(default = "10")]
    pub backend_keepalive_timeout_secs: u64,

    // ── etcd coordination (leader mode only) ─────────────────────
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    /// Router name for etcd registration (typically set from K8s downward API)
    #[envconfig(default = "router-0")]
    pub pod_name: String,

    #[envconfig(default = "30")]
    pub lease_ttl: i64,

    #[envconfig(default = "10")]
    pub heartbeat_interval_secs: u64,

    /// Leader gRPC port used when resolving pod names to addresses
    #[envconfig(default = "50053")]
    pub leader_port: u16,
}

impl Config {
    pub fn backend_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_timeout_ms)
    }

    pub fn grpc_keepalive_interval(&self) -> Option<Duration> {
        if self.grpc_keepalive_interval_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_keepalive_interval_secs))
        }
    }

    pub fn grpc_keepalive_timeout(&self) -> Option<Duration> {
        if self.grpc_keepalive_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_keepalive_timeout_secs))
        }
    }

    pub fn backend_keepalive_interval(&self) -> Option<Duration> {
        if self.backend_keepalive_interval_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.backend_keepalive_interval_secs))
        }
    }

    pub fn backend_keepalive_timeout(&self) -> Option<Duration> {
        if self.backend_keepalive_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.backend_keepalive_timeout_secs))
        }
    }

    pub fn retry_config(&self) -> RetryConfig {
        RetryConfig {
            max_retries: self.max_retries,
            initial_backoff_ms: self.initial_backoff_ms,
            max_backoff_ms: self.max_backoff_ms,
        }
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    pub fn heartbeat_interval(&self) -> Duration {
        Duration::from_secs(self.heartbeat_interval_secs)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub initial_backoff_ms: u64,
    pub max_backoff_ms: u64,
}
