use common_database::PoolConfig;
use envconfig::Envconfig;
use personhog_common::h2_window::{Http2Windows, WindowSize};
use std::net::SocketAddr;
use std::num::NonZeroU32;
use std::time::Duration;

use crate::pools::Lane;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50055")]
    pub grpc_address: SocketAddr,

    /// Primary database URL. All identity work (resolution and stub creation)
    /// runs on the primary — the identity plane is synchronous with Postgres.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub primary_database_url: String,

    #[envconfig(nested = true)]
    pub tables: IdentityTablesConfig,

    /// Fast pool (see `crate::pools`).
    #[envconfig(default = "10")]
    pub max_pg_connections: u32,

    #[envconfig(default = "0")]
    pub min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    #[envconfig(default = "5000")]
    pub statement_timeout_ms: u64,

    /// Heavy pool, sized separately so a burst of long transactions cannot
    /// take the fast pool's slots.
    #[envconfig(default = "10")]
    pub heavy_max_pg_connections: u32,

    #[envconfig(default = "0")]
    pub heavy_min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub heavy_acquire_timeout_secs: u64,

    #[envconfig(default = "5000")]
    pub heavy_statement_timeout_ms: u64,

    /// Applies to both pools.
    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    /// Maximum number of server-side (PgBouncer → Postgres) connections to
    /// warm at startup via SELECT 1. Clamped to min_pg_connections. Set to 0
    /// to skip server-side warming entirely.
    #[envconfig(default = "3")]
    pub warmup_server_connections: u32,

    #[envconfig(default = "10")]
    pub pool_monitor_interval_secs: u64,

    #[envconfig(default = "9108")]
    pub metrics_port: u16,

    /// Maximum entries per batch RPC.
    #[envconfig(default = "250")]
    pub max_batch_size: usize,

    /// Maximum accepted distinct_id length in bytes. Must not exceed the
    /// posthog_persondistinctid.distinct_id column limit (varchar(400)).
    #[envconfig(default = "400")]
    pub max_distinct_id_length: usize,

    /// Maximum extra distinct ids per get-or-create entry. Real entries carry
    /// one or two (the anon id at $identify); persons stop accumulating
    /// distinct ids around 2,500 in the merge path, so 5,000 only stops
    /// runaway callers.
    #[envconfig(default = "5000")]
    pub max_extra_distinct_ids: usize,

    /// Router endpoint used to reach the owning leader for initial-properties
    /// writes on the creation branch (UpdatePersonProperties).
    #[envconfig(default = "http://127.0.0.1:50054")]
    pub router_url: String,

    /// HTTP/2 connections to open to the router, used round-robin per
    /// request. Each connection lands on one router pod for its lifetime,
    /// so a single connection pins every leader call of this pod to one
    /// router and serializes the lifecycle fan-out onto one socket
    /// (0 acts as 1).
    #[envconfig(default = "4")]
    pub router_channels: usize,

    #[envconfig(default = "0")]
    pub router_initial_stream_window_bytes: WindowSize,

    #[envconfig(default = "0")]
    pub router_initial_connection_window_bytes: WindowSize,

    /// Per-attempt timeout for leader-routed property writes and strong reads (ms).
    #[envconfig(default = "5000")]
    pub leader_request_timeout_ms: u64,

    /// Attempts per leader-routed write or strong read, each under `leader_request_timeout_ms`.
    #[envconfig(default = "2")]
    pub leader_request_attempts: u32,

    /// etcd endpoints, comma separated. The delete saga groups its fence
    /// calls by leader partition, and the partition count lives in etcd.
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    /// Interval between HTTP/2 keepalive pings sent by the gRPC server (0 = disabled)
    #[envconfig(default = "30")]
    pub grpc_keepalive_interval_secs: u64,

    /// Timeout for a keepalive ping ack before considering the connection dead
    #[envconfig(default = "10")]
    pub grpc_keepalive_timeout_secs: u64,

    #[envconfig(default = "0")]
    pub grpc_initial_stream_window_bytes: WindowSize,

    #[envconfig(default = "0")]
    pub grpc_initial_connection_window_bytes: WindowSize,

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
    /// so the caller retries on another pod. 0 = disabled.
    #[envconfig(default = "0")]
    pub max_concurrent_requests: usize,

    /// Leader property writes in flight per get-or-create batch (0 acts as 1).
    #[envconfig(default = "8")]
    pub property_write_concurrency: usize,

    /// Leader calls in flight per lifecycle saga step (0 acts as 1).
    #[envconfig(default = "8")]
    pub lifecycle_leader_call_concurrency: usize,

    /// How long one claim of a lifecycle op lasts before another instance
    /// may steal it (seconds).
    #[envconfig(default = "15")]
    pub lifecycle_lease_secs: u64,

    /// Seconds one lifecycle call drives (or waits on another driver's
    /// lease) before returning UNAVAILABLE; callers need a larger deadline.
    #[envconfig(default = "30")]
    pub lifecycle_execute_timeout_secs: u64,

    /// How often a non-owning driver re-checks a leased op for completion (ms).
    #[envconfig(default = "250")]
    pub lifecycle_poll_interval_ms: u64,

    /// Warn when an op's attempt counter reaches this value.
    #[envconfig(default = "5")]
    pub lifecycle_attempt_alert_threshold: i32,

    /// Merge saga drives allowed to outlive a caller that hangs up; past this
    /// many a drive runs inline and stops with its caller. 0 disables.
    #[envconfig(default = "256")]
    pub lifecycle_detached_drive_limit: usize,

    /// Run the sweeper + GC loop for abandoned lifecycle ops; the lease
    /// arbitrates, so any number of instances may run it.
    #[envconfig(default = "true")]
    pub lifecycle_sweeper_enabled: bool,

    /// Interval between sweeper passes (seconds).
    #[envconfig(default = "30")]
    pub lifecycle_sweep_interval_secs: u64,

    /// Hours completed op rows are kept for op_id idempotency before GC.
    #[envconfig(default = "24")]
    pub lifecycle_op_retention_hours: u64,

    /// Rows one GC pass may delete, so a post-backlog sweep never holds
    /// locks for long; the next pass continues.
    #[envconfig(default = "10000")]
    pub lifecycle_gc_batch_limit: i64,

    /// Off until the ingestion consumer stops emitting the same merge
    /// verdicts itself, or customers see each refusal twice.
    #[envconfig(default = "false")]
    pub ingestion_warnings_enabled: bool,

    #[envconfig(default = "")]
    pub ingestion_warnings_kafka_hosts: String,

    #[envconfig(default = "false")]
    pub ingestion_warnings_kafka_tls: bool,

    #[envconfig(default = "clickhouse_ingestion_warnings")]
    pub ingestion_warnings_topic: String,

    #[envconfig(default = "16")]
    pub ingestion_warnings_kafka_queue_mib: u32,

    #[envconfig(default = "1048576")]
    pub ingestion_warnings_kafka_message_max_bytes: u32,

    /// The defaults below are fire-and-forget: a warning is worth less than
    /// the cost of retrying it, and a slow warnings topic must not hold a merge.
    #[envconfig(default = "1")]
    pub ingestion_warnings_kafka_acks: String,

    #[envconfig(default = "0")]
    pub ingestion_warnings_kafka_retries: u32,

    #[envconfig(default = "100")]
    pub ingestion_warnings_kafka_linger_ms: u32,

    #[envconfig(default = "10000")]
    pub ingestion_warnings_kafka_queue_messages: u32,

    #[envconfig(default = "5000")]
    pub ingestion_warnings_kafka_message_timeout_ms: u32,

    /// Warnings of one type a minute that one pod sends, shared by every team
    /// on it; the rest are dropped as `type_budget_exhausted`.
    #[envconfig(default = "60")]
    pub ingestion_warnings_type_budget_per_minute: NonZeroU32,

    /// Throttle keys (team, distinct id, type) a pod remembers for the hour a
    /// key lives, at roughly 135 bytes each.
    #[envconfig(default = "1000000")]
    pub ingestion_warnings_max_tracked_scopes: usize,

    /// Write the publish outbox, one row per create or attach mapping and
    /// one pointer per completed merge or delete op, for the separate
    /// personhog-publisher deployment to drain. Off, identity writes nothing
    /// there and never names the outbox table in a mapping or completion
    /// statement. An outbox nobody drains holds every pointed op past GC
    /// retention, so turn this on only where a publisher runs against the
    /// same table set.
    #[envconfig(default = "false")]
    pub lifecycle_outbox_enabled: bool,
}

