use std::time::Duration;

use envconfig::Envconfig;
use std::net::SocketAddr;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50053")]
    pub grpc_address: SocketAddr,

    /// In-memory cache capacity in number of entries
    #[envconfig(default = "100000")]
    pub cache_memory_capacity: usize,

    #[envconfig(default = "9102")]
    pub metrics_port: u16,

    // ── etcd coordination ────────────────────────────────────────
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    /// Pod name for etcd registration (typically set from K8s downward API)
    #[envconfig(default = "leader-0")]
    pub pod_name: String,

    #[envconfig(default = "30")]
    pub lease_ttl: i64,

    #[envconfig(default = "10")]
    pub heartbeat_interval_secs: u64,
}

impl Config {
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
