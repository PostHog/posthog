//! Service configuration and infrastructure client builders — the `envconfig` mirror plus the pool
//! and Kafka builders. A leaf: it names no other seeder module, so dependency arrows point at it,
//! never away.

use std::fmt;
use std::num::NonZeroU32;
use std::str::FromStr;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use common_types::cohort::TeamAllowlist;
use envconfig::Envconfig;

const POOL_NAME: &str = "posthog_cohort_seeder";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KafkaProducerPartitioner {
    Murmur2Random,
}

impl KafkaProducerPartitioner {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Murmur2Random => "murmur2_random",
        }
    }
}

impl fmt::Display for KafkaProducerPartitioner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for KafkaProducerPartitioner {
    type Err = InvalidKafkaProducerPartitioner;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "murmur2_random" => Ok(Self::Murmur2Random),
            other => Err(InvalidKafkaProducerPartitioner(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("Kafka producer partitioner must be murmur2_random, got {0:?}")]
pub struct InvalidKafkaProducerPartitioner(String);

#[derive(Clone, Debug, Envconfig)]
pub struct Config {
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    #[envconfig(default = "3324")]
    pub bind_port: u16,

    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    #[envconfig(
        from = "COHORT_STREAM_SEED_EVENTS_TOPIC",
        default = "cohort_stream_seed_events"
    )]
    pub seed_events_topic: String,

    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: KafkaProducerPartitioner,

    /// The partition count every co-partitioned cohort topic must have — the consumer owns a
    /// person by `partition_for(key, COHORT_PARTITION_COUNT)`, so a seed topic provisioned with a
    /// different count would route a person's seed tiles to a worker that does not own them.
    /// Mirrors the processor's `COHORT_PARTITION_COUNT`; startup verifies the seed topic against it.
    #[envconfig(from = "COHORT_PARTITION_COUNT", default = "64")]
    pub cohort_partition_count: u32,

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String,

    #[envconfig(default = "100")]
    pub kafka_producer_linger_ms: u32,

    #[envconfig(default = "64")]
    pub kafka_producer_queue_mib: u32,

    #[envconfig(default = "100000")]
    pub kafka_producer_queue_messages: u32,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub pg_acquire_timeout_secs: u64,

    #[envconfig(default = "5000")]
    pub pg_statement_timeout_ms: u64,

    #[envconfig(default = "")]
    pub clickhouse_url: String,

    #[envconfig(default = "")]
    pub clickhouse_offline_cluster_host: String,

    #[envconfig(default = "localhost:8123")]
    pub clickhouse_host: String,

    #[envconfig(default = "default")]
    pub clickhouse_user: String,

    #[envconfig(default = "")]
    pub clickhouse_password: String,

    #[envconfig(default = "default")]
    pub clickhouse_database: String,

    #[envconfig(default = "false")]
    pub clickhouse_secure: bool,

    /// Validate the server certificate against the public root CAs. Defaults on so an unconfigured
    /// deployment fails closed; the chart sets it to `false` for internal ClickHouse.
    #[envconfig(default = "true")]
    pub clickhouse_verify: bool,

    /// PEM CA bundle to validate the ClickHouse server certificate against, as Django's
    /// `CLICKHOUSE_CA`. Naming a CA is an explicit request to authenticate the server, so it wins
    /// over `clickhouse_verify` rather than being downgraded by an inherited `CLICKHOUSE_VERIFY=false`.
    #[envconfig(default = "")]
    pub clickhouse_ca: String,

    #[envconfig(from = "REALTIME_COHORT_TEAM_ALLOWLIST", default = "2")]
    pub team_allowlist: TeamAllowlist,

    #[envconfig(default = "15")]
    pub seeder_run_poll_secs: u64,

    #[envconfig(default = "1")]
    pub seeder_max_concurrent_chunks: usize,

    #[envconfig(default = "900")]
    pub seeder_chunk_lease_secs: u64,

    #[envconfig(default = "5")]
    pub seeder_max_chunk_attempts: u32,

    #[envconfig(default = "3000")]
    pub seeder_tiles_per_sec: u32,

    #[envconfig(default = "4000")]
    pub seeder_max_inflight_tiles: usize,

    #[envconfig(default = "400")]
    pub seeder_max_lookback_days: u32,

    /// Person-hash bands each planned day is split into, bounding one chunk's in-memory aggregate
    /// to roughly `uniq(person, condition) / bands`. Safe to raise mid-run: planning is idempotent
    /// per (run, day, band) and tile application is max-merge idempotent, so a re-planned day only
    /// adds narrower re-scans.
    #[envconfig(default = "1")]
    pub seeder_bands_per_day: u16,

    /// Enable the person-property seed path: discovery widens to `person_property` runs and the
    /// planning/scan/emission pipeline arms. Default off — the processor's decode arm and
    /// `COHORT_SEED_PERSON_APPLY_ENABLED` must be deployed everywhere first, or an old processor
    /// skip-and-commits the seeds.
    #[envconfig(default = "false")]
    pub seeder_person_seeds_enabled: bool,

