use std::fmt;
use std::str::FromStr;

use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReplicaDiscoveryMode {
    /// DNS mode: static channels to ClusterIP URL.
    Dns,
    /// K8s mode: EndpointSlice watcher with client-side p2c balancing.
    K8s,
}

impl fmt::Display for ReplicaDiscoveryMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ReplicaDiscoveryMode::Dns => write!(f, "dns"),
            ReplicaDiscoveryMode::K8s => write!(f, "k8s"),
        }
    }
}

impl FromStr for ReplicaDiscoveryMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "dns" => Ok(ReplicaDiscoveryMode::Dns),
            "k8s" => Ok(ReplicaDiscoveryMode::K8s),
            other => Err(format!(
                "unknown replica discovery mode '{other}', expected 'dns' or 'k8s'"
            )),
        }
    }
}

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

    /// URL of the personhog-replica backend (DNS mode only)
    #[envconfig(default = "http://127.0.0.1:50051")]
    pub replica_url: String,

    /// Number of gRPC channels to open to the replica service (DNS mode only).
    /// Multiple channels distribute requests across K8s service endpoints.
    #[envconfig(default = "4")]
    pub replica_channels: usize,

    /// Discovery mode for replica endpoints: "dns" (default)
    /// or "k8s" (EndpointSlice watcher with client-side balancing)
    #[envconfig(default = "dns")]
    pub replica_discovery_mode: ReplicaDiscoveryMode,

    /// Kubernetes service name to watch for replica endpoints (k8s mode only)
    #[envconfig(default = "personhog-replica")]
    pub replica_service_name: String,

    /// Kubernetes namespace for replica endpoint discovery (k8s mode only).
    /// If empty, reads from the service account mount.
    #[envconfig(default = "")]
    pub replica_service_namespace: String,

    /// gRPC port on replica pods (k8s mode only)
    #[envconfig(default = "50051")]
    pub replica_port: u16,

    /// Timeout for backend requests in milliseconds
    #[envconfig(default = "5000")]
    pub backend_timeout_ms: u64,

    /// Connect timeout for backend connections in milliseconds (k8s mode only)
    #[envconfig(default = "2000")]
    pub backend_connect_timeout_ms: u64,

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

    /// Maximum request body size the proxy will collect before forwarding,
    /// in bytes. Oversized requests are rejected with RESOURCE_EXHAUSTED.
    /// Responses stream through unbounded (see `response_size_warn_bytes`).
    #[envconfig(default = "134217728")]
    pub grpc_max_recv_message_size: usize,

    /// Log a warning when a gRPC response exceeds this size in bytes.
    /// Set to 0 to disable. Default: 10 MiB.
    #[envconfig(default = "10485760")]
    pub response_size_warn_bytes: usize,

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

    /// Maximum number of stashed write requests held per partition while
    /// a handoff is in progress. Excess requests return UNAVAILABLE and
    /// rely on caller-side retries.
    #[envconfig(default = "5000")]
    pub stash_max_messages_per_partition: usize,

    /// Maximum total payload bytes held in the stash per partition. Bounds
    /// memory pressure independent of message count, which matters when
    /// payload sizes vary widely (typical for person properties). Default
    /// is 50 MiB.
    #[envconfig(default = "52428800")]
    pub stash_max_bytes_per_partition: usize,

    /// Per-request deadline for stashed writes, in milliseconds. When
    /// drain dequeues a request whose `enqueued_at` is older than this,
    /// it returns `UNAVAILABLE` to the original caller without
    /// forwarding to the leader. This bounds individual request
    /// latency under sustained drain load and gives clients a
    /// definitive retryable error instead of an ambiguous gRPC timeout.
    /// Should be smaller than typical client gRPC timeouts (often
    /// 30+ seconds). Default 10 seconds.
    #[envconfig(default = "10000")]
    pub stash_max_wait_ms: u64,

    /// Maximum number of stashed requests to forward concurrently
    /// during a drain, grouped by `(team_id, person_id)`. Within each
    /// key the requests are forwarded sequentially to preserve per-key
    /// ordering at the leader; across keys the drain fans out to
    /// shrink wall-clock drain duration. Set to 1 to force fully
    /// sequential drain.
    #[envconfig(default = "32")]
    pub stash_drain_concurrency: usize,

    // ── coordinator (leader election among router-leader pods) ───
    /// Lease TTL for the coordinator leader election
    #[envconfig(default = "15")]
    pub coordinator_lease_ttl: i64,

    /// Keepalive interval for the coordinator lease
    #[envconfig(default = "5")]
    pub coordinator_keepalive_secs: u64,

    /// Retry interval when coordinator fails to acquire leadership
    #[envconfig(default = "5")]
    pub coordinator_election_retry_secs: u64,

    /// Debounce interval (ms) for batching pod events before rebalancing
    #[envconfig(default = "1000")]
    pub coordinator_rebalance_debounce_ms: u64,

    /// How often the coordinator re-evaluates in-flight handoffs
    /// regardless of watch events — the liveness backstop for state
    /// changes that fire no event (e.g. router departures) and for
    /// events missed before a watch attaches.
    #[envconfig(default = "5")]
    pub coordinator_reconcile_secs: u64,

    // ── K8s awareness (leader mode only) ────────────────────────
    /// Enable K8s-aware departure classification for smarter rebalancing.
    /// When disabled, falls back to lease-based behavior.
    #[envconfig(default = "false")]
    pub k8s_awareness_enabled: bool,

    /// Kubernetes namespace to watch. If empty, auto-reads from the
    /// service account mount at /var/run/secrets/kubernetes.io/serviceaccount/namespace.
    #[envconfig(default = "")]
    pub k8s_namespace: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    // ── ReplicaDiscoveryMode ──────────────────────────────────────────────────

    #[test]
    fn replica_discovery_mode_from_str_valid_variants() {
        let cases = [
            ("dns", ReplicaDiscoveryMode::Dns),
            ("k8s", ReplicaDiscoveryMode::K8s),
            // case-insensitive
            ("DNS", ReplicaDiscoveryMode::Dns),
            ("K8S", ReplicaDiscoveryMode::K8s),
            ("Dns", ReplicaDiscoveryMode::Dns),
        ];
        for (input, expected) in cases {
            let result: Result<ReplicaDiscoveryMode, _> = input.parse();
            assert_eq!(
                result.unwrap(),
                expected,
                "'{input}' should parse to {expected:?}",
            );
        }
    }

    #[test]
    fn replica_discovery_mode_from_str_invalid_returns_error() {
        let invalid_inputs = ["endpoint", "", "replica", "kubernetes", "k8s1"];
        for input in invalid_inputs {
            let result: Result<ReplicaDiscoveryMode, _> = input.parse();
            assert!(result.is_err(), "'{input}' should be an error");
            let msg = result.unwrap_err();
            assert!(
                msg.contains(input) || msg.contains("expected"),
                "error message should mention the bad input or expected values, got: {msg}",
            );
        }
    }

    #[test]
    fn replica_discovery_mode_display() {
        assert_eq!(ReplicaDiscoveryMode::Dns.to_string(), "dns");
        assert_eq!(ReplicaDiscoveryMode::K8s.to_string(), "k8s");
    }

    #[test]
    fn replica_discovery_mode_roundtrips() {
        for mode in [ReplicaDiscoveryMode::Dns, ReplicaDiscoveryMode::K8s] {
            let s = mode.to_string();
            let parsed: ReplicaDiscoveryMode = s.parse().unwrap();
            assert_eq!(
                parsed, mode,
                "Display → FromStr roundtrip failed for {mode:?}"
            );
        }
    }

    // ── RouterMode ───────────────────────────────────────────────────────────

    #[test]
    fn router_mode_from_str_valid_variants() {
        let cases = [
            ("replica", RouterMode::Replica),
            ("leader", RouterMode::Leader),
            ("REPLICA", RouterMode::Replica),
            ("LEADER", RouterMode::Leader),
        ];
        for (input, expected) in cases {
            let result: Result<RouterMode, _> = input.parse();
            assert_eq!(
                result.unwrap(),
                expected,
                "'{input}' should parse to {expected:?}"
            );
        }
    }

    #[test]
    fn router_mode_from_str_invalid_returns_error() {
        let invalid_inputs = ["dns", "", "follow", "primary"];
        for input in invalid_inputs {
            let result: Result<RouterMode, _> = input.parse();
            assert!(result.is_err(), "'{input}' should be an error");
        }
    }

    #[test]
    fn router_mode_display() {
        assert_eq!(RouterMode::Replica.to_string(), "replica");
        assert_eq!(RouterMode::Leader.to_string(), "leader");
    }

    #[test]
    fn router_mode_roundtrips() {
        for mode in [RouterMode::Replica, RouterMode::Leader] {
            let s = mode.to_string();
            let parsed: RouterMode = s.parse().unwrap();
            assert_eq!(
                parsed, mode,
                "Display → FromStr roundtrip failed for {mode:?}"
            );
        }
    }
}

