//! Service configuration, loaded from environment variables via `envconfig`.

use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use common_types::cohort::TeamAllowlist;
use envconfig::Envconfig;

use crate::consumer::ShufflerSettings;

const POOL_NAME: &str = "posthog_cohort";

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    #[envconfig(default = "3322")]
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

    #[envconfig(default = "clickhouse_events_json")]
    pub input_topic: String,

    #[envconfig(default = "cohort-event-shuffler")]
    pub kafka_consumer_group: String,

    /// Start at the tail: historical population is the seed topic's job, not a days-long replay.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    #[envconfig(default = "cohort_stream_events")]
    pub output_topic: String,

    /// Must be `murmur2_random` to co-partition `(team_id, person_id)` identically to the
    /// Node-produced `person_merge_events`; other values silently break cross-runtime affinity.
    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: String,

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub pg_acquire_timeout_secs: u64,

    /// `0` → database default.
    #[envconfig(default = "5000")]
    pub pg_statement_timeout_ms: u64,

    #[envconfig(default = "300")]
    pub team_index_refresh_secs: u64,

    #[envconfig(default = "60")]
    pub team_index_refresh_jitter_secs: u64,

    /// Teams whose events are forwarded into the shadow pipeline. Defaults to team 2 (the parity
    /// baseline's gate); set `all` to disable the gate. See [`TeamAllowlist`].
    #[envconfig(from = "REALTIME_COHORT_TEAM_ALLOWLIST", default = "2")]
    pub team_allowlist: TeamAllowlist,

    /// Cap on unresolved forwards; intake pauses at the cap while acks and commits keep
    /// draining. Steady state is ~two orders of magnitude below this.
    #[envconfig(default = "10000")]
    pub max_inflight_forwards: usize,

    /// Also bounds the crash-replay window: interval × consume rate events per pod, deduped
    /// downstream via `source_partition`/`source_offset`.
    #[envconfig(default = "5000")]
    pub commit_interval_ms: u64,

    /// Base of the capped-exponential backoff when the producer queue is full.
    #[envconfig(default = "100")]
    pub queue_full_backoff_ms: u64,

    /// WarpStream-recommended linger.
    #[envconfig(default = "100")]
    pub kafka_producer_linger_ms: u32,

    /// OOM guard: librdkafka's buffer must stay far below the 1Gi pod limit.
    #[envconfig(default = "64")]
    pub kafka_producer_queue_mib: u32,

    #[envconfig(default = "100000")]
    pub kafka_producer_queue_messages: u32,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn shuffler_settings(&self) -> ShufflerSettings {
        ShufflerSettings {
            max_inflight_forwards: self.max_inflight_forwards,
            commit_interval: Duration::from_millis(self.commit_interval_ms),
            queue_full_backoff: Duration::from_millis(self.queue_full_backoff_ms),
        }
    }

    pub fn team_index_refresh_interval(&self) -> Duration {
        Duration::from_secs(self.team_index_refresh_secs)
    }

    pub fn team_index_refresh_jitter(&self) -> Duration {
        Duration::from_secs(self.team_index_refresh_jitter_secs)
    }

    fn pg_statement_timeout(&self) -> Option<u64> {
        (self.pg_statement_timeout_ms != 0).then_some(self.pg_statement_timeout_ms)
    }

    pub fn pool_config(&self) -> PoolConfig {
        PoolConfig {
            min_connections: self.min_pg_connections,
            max_connections: self.max_pg_connections,
            acquire_timeout: Duration::from_secs(self.pg_acquire_timeout_secs),
            idle_timeout: Some(Duration::from_secs(300)),
            test_before_acquire: true,
            statement_timeout_ms: self.pg_statement_timeout(),
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
            kafka_producer_partitioner: Some(self.kafka_producer_partitioner.clone()),
            kafka_producer_linger_ms: self.kafka_producer_linger_ms,
            kafka_producer_queue_mib: self.kafka_producer_queue_mib,
            kafka_producer_queue_messages: self.kafka_producer_queue_messages,
            kafka_message_timeout_ms: 20_000,
            kafka_producer_batch_size: None,
            kafka_producer_batch_num_messages: None,
            // Idempotence stays off (librdkafka retries can reorder — accepted for the PoC).
            // A strict-ordering flip requires enable.idempotence=true, which in turn caps
            // max.in.flight.requests.per.connection at 5.
            kafka_producer_enable_idempotence: None,
            kafka_producer_max_in_flight_requests_per_connection: None,
            kafka_producer_topic_metadata_refresh_interval_ms: None,
            kafka_producer_message_max_bytes: None,
            kafka_producer_sticky_partitioning_linger_ms: None,
        }
    }

    /// Auto-commit is disabled: the pipeline commits explicit per-partition next-offsets computed
    /// by its [`crate::ledger::Ledger`] (at-least-once; only ack-covered offsets are committed).
    /// Load-bearing: `recv_with` still auto-STORES offsets for empty payloads, so enabling
    /// auto-commit would commit those stores past unacked forwards and silently break
    /// at-least-once. A unit test pins the flag.
    pub fn build_consumer_config(&self) -> ConsumerConfig {
        ConsumerConfig {
            kafka_consumer_group: self.kafka_consumer_group.clone(),
            kafka_consumer_topic: self.input_topic.clone(),
            kafka_consumer_offset_reset: self.kafka_consumer_offset_reset.clone(),
            kafka_consumer_auto_commit: false,
            kafka_consumer_auto_commit_interval_ms: 5000,
            kafka_consumer_fetch_wait_max_ms: None,
            kafka_consumer_fetch_min_bytes: None,
            kafka_consumer_fetch_max_bytes: None,
            kafka_consumer_max_partition_fetch_bytes: None,
            kafka_consumer_group_instance_id: None,
            kafka_consumer_partition_strategy: None,
            kafka_consumer_socket_send_buffer_bytes: None,
            kafka_consumer_socket_receive_buffer_bytes: None,
            kafka_consumer_metadata_refresh_interval_ms: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> Config {
        Config {
            bind_host: "0.0.0.0".to_string(),
            bind_port: 3322,
            export_prometheus: true,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_rack: String::new(),
            kafka_client_id: String::new(),
            input_topic: "clickhouse_events_json".to_string(),
            kafka_consumer_group: "cohort-event-shuffler".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
            output_topic: "cohort_stream_events".to_string(),
            kafka_producer_partitioner: "murmur2_random".to_string(),
            kafka_compression_codec: "none".to_string(),
            database_url: "postgres://posthog:posthog@localhost:5432/posthog".to_string(),
            min_pg_connections: 1,
            max_pg_connections: 5,
            pg_acquire_timeout_secs: 10,
            pg_statement_timeout_ms: 5000,
            team_index_refresh_secs: 300,
            team_index_refresh_jitter_secs: 60,
            team_allowlist: TeamAllowlist::All,
            max_inflight_forwards: 10_000,
            commit_interval_ms: 5000,
            queue_full_backoff_ms: 100,
            kafka_producer_linger_ms: 100,
            kafka_producer_queue_mib: 64,
            kafka_producer_queue_messages: 100_000,
        }
    }

    #[test]
    fn kafka_config_pins_the_partitioner() {
        let config = test_config();
        assert_eq!(
            config
                .build_kafka_config()
                .kafka_producer_partitioner
                .as_deref(),
            Some("murmur2_random"),
        );
    }

    #[test]
    fn consumer_disables_auto_commit_for_manual_offset_control() {
        let config = test_config();
        let consumer = config.build_consumer_config();
        assert!(!consumer.kafka_consumer_auto_commit);
        assert_eq!(consumer.kafka_consumer_topic, "clickhouse_events_json");
    }

    #[test]
    fn statement_timeout_zero_means_database_default() {
        let mut config = test_config();
        config.pg_statement_timeout_ms = 0;
        assert!(config.pool_config().statement_timeout_ms.is_none());
    }
}