/// The six table variables identity and the publisher both read. One
/// struct, nested in both configs, so the names and defaults cannot drift
/// between the deployment that writes the outbox and the one that drains it.
#[derive(Envconfig, Clone, Debug)]
pub struct IdentityTablesConfig {
    /// Person table every identity query reads and writes (stub creation,
    /// resolution, and the delete saga's person mutations). Must pair with
    /// the leader's FALLBACK_TABLE and the writer's PG_TARGET_TABLE so the
    /// three services agree on where person rows live. Defaults to the
    /// validation table, matching the writer; set to "posthog_person" at
    /// production cutover — and flip all three services together.
    #[envconfig(default = "personhog_person_tmp")]
    pub person_table: String,

    /// Distinct id table paired with PERSON_TABLE. Person ids come from the
    /// person table's own sequence, so the mapping must live in the same
    /// namespace (and posthog_persondistinctid's FK rejects ids that are not
    /// in posthog_person). Set to "posthog_persondistinctid" at cutover.
    #[envconfig(default = "personhog_persondistinctid_tmp")]
    pub person_distinct_id_table: String,

    /// Feature-flag hash-key-override table the delete saga clears by
    /// person_id — same namespace rule as the distinct id table. Set to
    /// "posthog_featureflaghashkeyoverride" at cutover.
    #[envconfig(default = "personhog_featureflaghashkeyoverride_tmp")]
    pub ff_hash_key_override_table: String,