impl Config {
    pub fn backend_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_timeout_ms)
    }

    pub fn backend_connect_timeout(&self) -> Duration {
        Duration::from_millis(self.backend_connect_timeout_ms)
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

    pub fn coordinator_keepalive_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_keepalive_secs)
    }

    pub fn coordinator_election_retry_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_election_retry_secs)
    }

    pub fn coordinator_rebalance_debounce_interval(&self) -> Duration {
        Duration::from_millis(self.coordinator_rebalance_debounce_ms)
    }

    pub fn coordinator_reconcile_interval(&self) -> Duration {
        Duration::from_secs(self.coordinator_reconcile_secs)
    }

    pub fn stash_max_wait(&self) -> Duration {
        Duration::from_millis(self.stash_max_wait_ms)
    }

    /// Resolve the replica service namespace from config or the service account mount.
    pub fn resolve_replica_namespace(&self) -> Result<String, String> {
        if !self.replica_service_namespace.is_empty() {
            return Ok(self.replica_service_namespace.clone());
        }
        std::fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
            .map(|s| s.trim().to_string())
            .map_err(|e| {
                format!(
                    "replica_service_namespace not set and failed to read from service account: {e}"
                )
            })
    }

    /// Resolve the K8s namespace from config or the service account mount.
    pub fn resolve_k8s_namespace(&self) -> Result<String, String> {
        if !self.k8s_namespace.is_empty() {
            return Ok(self.k8s_namespace.clone());
        }
        std::fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
            .map(|s| s.trim().to_string())
            .map_err(|e| {
                format!("k8s_namespace not set and failed to read from service account: {e}")
            })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct RetryConfig {
    pub max_retries: u32,
    pub initial_backoff_ms: u64,
    pub max_backoff_ms: u64,
}
