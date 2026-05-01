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

    // ── Warming ──────────────────────────────────────────────────
    /// Consumer group name used by the writer pod. The leader queries this
    /// group's committed offsets during warming: any Kafka message at or
    /// after the writer's committed offset has not yet been persisted to PG,
    /// so it must live in the leader's cache to avoid stale PG fallback
    /// reads.
    #[envconfig(default = "personhog-writer")]
    pub writer_consumer_group: String,

    /// How many offsets to rewind past the writer's committed offset when
    /// warming. Pure safety margin — any non-negative value is correct, but
    /// a larger value is more forgiving of momentary races between the
    /// writer's commit and our observation of it. Bounded above by Kafka's
    /// earliest available offset.
    #[envconfig(default = "1000")]
    pub warm_lookback_offsets: i64,

    /// Timeout for the OffsetFetch round-trip that asks the writer's
    /// consumer group for its committed offset.
    #[envconfig(default = "5")]
    pub warm_committed_offsets_timeout_secs: u64,

    /// Timeout for the per-partition `fetch_watermarks` metadata call.
    #[envconfig(default = "5")]
    pub warm_fetch_watermarks_timeout_secs: u64,

    /// Per-message receive timeout while consuming the warming range. If
    /// hit, warming aborts with the offsets seen so far so the partition
    /// can be retried fresh.
    #[envconfig(default = "10")]
    pub warm_recv_timeout_secs: u64,

    /// Maximum attempts for retryable warming metadata calls
    /// (committed-offset query, fetch-watermarks).
    #[envconfig(default = "3")]
    pub warm_retry_max_attempts: u32,

    /// Initial backoff between warming-step retries; doubles each attempt
    /// up to `warm_retry_max_backoff_ms`.
    #[envconfig(default = "500")]
    pub warm_retry_initial_backoff_ms: u64,

    /// Cap on the exponential backoff between warming-step retries.
    #[envconfig(default = "5000")]
    pub warm_retry_max_backoff_ms: u64,

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
