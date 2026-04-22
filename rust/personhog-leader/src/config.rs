use std::net::SocketAddr;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50053")]
    pub grpc_address: SocketAddr,

    /// In-memory cache capacity in number of entries
    #[envconfig(default = "100000")]
    pub cache_memory_capacity: usize,

    #[envconfig(default = "9102")]
    pub metrics_port: u16,

    // ── Kafka durability ─────────────────────────────────────────
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "personhog_updates")]
    pub kafka_person_state_topic: String,

    // ── PG fallback ───────────────────────────────────────────────
    /// Read-only Postgres URL for cache miss fallback. If empty, cache
    /// misses return NotFound without querying PG.
    #[envconfig(default = "")]
    pub fallback_database_url: String,

    #[envconfig(default = "5")]
    pub fallback_pg_max_connections: u32,

    /// Keep at least this many connections warm so the first cache-miss
    /// after a quiet period doesn't pay the TCP+auth handshake tax.
    #[envconfig(default = "1")]
    pub fallback_pg_min_connections: u32,

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