    /// Enable the person-property *reconcile* path: completion discovery widens to `person_property`
    /// runs, so a fully-seeded one transitions `seeding -> reconciling` and produces
    /// `reconcile_person` tiles. The orchestrator also needs `SEEDER_PERSON_SEEDS_ENABLED` before
    /// this does anything, since there is no person seed path to reconcile without it; the CLI
    /// reads this flag on its own and will dispatch a person run's tiles with seeds off.
    ///
    /// Deploy order, in this order, no overlap:
    ///   1. Roll the processor fleet-wide with a build that decodes `reconcile_person` tiles and
    ///      loads the person shape-hash map. An older processor routes the person kind to
    ///      `UnknownKind` and skip-commits it without a marker, stranding the run as a shortfall.
    ///   2. Flip `SEEDER_PERSON_SEEDS_ENABLED` and let person runs seed.
    ///   3. Flip this once step 1 is confirmed everywhere.
    ///   4. Set `REALTIME_COHORT_MEMBERSHIP_STAMP_POLICY=events_or_calculation_stamp` on every
    ///      region's flags service, then flip Django's
    ///      `BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED`. Until that gate opens the finalizer
    ///      skips person runs, so they stay `reconciling` after step 3 and
    ///      `seeder_runs_reconciling{kind="person_property"}` climbs. That is expected, not a
    ///      stalled dispatch.
    ///
    /// Flipping this back off does not undo a bad rollout: a run already in `reconciling` stops
    /// being discovered, so it never reaches `reconcile_observed_at` and never finalizes. Recovery
    /// is an operator re-dispatch through the CLI after the fleet is upgraded.
    #[envconfig(default = "false")]
    pub seeder_person_reconcile_dispatch_enabled: bool,

    /// Person-seed produce rate, shared across concurrent person chunks and separate from
    /// `seeder_tiles_per_sec` so the two throughputs tune independently.
    #[envconfig(default = "2000")]
    pub seeder_person_seeds_per_sec: u32,

    /// Target persons per planned UUID-range chunk; the planning scan keeps every Nth id as a
    /// range boundary. Sized so one chunk's paced emission completes in single-digit minutes —
    /// settings validation refuses a value the ClickHouse execution-time budget cannot cover.
    #[envconfig(default = "1000000")]
    pub seeder_persons_per_chunk: u64,

    /// The person path's own chunk-slot budget, so a person scan never occupies a behavioral slot.
    #[envconfig(default = "1")]
    pub seeder_person_max_concurrent_chunks: usize,

    /// Emit empty-`matched` seeds for scanned non-matchers. They heal stale-TRUE state and cost
    /// only a point-read on absent records (the consumer's no-create rule).
    #[envconfig(default = "true")]
    pub seeder_person_emit_nonmatchers: bool,

    #[envconfig(default = "14400")]
    pub seeder_ch_max_execution_time_secs: u64,

    #[envconfig(default = "20000000000")]
    pub seeder_ch_max_bytes_before_external_group_by: u64,

    #[envconfig(default = "20000000000")]
    pub seeder_ch_max_bytes_before_external_sort: u64,

    /// Runaway guard on sets built from `IN (SELECT …)` subqueries, which nothing else bounds — the
    /// person boundary scan's horizon prefilter builds one id set covering a whole team, unchunked.
    /// Exceeding it throws a set-size error naming the limit rather than pushing the server toward
    /// an OOM that takes unrelated queries down with it.
    #[envconfig(default = "20000000000")]
    pub seeder_ch_max_bytes_in_set: u64,

    #[envconfig(default = "grace_hash")]
    pub seeder_ch_join_algorithm: String,

    #[envconfig(default = "100")]
    pub seeder_queue_full_backoff_ms: u64,

    /// Enable the dark-by-default automatic reconcile dispatch driver. Enabling it without
    /// [`Config::seeder_confirm_register_backfilled`] is a startup error.
    #[envconfig(default = "false")]
    pub seeder_reconcile_auto_dispatch_enabled: bool,

    /// Attest that every run's data tiles were seeded after membership-register writers deployed —
    /// the automatic equivalent of the CLI's `--confirm-register-backfilled`. Required to arm
    /// automatic dispatch.
    #[envconfig(default = "false")]
    pub seeder_confirm_register_backfilled: bool,

    /// How many reconcile dispatches this replica may run at once — the bound on how hard a backlog
    /// of completed runs can press the producer queue the chunk pipeline shares. Separate from
    /// [`Config::seeder_max_inflight_tiles`], which bounds a single dispatch.
    #[envconfig(default = "4")]
    pub seeder_reconcile_max_concurrent_dispatches: usize,

    /// The reconcile-marker topic whose high watermarks anchor the marker watcher's start positions,
    /// captured at dispatch time. The observer reads markers from the same topic. Its partition count
    /// must not change while runs are in flight: a run's watch covers the partitions that existed at
    /// its dispatch, so one added later is never read — holding the run open if it appeared before
    /// the observation ends were captured, and settling the run short if it appeared after them.
    #[envconfig(default = "cohort_reconcile_markers")]
    pub cohort_reconcile_markers_topic: String,

