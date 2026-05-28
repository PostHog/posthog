//! Service configuration, loaded from environment variables via `envconfig`.
//!
//! Flat struct plus `build_*` helpers, mirroring `rust/flags-consumer/src/config.rs`.
//! `ConsumerConfig` has no useful field-level defaults (group/topic are service-specific),
//! so a nested derive would be awkward; the helpers compose the common-kafka configs
//! explicitly instead.

use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

const POOL_NAME: &str = "posthog_cohort";

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ── Observability ─────────────────────────────────────────────────────
    /// Host for the observability HTTP server (`/_health`, `/_ready`, `/metrics`).
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    /// Port for the observability HTTP server. Overridden by the Helm values in PR 1.11.
    #[envconfig(default = "3322")]
    pub bind_port: u16,

    /// Install the Prometheus recorder and expose `/metrics`.
    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    // ── Kafka (shared) ────────────────────────────────────────────────────
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    // ── Consumer (input: clickhouse_events_json) ──────────────────────────
    #[envconfig(default = "clickhouse_events_json")]
    pub input_topic: String,

    #[envconfig(default = "cohort-event-shuffler")]
    pub kafka_consumer_group: String,

    /// A new consumer group on a high-volume live topic starts at the tail rather than
    /// replaying days of history; historical population is the seed topic's job (TDD §4.4).
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    // ── Producer (output: cohort_stream_events) ───────────────────────────
    #[envconfig(default = "cohort_stream_events")]
    pub output_topic: String,

    /// **Load-bearing** (key design point 1): must be `murmur2_random` so this Rust producer
    /// co-partitions a given `(team_id, person_id)` identically to the Node-produced
    /// `person_merge_events` and the future seed/cascade producers. Changing it silently
    /// breaks cross-topic / cross-runtime partition affinity. Exposed as config only so ops
    /// can pin it explicitly per environment.
    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: String,

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String,

    // ── Postgres (posthog_cohort realtime team index) ─────────────────────
    /// DSN for the main PostHog database that owns `posthog_cohort`.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub pg_acquire_timeout_secs: u64,

    /// Statement timeout for the team-index SELECT (ms). `0` → database default.
    #[envconfig(default = "5000")]
    pub pg_statement_timeout_ms: u64,

    // ── Team index refresh ────────────────────────────────────────────────
    #[envconfig(default = "300")]
    pub team_index_refresh_secs: u64,

    #[envconfig(default = "60")]
    pub team_index_refresh_jitter_secs: u64,

    // ── Batching ──────────────────────────────────────────────────────────
    /// Max events pulled per consume→filter→produce cycle.
    #[envconfig(default = "1000")]
    pub recv_batch_size: usize,

    /// Max wait before a partial batch is processed.
    #[envconfig(default = "500")]
    pub recv_batch_timeout_ms: u64,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn recv_batch_timeout(&self) -> Duration {
        Duration::from_millis(self.recv_batch_timeout_ms)
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

    /// Pool config for the team-index reader: small (defaults min 1 / max 5) since the only
    /// query is the periodic `SELECT DISTINCT team_id` refresh.
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

    /// Common Kafka connection + producer config. The partitioner is always set (the default
    /// is `murmur2_random`); the producer queue/timeout knobs use the same conservative
    /// values as other PostHog producers.
    pub fn build_kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_rack: self.kafka_client_rack.clone(),
            kafka_client_id: self.kafka_client_id.clone(),
            kafka_compression_codec: self.kafka_compression_codec.clone(),
            kafka_producer_partitioner: Some(self.kafka_producer_partitioner.clone()),
            kafka_producer_linger_ms: 20,
            kafka_producer_queue_mib: 400,
            kafka_producer_queue_messages: 10_000_000,
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

    /// Consumer config for `clickhouse_events_json`. Auto-commit is disabled: the loop stores
    /// offsets manually only after the forwarded envelopes are ack'd, then commits per batch
    /// (TDD at-least-once ordering, key design point 2).
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
            recv_batch_size: 1000,
            recv_batch_timeout_ms: 500,
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