    /// Saga state table. Same namespace rule as PERSON_TABLE; the leader
    /// derives the same pair from FALLBACK_TABLE. Set to "lifecycle_op" at cutover.
    #[envconfig(default = "lifecycle_op_tmp")]
    pub lifecycle_op_table: String,

    /// Claim table paired with LIFECYCLE_OP_TABLE. Set to "lifecycle_op_person" at cutover.
    #[envconfig(default = "lifecycle_op_person_tmp")]
    pub lifecycle_op_person_table: String,

    /// Outbox the publisher drains, paired with LIFECYCLE_OP_TABLE: a merge
    /// or delete op's pointer row resolves against that op's rows. Set to
    /// "person_publish_outbox" at cutover.
    #[envconfig(default = "person_publish_outbox_tmp")]
    pub person_publish_outbox_table: String,
}

impl IdentityTablesConfig {
    pub fn tables(&self) -> IdentityTables {
        IdentityTables {
            person: self.person_table.clone(),
            person_distinct_id: self.person_distinct_id_table.clone(),
            ff_hash_key_override: self.ff_hash_key_override_table.clone(),
            lifecycle_op: self.lifecycle_op_table.clone(),
            lifecycle_op_person: self.lifecycle_op_person_table.clone(),
            person_publish_outbox: self.person_publish_outbox_table.clone(),
        }
    }
}

/// Whether identity writes the publish outbox (`LIFECYCLE_OUTBOX_ENABLED`):
/// one row per create or attach mapping and one pointer per completed merge
/// or delete op. Carried by every writer so the choice is made where the
/// writer is built, never defaulted at the write site.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutboxWrites {
    Enabled,
    Disabled,
}

