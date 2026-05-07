use std::collections::HashSet;
use std::time::Duration;

use common_kafka::config::{ConsumerConfig, KafkaConfig};
use envconfig::Envconfig;

/// Configuration for the `flags-consumer` CDC service.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ── Database ──────────────────────────────────────────────────────────
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/flags_read_store")]
    pub flags_read_store_database_url: String,

    #[envconfig(default = "20")]
    pub max_pg_connections: u32,

    #[envconfig(default = "5")]
    pub min_pg_connections: u32,

    #[envconfig(default = "10")]
    pub acquire_timeout_secs: u64,

    #[envconfig(default = "300")]
    pub idle_timeout_secs: u64,

    /// Statement timeout for CDC writes (ms).
    #[envconfig(default = "5000")]
    pub write_statement_timeout_ms: u64,

    #[envconfig(default = "10")]
    pub pool_monitor_interval_secs: u64,

    // ── Kafka ─────────────────────────────────────────────────────────────
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    #[envconfig(default = "flags-cdc-consumer")]
    pub kafka_consumer_group: String,

    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    #[envconfig(default = "clickhouse_person")]
    pub kafka_person_topic: String,

    #[envconfig(default = "clickhouse_person_distinct_id")]
    pub kafka_person_distinct_id_topic: String,

    // ── Batching ──────────────────────────────────────────────────────────
    /// Max messages per batch write.
    #[envconfig(default = "500")]
    pub batch_size: usize,

    /// Max wait (ms) before flushing a partial batch.
    #[envconfig(default = "100")]
    pub batch_timeout_ms: u64,

    // ── Team filtering (POC scoping) ──────────────────────────────────────
    /// Comma-separated team IDs to process. Empty means "all teams".
    #[envconfig(default = "")]
    pub filtered_team_ids: String,

    // ── Retry / resilience ────────────────────────────────────────────────
    #[envconfig(default = "3")]
    pub max_retries: u32,

    /// Base backoff between retries (doubles each attempt).
    #[envconfig(default = "50")]
    pub retry_backoff_base_ms: u64,

    // ── Heartbeat ─────────────────────────────────────────────────────────
    #[envconfig(default = "10")]
    pub heartbeat_interval_secs: u64,

    // ── Observability ─────────────────────────────────────────────────────
    #[envconfig(default = "9105")]
    pub metrics_port: u16,
}

impl Config {
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
        if self.write_statement_timeout_ms == 0 {
            None
        } else {
            Some(self.write_statement_timeout_ms)
        }
    }

    pub fn batch_timeout(&self) -> Duration {
        Duration::from_millis(self.batch_timeout_ms)
    }

    /// Parse the comma-separated team filter into a `HashSet`.
    /// Returns `None` if empty (meaning "all teams").
    pub fn parsed_team_filter(&self) -> Option<HashSet<i32>> {
        if self.filtered_team_ids.is_empty() {
            return None;
        }
        Some(
            self.filtered_team_ids
                .split(',')
                .filter_map(|s| s.trim().parse::<i32>().ok())
                .collect(),
        )
    }

    /// Build the common Kafka connection config.
    pub fn build_kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_rack: self.kafka_client_rack.clone(),
            kafka_client_id: self.kafka_client_id.clone(),
            // Producer settings — unused by consumers but required by KafkaConfig.
            kafka_producer_linger_ms: 20,
            kafka_producer_queue_mib: 400,
            kafka_producer_queue_messages: 10_000_000,
            kafka_message_timeout_ms: 20_000,
            kafka_compression_codec: "none".to_string(),
            kafka_producer_batch_size: None,
            kafka_producer_batch_num_messages: None,
            kafka_producer_enable_idempotence: None,
            kafka_producer_max_in_flight_requests_per_connection: None,
            kafka_producer_topic_metadata_refresh_interval_ms: None,
            kafka_producer_message_max_bytes: None,
            kafka_producer_sticky_partitioning_linger_ms: None,
        }
    }

    /// Build the consumer config for the `clickhouse_person` topic.
    pub fn build_person_consumer_config(&self) -> ConsumerConfig {
        ConsumerConfig {
            kafka_consumer_group: self.kafka_consumer_group.clone(),
            kafka_consumer_topic: self.kafka_person_topic.clone(),
            kafka_consumer_offset_reset: self.kafka_consumer_offset_reset.clone(),
            kafka_consumer_auto_commit: true,
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

    /// Build the consumer config for the `clickhouse_person_distinct_id` topic.
    pub fn build_distinct_id_consumer_config(&self) -> ConsumerConfig {
        ConsumerConfig {
            kafka_consumer_group: self.kafka_consumer_group.clone(),
            kafka_consumer_topic: self.kafka_person_distinct_id_topic.clone(),
            kafka_consumer_offset_reset: self.kafka_consumer_offset_reset.clone(),
            kafka_consumer_auto_commit: true,
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
            flags_read_store_database_url: "postgres://localhost/test".to_string(),
            max_pg_connections: 5,
            min_pg_connections: 1,
            acquire_timeout_secs: 10,
            idle_timeout_secs: 300,
            write_statement_timeout_ms: 5000,
            pool_monitor_interval_secs: 10,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_rack: String::new(),
            kafka_client_id: String::new(),
            kafka_consumer_group: "test-group".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
            kafka_person_topic: "clickhouse_person".to_string(),
            kafka_person_distinct_id_topic: "clickhouse_person_distinct_id".to_string(),
            batch_size: 500,
            batch_timeout_ms: 100,
            filtered_team_ids: String::new(),
            max_retries: 3,
            retry_backoff_base_ms: 50,
            heartbeat_interval_secs: 10,
            metrics_port: 9105,
        }
    }

    #[test]
    fn test_parsed_team_filter_empty() {
        let config = test_config();
        assert!(config.parsed_team_filter().is_none());
    }

    #[test]
    fn test_parsed_team_filter_single() {
        let mut config = test_config();
        config.filtered_team_ids = "42".to_string();
        let filter = config.parsed_team_filter().unwrap();
        assert_eq!(filter.len(), 1);
        assert!(filter.contains(&42));
    }

    #[test]
    fn test_parsed_team_filter_multiple() {
        let mut config = test_config();
        config.filtered_team_ids = "1, 2, 3".to_string();
        let filter = config.parsed_team_filter().unwrap();
        assert_eq!(filter.len(), 3);
        assert!(filter.contains(&1));
        assert!(filter.contains(&2));
        assert!(filter.contains(&3));
    }

    #[test]
    fn test_parsed_team_filter_invalid_entries() {
        let mut config = test_config();
        config.filtered_team_ids = "1, abc, 3".to_string();
        let filter = config.parsed_team_filter().unwrap();
        assert_eq!(filter.len(), 2);
        assert!(filter.contains(&1));
        assert!(filter.contains(&3));
    }

    #[test]
    fn test_batch_timeout() {
        let config = test_config();
        assert_eq!(config.batch_timeout(), Duration::from_millis(100));
    }

    #[test]
    fn test_statement_timeout_zero_means_none() {
        let mut config = test_config();
        config.write_statement_timeout_ms = 0;
        assert!(config.statement_timeout().is_none());
    }
}
