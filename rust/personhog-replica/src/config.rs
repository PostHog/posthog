use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50051")]
    pub grpc_address: SocketAddr,

    /// Storage backend to use. Currently supported: "postgres"
    #[envconfig(default = "postgres")]
    pub storage_backend: String,

    /// Primary database URL (for writes and strong consistency reads)
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub primary_database_url: String,

    /// Replica database URL (for eventual consistency reads)
    /// If not set, falls back to primary_database_url
    #[envconfig(default = "")]
    pub replica_database_url: String,

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

    /// Max connections for the bulk pool (large batch reads, deletes).
    /// Kept small so bulk queries can't starve the fast pool.
    #[envconfig(default = "5")]
    pub bulk_max_pg_connections: u32,

    /// Statement timeout for bulk queries (ms). Longer than the fast pool
    /// because batch reads over thousands of IDs legitimately take seconds.
    #[envconfig(default = "30000")]
    pub bulk_statement_timeout_ms: u64,

    /// Acquire timeout for bulk pool (seconds).
    #[envconfig(default = "10")]
    pub bulk_acquire_timeout_secs: u64,

    /// Number of items per chunk when splitting bulk operations (reads and
    /// deletes) into parallel queries.
    #[envconfig(default = "200")]
    pub bulk_chunk_size: usize,

    /// Maximum number of chunks to execute concurrently. Each concurrent
    /// chunk holds a connection from the bulk pool, so this should not
    /// exceed bulk_max_pg_connections. Kept conservative to limit burst
    /// load on the database when multiple callers delete concurrently.
    #[envconfig(default = "2")]
    pub bulk_max_concurrent_chunks: usize,

    /// Maximum number of server-side (PgBouncer → Postgres) connections to
    /// warm at startup via SELECT 1. Clamped to min_pg_connections. Set to 0
    /// to skip server-side warming entirely.
    #[envconfig(default = "3")]
    pub warmup_server_connections: u32,

    #[envconfig(default = "10")]
    pub pool_monitor_interval_secs: u64,

    #[envconfig(default = "9100")]
    pub metrics_port: u16,

    /// Interval between HTTP/2 keepalive pings sent by the gRPC server (0 = disabled)
    #[envconfig(default = "30")]
    pub grpc_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack before considering the connection dead
    #[envconfig(default = "10")]
    pub grpc_keepalive_timeout_secs: u64,

    /// Maximum gRPC message size to encode (send), in bytes. Defaults to 128 MiB.
    #[envconfig(default = "134217728")]
    pub grpc_max_send_message_size: usize,

    /// Maximum gRPC message size to decode (receive), in bytes.
    #[envconfig(default = "134217728")]
    pub grpc_max_recv_message_size: usize,

    /// Maximum age of a gRPC connection in seconds before the server sends GOAWAY.
    /// Clients reconnect transparently, naturally staggering across pods.
    /// 0 = disabled (connections live indefinitely).
    #[envconfig(default = "300")]
    pub grpc_max_connection_age_secs: u64,

    /// Maximum concurrent gRPC requests before load shedding.
    /// When exceeded, new requests get an immediate UNAVAILABLE response
    /// so the router retries on another pod. 0 = disabled.
    #[envconfig(default = "0")]
    pub max_concurrent_requests: usize,

    /// Enable gzip response compression via AsyncGzipLayer. When enabled,
    /// responses to clients that send `grpc-accept-encoding: gzip` are
    /// compressed on a blocking thread pool instead of the tokio runtime.
    #[envconfig(default = "false")]
    pub gzip_response_compression: bool,

    /// Gzip compression level (1–9). Lower is faster, higher compresses more.
    #[envconfig(default = "6")]
    pub gzip_compression_level: u32,

    /// Minimum response payload size (bytes) to compress. Responses smaller
    /// than this pass through uncompressed.
    #[envconfig(default = "256")]
    pub gzip_min_payload_size: usize,

    /// Maximum response size (bytes) enforced after gzip compression. Applies
    /// to the final wire size — compressed bytes for gzip responses, raw bytes
    /// for uncompressed passthrough. 0 = disabled. Default 4 MiB.
    #[envconfig(default = "4194304")]
    pub gzip_max_response_size: usize,

    /// When true, responses exceeding `gzip_max_response_size` are rejected
    /// with a gRPC OUT_OF_RANGE error. When false, the metric fires but the
    /// response is delivered normally (monitor mode).
    #[envconfig(default = "false")]
    pub gzip_max_response_size_enforce: bool,
}

impl Config {
    pub fn acquire_timeout(&self) -> Duration {
        Duration::from_secs(self.acquire_timeout_secs)
    }

    pub fn bulk_acquire_timeout(&self) -> Duration {
        Duration::from_secs(self.bulk_acquire_timeout_secs)
    }

    pub fn bulk_statement_timeout(&self) -> Option<u64> {
        if self.bulk_statement_timeout_ms == 0 {
            None
        } else {
            Some(self.bulk_statement_timeout_ms)
        }
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

    pub fn grpc_max_connection_age(&self) -> Option<Duration> {
        if self.grpc_max_connection_age_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_max_connection_age_secs))
        }
    }

    /// Returns the replica database URL, falling back to primary if not set
    pub fn replica_database_url(&self) -> &str {
        if self.replica_database_url.is_empty() {
            &self.primary_database_url
        } else {
            &self.replica_database_url
        }
    }
}