/// The paired table set identity operates on: the person table plus the
/// tables it writes rows into (or clears rows from) keyed by that table's
/// person ids, plus the saga tables whose marks claim those ids and the
/// outbox whose pointers name those ops. All six must come from the same
/// namespace — mixing the validation set with the real set
/// cross-contaminates id spaces.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IdentityTables {
    pub person: String,
    pub person_distinct_id: String,
    pub ff_hash_key_override: String,
    pub lifecycle_op: String,
    pub lifecycle_op_person: String,
    pub person_publish_outbox: String,
}

impl IdentityTables {
    pub fn real() -> Self {
        Self {
            person: "posthog_person".to_string(),
            person_distinct_id: "posthog_persondistinctid".to_string(),
            ff_hash_key_override: "posthog_featureflaghashkeyoverride".to_string(),
            lifecycle_op: "lifecycle_op".to_string(),
            lifecycle_op_person: "lifecycle_op_person".to_string(),
            person_publish_outbox: "person_publish_outbox".to_string(),
        }
    }

    pub fn validation() -> Self {
        Self {
            person: "personhog_person_tmp".to_string(),
            person_distinct_id: "personhog_persondistinctid_tmp".to_string(),
            ff_hash_key_override: "personhog_featureflaghashkeyoverride_tmp".to_string(),
            lifecycle_op: "lifecycle_op_tmp".to_string(),
            lifecycle_op_person: "lifecycle_op_person_tmp".to_string(),
            person_publish_outbox: "person_publish_outbox_tmp".to_string(),
        }
    }

    /// Whether this is the validation set, for `mirrored_query!` and kin.
    pub fn is_validation(&self) -> bool {
        *self == Self::validation()
    }

    /// Only the two complete namespaces are accepted: a partial override
    /// (one table flipped, the others left on defaults) would pair person
    /// ids from one sequence with rows keyed by another, which is exactly
    /// the cross-contamination this config exists to prevent.
    pub fn validate(&self) -> Result<(), String> {
        if *self == Self::real() || *self == Self::validation() {
            return Ok(());
        }
        Err(format!(
            "mixed identity table set {self:?}: set PERSON_TABLE, PERSON_DISTINCT_ID_TABLE, \
             FF_HASH_KEY_OVERRIDE_TABLE, LIFECYCLE_OP_TABLE, LIFECYCLE_OP_PERSON_TABLE, and \
             PERSON_PUBLISH_OUTBOX_TABLE together, to either the full real set or the full \
             validation set"
        ))
    }
}

impl Config {
    pub fn tables(&self) -> IdentityTables {
        self.tables.tables()
    }

    pub fn outbox_writes(&self) -> OutboxWrites {
        if self.lifecycle_outbox_enabled {
            OutboxWrites::Enabled
        } else {
            OutboxWrites::Disabled
        }
    }

    pub fn request_limits(&self) -> crate::service::validation::RequestLimits {
        crate::service::validation::RequestLimits {
            max_batch_size: self.max_batch_size,
            max_distinct_id_length: self.max_distinct_id_length,
            max_extra_distinct_ids: self.max_extra_distinct_ids,
        }
    }

