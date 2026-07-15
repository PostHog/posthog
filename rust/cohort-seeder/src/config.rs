//! Service configuration and infrastructure client builders.

use std::fmt;
use std::num::NonZeroU32;
use std::str::FromStr;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use common_types::cohort::TeamAllowlist;
use envconfig::Envconfig;

use crate::orchestrator::{OrchestratorSettings, OrchestratorSettingsError};
use crate::producer::{ProducerSettings, ProducerSettingsError};

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
        }
    }

    pub fn clickhouse_endpoint(&self) -> String {
        if !self.clickhouse_url.is_empty() {
            return self.clickhouse_url.clone();
        }
        let host = if self.clickhouse_offline_cluster_host.is_empty() {
            &self.clickhouse_host
        } else {
            &self.clickhouse_offline_cluster_host
        };
        if host.starts_with("http://") || host.starts_with("https://") {
            return host.clone();
        }
        let scheme = if self.clickhouse_secure {
            "https"
        } else {
            "http"
        };
        if has_explicit_port(host) {
            format!("{scheme}://{host}")
        } else {
            let port = if self.clickhouse_secure { 8443 } else { 8123 };
            format!("{scheme}://{host}:{port}")
        }
    }

    pub fn build_clickhouse_client(&self) -> clickhouse::Client {
        clickhouse::Client::default()
            .with_url(self.clickhouse_endpoint())
            .with_user(&self.clickhouse_user)
            .with_password(&self.clickhouse_password)
            .with_database(&self.clickhouse_database)
            .with_option(
                "max_execution_time",
                self.seeder_ch_max_execution_time_secs.to_string(),
            )
            .with_option(
                "max_bytes_before_external_group_by",
                self.seeder_ch_max_bytes_before_external_group_by
                    .to_string(),
            )
            .with_option(
                "max_bytes_before_external_sort",
                self.seeder_ch_max_bytes_before_external_sort.to_string(),
            )
            .with_option("join_algorithm", self.seeder_ch_join_algorithm.clone())
    }

    pub fn tiles_per_second(&self) -> Result<NonZeroU32, ConfigValidationError> {
        NonZeroU32::new(self.seeder_tiles_per_sec).ok_or(ConfigValidationError::ZeroTileRate)
    }

    pub fn orchestrator_settings(&self) -> Result<OrchestratorSettings, ConfigValidationError> {
        let producer = ProducerSettings::new(
            self.seeder_max_inflight_tiles,
            Duration::from_millis(self.seeder_queue_full_backoff_ms),
        )?;
        Ok(OrchestratorSettings::new(
            Duration::from_secs(self.seeder_run_poll_secs),
            self.seeder_max_concurrent_chunks,
            Duration::from_secs(self.seeder_chunk_lease_secs),
            self.seeder_max_chunk_attempts,
            self.seeder_max_lookback_days,
            producer,
        )?)
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigValidationError {
    #[error("seed tiles per second must be greater than zero")]
    ZeroTileRate,
    #[error(transparent)]
    Producer(#[from] ProducerSettingsError),
    #[error(transparent)]
    Orchestrator(#[from] OrchestratorSettingsError),
}

fn has_explicit_port(host: &str) -> bool {
    if let Some(bracket_end) = host.find(']') {
        return host
            .get(bracket_end + 1..)
            .is_some_and(|suffix| suffix.starts_with(':'));
    }
    let Some((_, port)) = host.rsplit_once(':') else {
        return false;
    };
    host.matches(':').count() == 1 && port.parse::<u16>().is_ok()
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
    fn bare_clickhouse_hosts_get_the_canonical_port_for_the_scheme() {
        for (secure, expected) in [
            (false, "http://clickhouse.internal:8123"),
            (true, "https://clickhouse.internal:8443"),
        ] {
            let mut config = default_config();
            config.clickhouse_host = "clickhouse.internal".to_string();
            config.clickhouse_secure = secure;
            assert_eq!(config.clickhouse_endpoint(), expected);
        }

        let mut config = default_config();
        config.clickhouse_host = "fallback.internal".to_string();
        config.clickhouse_offline_cluster_host = "offline.internal".to_string();
        config.clickhouse_secure = true;
        assert_eq!(
            config.clickhouse_endpoint(),
            "https://offline.internal:8443"
        );
    }

    #[test]
    fn explicit_clickhouse_urls_and_ports_are_preserved() {
        let mut config = default_config();
        config.clickhouse_url = "https://proxy.example:9440/clickhouse".to_string();
        assert_eq!(
            config.clickhouse_endpoint(),
            "https://proxy.example:9440/clickhouse"
        );

        config.clickhouse_url.clear();
        config.clickhouse_host = "clickhouse.internal:9000".to_string();
        config.clickhouse_secure = true;
        assert_eq!(
            config.clickhouse_endpoint(),
            "https://clickhouse.internal:9000"
        );
    }

    #[test]
    fn service_limits_reject_disabled_pacing_and_concurrency() {
        let mut config = default_config();
        config.seeder_tiles_per_sec = 0;
        assert!(matches!(
            config.tiles_per_second(),
            Err(ConfigValidationError::ZeroTileRate)
        ));

        config.seeder_tiles_per_sec = 1;
        config.seeder_max_concurrent_chunks = 0;
        assert!(matches!(
            config.orchestrator_settings(),
            Err(ConfigValidationError::Orchestrator(
                OrchestratorSettingsError::ZeroConcurrency
            ))
        ));
    }
}