    /// Enable the dark-by-default reconcile observer: the marker-watch task and the driver's
    /// observation pass. A separate gate from auto-dispatch — observation can run against
    /// CLI-dispatched runs without auto-dispatch, and vice versa.
    #[envconfig(default = "false")]
    pub seeder_reconcile_observer_enabled: bool,

    /// The seed processor's consumer group id. The observer queries this group's committed offsets on
    /// the seed topic as the reconcile-liveness signal; it never commits to it.
    #[envconfig(default = "cohort-stream-seeds")]
    pub kafka_seed_consumer_group: String,

    /// Timeout for the seed-group OffsetFetch and marker-topic watermark metadata calls the
    /// observer makes.
    #[envconfig(default = "10000")]
    pub seeder_reconcile_offsets_timeout_ms: u64,

    /// Flush the marker watcher's accumulated bits and positions at least this often.
    #[envconfig(default = "5000")]
    pub seeder_reconcile_persist_interval_ms: u64,

    /// Flush the marker watcher after this many consumed messages even if the interval has not
    /// elapsed, bounding how many observations a crash can lose.
    #[envconfig(default = "5000")]
    pub seeder_reconcile_persist_max_batch: u64,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn pool_config(&self) -> PoolConfig {
        PoolConfig {
            min_connections: self.min_pg_connections,
            max_connections: self.max_pg_connections,
            acquire_timeout: Duration::from_secs(self.pg_acquire_timeout_secs),
            idle_timeout: Some(Duration::from_secs(300)),
            test_before_acquire: true,
            statement_timeout_ms: (self.pg_statement_timeout_ms != 0)
                .then_some(self.pg_statement_timeout_ms),
            pool_name: Some(POOL_NAME.to_string()),
        }
    }

    pub fn build_kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_rack: self.kafka_client_rack.clone(),
            kafka_client_id: self.kafka_client_id.clone(),
            kafka_compression_codec: self.kafka_compression_codec.clone(),
            kafka_producer_partitioner: Some(self.kafka_producer_partitioner.as_str().to_string()),
            kafka_producer_linger_ms: self.kafka_producer_linger_ms,
            kafka_producer_queue_mib: self.kafka_producer_queue_mib,
            kafka_producer_queue_messages: self.kafka_producer_queue_messages,
            kafka_message_timeout_ms: 20_000,
            kafka_producer_batch_size: None,
            kafka_producer_batch_num_messages: None,
            kafka_producer_enable_idempotence: None,
            kafka_producer_max_in_flight_requests_per_connection: None,
            kafka_producer_topic_metadata_refresh_interval_ms: None,
            kafka_producer_message_max_bytes: None,
            kafka_producer_sticky_partitioning_linger_ms: None,
            kafka_producer_acks: None,
            kafka_producer_retries: None,
        }
    }

    pub fn tiles_per_second(&self) -> Result<NonZeroU32, ConfigValidationError> {
        NonZeroU32::new(self.seeder_tiles_per_sec).ok_or(ConfigValidationError::ZeroTileRate)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigValidationError {
    #[error("seed tiles per second must be greater than zero")]
    ZeroTileRate,
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn default_config() -> Config {
        Config::init_from_hashmap(&HashMap::new()).unwrap()
    }

    #[test]
    fn producer_partitioner_is_pinned_to_the_cohort_affinity_contract() {
        let config = Config::init_from_hashmap(&HashMap::new()).unwrap();
        assert_eq!(
            config.kafka_producer_partitioner,
            KafkaProducerPartitioner::Murmur2Random
        );
        assert_eq!(
            config
                .build_kafka_config()
                .kafka_producer_partitioner
                .as_deref(),
            Some("murmur2_random"),
        );
    }

    #[test]
    fn producer_partitioner_rejects_unsafe_environment_overrides() {
        for value in ["consistent_random", "random", ""] {
            let env =
                HashMap::from([("KAFKA_PRODUCER_PARTITIONER".to_string(), value.to_string())]);
            assert!(
                Config::init_from_hashmap(&env).is_err(),
                "accepted unsafe partitioner {value:?}"
            );
        }
    }

    #[test]
    fn partition_count_defaults_to_the_shared_cohort_contract() {
        assert_eq!(
            default_config().cohort_partition_count,
            cohort_core::partitioner::COHORT_PARTITION_COUNT,
        );
        let env = HashMap::from([("COHORT_PARTITION_COUNT".to_string(), "8".to_string())]);
        assert_eq!(
            Config::init_from_hashmap(&env)
                .unwrap()
                .cohort_partition_count,
            8
        );
    }

    /// The fail-closed TLS posture lives entirely in these defaults, so pin them.
    #[test]
    fn clickhouse_tls_defaults_are_fail_closed() {
        let config = default_config();
        assert!(config.clickhouse_verify);
        assert!(config.clickhouse_ca.is_empty());
    }

    #[test]
    fn service_limits_reject_disabled_tile_rate() {
        let mut config = default_config();
        config.seeder_tiles_per_sec = 0;
        assert!(matches!(
            config.tiles_per_second(),
            Err(ConfigValidationError::ZeroTileRate)
        ));
    }
}