    pub fn idle_timeout(&self) -> Option<Duration> {
        if self.idle_timeout_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.idle_timeout_secs))
        }
    }

    pub fn fast_pool_config(&self) -> PoolConfig {
        self.pool_config(
            Lane::Fast,
            self.min_pg_connections,
            self.max_pg_connections,
            self.acquire_timeout_secs,
            self.statement_timeout_ms,
        )
    }

    pub fn heavy_pool_config(&self) -> PoolConfig {
        self.pool_config(
            Lane::Heavy,
            self.heavy_min_pg_connections,
            self.heavy_max_pg_connections,
            self.heavy_acquire_timeout_secs,
            self.heavy_statement_timeout_ms,
        )
    }

    fn pool_config(
        &self,
        lane: Lane,
        min_connections: u32,
        max_connections: u32,
        acquire_timeout_secs: u64,
        statement_timeout_ms: u64,
    ) -> PoolConfig {
        PoolConfig {
            min_connections,
            max_connections,
            acquire_timeout: Duration::from_secs(acquire_timeout_secs),
            idle_timeout: self.idle_timeout(),
            test_before_acquire: false,
            statement_timeout_ms: (statement_timeout_ms != 0).then_some(statement_timeout_ms),
            pool_name: Some(lane.label().to_string()),
        }
    }

    pub fn leader_request_timeout(&self) -> Duration {
        Duration::from_millis(self.leader_request_timeout_ms)
    }

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
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

    pub fn router_http2_windows(&self) -> Http2Windows {
        Http2Windows::new(
            self.router_initial_stream_window_bytes,
            self.router_initial_connection_window_bytes,
        )
    }

    pub fn grpc_http2_windows(&self) -> Http2Windows {
        Http2Windows::new(
            self.grpc_initial_stream_window_bytes,
            self.grpc_initial_connection_window_bytes,
        )
    }

    pub fn grpc_max_connection_age(&self) -> Option<Duration> {
        if self.grpc_max_connection_age_secs == 0 {
            None
        } else {
            Some(Duration::from_secs(self.grpc_max_connection_age_secs))
        }
    }

    pub fn lifecycle_engine_config(&self) -> crate::lifecycle::engine::EngineConfig {
        crate::lifecycle::engine::EngineConfig {
            lease: Duration::from_secs(self.lifecycle_lease_secs),
            execute_timeout: Duration::from_secs(self.lifecycle_execute_timeout_secs),
            poll_interval: Duration::from_millis(self.lifecycle_poll_interval_ms),
            attempt_alert_threshold: self.lifecycle_attempt_alert_threshold,
            gc_batch_limit: self.lifecycle_gc_batch_limit,
        }
    }

    pub fn lifecycle_sweep_interval(&self) -> Duration {
        Duration::from_secs(self.lifecycle_sweep_interval_secs)
    }

    pub fn lifecycle_op_retention(&self) -> Duration {
        Duration::from_secs(self.lifecycle_op_retention_hours * 3600)
    }

    pub fn ingestion_warnings_settings(&self) -> common_ingestion_warnings::RowWarningsSettings {
        common_ingestion_warnings::RowWarningsSettings {
            enabled: self.ingestion_warnings_enabled,
            kafka_hosts: self.ingestion_warnings_kafka_hosts.clone(),
            kafka_tls: self.ingestion_warnings_kafka_tls,
            topic: self.ingestion_warnings_topic.clone(),
            kafka_queue_mib: self.ingestion_warnings_kafka_queue_mib,
            kafka_message_max_bytes: self.ingestion_warnings_kafka_message_max_bytes,
            kafka_acks: self.ingestion_warnings_kafka_acks.clone(),
            kafka_retries: self.ingestion_warnings_kafka_retries,
            kafka_linger_ms: self.ingestion_warnings_kafka_linger_ms,
            kafka_queue_messages: self.ingestion_warnings_kafka_queue_messages,
            kafka_message_timeout_ms: self.ingestion_warnings_kafka_message_timeout_ms,
            type_budget_per_minute: self.ingestion_warnings_type_budget_per_minute,
            max_tracked_scopes: self.ingestion_warnings_max_tracked_scopes,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::IdentityTables;

    #[test]
    fn complete_table_sets_pass_validation() {
        assert!(IdentityTables::real().validate().is_ok());
        assert!(IdentityTables::validation().validate().is_ok());
    }

    // A mixed table set pairs person ids from one sequence with rows keyed by
    // another; validation must refuse it rather than let a partial env
    // override through.
    #[test]
    fn a_mixed_table_set_is_refused() {
        let mixed = IdentityTables {
            person: "posthog_person".to_string(),
            ..IdentityTables::validation()
        };
        assert!(mixed.validate().is_err());
    }
}
