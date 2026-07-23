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

    #[envconfig(default = "14400")]
    pub seeder_ch_max_execution_time_secs: u64,

    #[envconfig(default = "20000000000")]
    pub seeder_ch_max_bytes_before_external_group_by: u64,

    #[envconfig(default = "20000000000")]
    pub seeder_ch_max_bytes_before_external_sort: u64,

    #[envconfig(default = "grace_hash")]
    pub seeder_ch_join_algorithm: String,

    #[envconfig(default = "100")]
    pub seeder_queue_full_backoff_ms: u64,
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
