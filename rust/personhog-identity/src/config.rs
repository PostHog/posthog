use envconfig::Envconfig;
use std::net::SocketAddr;
use std::time::Duration;

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50055")]
    pub grpc_address: SocketAddr,

    /// Primary database URL. All identity work (resolution and stub creation)
    /// runs on the primary — the identity plane is synchronous with Postgres.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub primary_database_url: String,

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

    /// Per-call timeout for leader-routed property writes (ms).
    #[envconfig(default = "5000")]
    pub leader_request_timeout_ms: u64,

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
    /// so the caller retries on another pod. 0 = disabled.
    #[envconfig(default = "0")]
    pub max_concurrent_requests: usize,

    /// How long one claim of a lifecycle op lasts before another instance
    /// may steal it (seconds).
    #[envconfig(default = "15")]
    pub lifecycle_lease_secs: u64,

    /// How long one lifecycle call — MergePersons or DeletePersons — keeps
    /// driving (or waiting on another driver's lease) before returning
    /// UNAVAILABLE (seconds); checked between steps. A caller's own deadline
    /// must exceed this value, or it cancels drives mid-lease and every
    /// follow-up waits the abandoned lease out.
    #[envconfig(default = "30")]
    pub lifecycle_execute_timeout_secs: u64,

    /// How often a non-owning driver re-checks a leased op for completion (ms).
    #[envconfig(default = "250")]
    pub lifecycle_poll_interval_ms: u64,

    /// Warn when an op's attempt counter reaches this value.
    #[envconfig(default = "5")]
    pub lifecycle_attempt_alert_threshold: i32,

    /// Run the background sweeper + GC loop for abandoned lifecycle ops;
    /// the lease arbitrates, so any number of instances may run it. The
    /// protocol depends on it: a claim-race drop can orphan a live saga
    /// whose op id no client presents again, and without the sweeper its
    /// fences freeze until an operator intervenes.
    #[envconfig(default = "true")]
    pub lifecycle_sweeper_enabled: bool,

    /// Interval between sweeper passes (seconds).
    #[envconfig(default = "30")]
    pub lifecycle_sweep_interval_secs: u64,

    /// How long completed op rows are retained for op_id idempotency before
    /// GC (hours); the durable deletion shield is the person tombstone row,
    /// not the op row. A completed op's verdict replays for this long, so a
    /// client that caches which persons a merge destroyed must hold those
    /// marks longer than this window or a replay can resurrect one.
    #[envconfig(default = "24")]
    pub lifecycle_op_retention_hours: u64,
}

/// The paired table set identity operates on: the person table plus the
/// tables it writes rows into (or clears rows from) keyed by that table's
/// person ids. The three must come from the same namespace — mixing the
/// validation set with the real set cross-contaminates id spaces.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IdentityTables {
    pub person: String,
    pub person_distinct_id: String,
    pub ff_hash_key_override: String,
}

impl IdentityTables {
    pub fn real() -> Self {
        Self {
            person: "posthog_person".to_string(),
            person_distinct_id: "posthog_persondistinctid".to_string(),
            ff_hash_key_override: "posthog_featureflaghashkeyoverride".to_string(),
        }
    }

    pub fn validation() -> Self {
        Self {
            person: "personhog_person_tmp".to_string(),
            person_distinct_id: "personhog_persondistinctid_tmp".to_string(),
            ff_hash_key_override: "personhog_featureflaghashkeyoverride_tmp".to_string(),
        }
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
             and FF_HASH_KEY_OVERRIDE_TABLE together, to either the full real set or the \
             full validation set"
        ))
    }
}

impl Config {
    pub fn tables(&self) -> IdentityTables {
        IdentityTables {
            person: self.person_table.clone(),
            person_distinct_id: self.person_distinct_id_table.clone(),
            ff_hash_key_override: self.ff_hash_key_override_table.clone(),
        }
    }

    pub fn request_limits(&self) -> crate::service::validation::RequestLimits {
        crate::service::validation::RequestLimits {
            max_batch_size: self.max_batch_size,
            max_distinct_id_length: self.max_distinct_id_length,
            max_extra_distinct_ids: self.max_extra_distinct_ids,
        }
    }

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

    pub fn leader_request_timeout(&self) -> Duration {
        Duration::from_millis(self.leader_request_timeout_ms)
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

    pub fn lifecycle_engine_config(&self) -> crate::lifecycle::engine::EngineConfig {
        crate::lifecycle::engine::EngineConfig {
            lease: Duration::from_secs(self.lifecycle_lease_secs),
            execute_timeout: Duration::from_secs(self.lifecycle_execute_timeout_secs),
            poll_interval: Duration::from_millis(self.lifecycle_poll_interval_ms),
            attempt_alert_threshold: self.lifecycle_attempt_alert_threshold,
        }
    }

    pub fn lifecycle_sweep_interval(&self) -> Duration {
        Duration::from_secs(self.lifecycle_sweep_interval_secs)
    }

    pub fn lifecycle_op_retention(&self) -> Duration {
        Duration::from_secs(self.lifecycle_op_retention_hours * 3600)
    }
}

// A mixed table set pairs person ids from one sequence with rows keyed by
// another; validation must refuse it rather than let a partial env override
// through.
#[cfg(test)]
mod tests {
    use super::IdentityTables;

    #[test]
    fn complete_table_sets_pass_validation() {
        assert!(IdentityTables::real().validate().is_ok());
        assert!(IdentityTables::validation().validate().is_ok());
    }

    #[test]
    fn a_mixed_table_set_is_refused() {
        let mixed = IdentityTables {
            person: "posthog_person".to_string(),
            ..IdentityTables::validation()
        };
        assert!(mixed.validate().is_err());
    }
}
