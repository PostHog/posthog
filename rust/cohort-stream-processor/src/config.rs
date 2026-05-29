//! Service configuration, loaded from environment variables via `envconfig`
//! (pattern mirrors `rust/feature-flags/src/config.rs` and the shuffler's `config.rs`).
//!
//! PR 1.3 adds the Postgres reader and filter-catalog refresh knobs. The Kafka topics/consumer
//! groups, RocksDB path and tuning, sweep interval + `safety_margin_ms`, S3 checkpoint
//! settings, cascade caps, and kill-switch list are added by their respective Phase 1–3 PRs
//! (TDD §6) as each subsystem is wired in.

use std::path::PathBuf;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use rdkafka::ClientConfig;

use crate::store::StoreConfig;

const POOL_NAME: &str = "posthog_cohort";

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// Host for the observability HTTP server (`/_health`, `/_ready`, `/metrics`).
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    /// Port for the observability HTTP server. Overridden by the Helm values in PR 1.11.
    #[envconfig(default = "3323")]
    pub bind_port: u16,

    /// Install the Prometheus recorder and expose `/metrics`.
    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    // ── Postgres (posthog_cohort realtime filter catalog) ─────────────────
    /// DSN for the main PostHog database that owns `posthog_cohort`.
    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    #[envconfig(default = "1")]
    pub min_pg_connections: u32,

    #[envconfig(default = "5")]
    pub max_pg_connections: u32,

    #[envconfig(default = "10")]
    pub pg_acquire_timeout_secs: u64,

    /// Statement timeout for the catalog SELECT (ms). `0` → database default.
    #[envconfig(default = "5000")]
    pub pg_statement_timeout_ms: u64,

    // ── Filter catalog refresh ────────────────────────────────────────────
    #[envconfig(default = "300")]
    pub filter_catalog_refresh_secs: u64,

    #[envconfig(default = "60")]
    pub filter_catalog_refresh_jitter_secs: u64,

    // ── Partition routing (PR 1.5) ────────────────────────────────────────
    /// Bounded buffer, in sub-batches, for each per-partition worker channel. This is the
    /// backpressure knob (§2.3): once a worker is this far behind the router, routing to *that*
    /// partition blocks instead of growing memory unbounded, while other partitions keep flowing.
    /// The buffer is per active partition, so peak in-flight scales with the assigned partition
    /// count. Consumed by PR 1.7 when it constructs the [`crate::partitions::PartitionRouter`].
    #[envconfig(default = "1024")]
    pub partition_channel_buffer: usize,

    // ── Kafka (shared) ─────────────────────────────────────────────────────
    /// Bootstrap servers, mirroring the shuffler's naming/defaults.
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    // ── Consumer (input: cohort_stream_events) ─────────────────────────────
    /// The hot-path input topic. Named specifically (not `input_topic`) so later PRs can add
    /// sibling topics (`cohort_cascade_events`, `cohort_stream_seed_events`, …) without ambiguity.
    #[envconfig(default = "cohort_stream_events")]
    pub cohort_stream_events_topic: String,

    #[envconfig(default = "cohort-stream-processor")]
    pub kafka_consumer_group: String,

    /// A new consumer group on a high-volume live topic starts at the tail rather than replaying
    /// the topic's retention; the parity harness (PR 1.9/1.10) defines its window forward from
    /// processor start. Matches the shuffler.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    // ── Producer (output: cohort_membership_changed_shadow) ────────────────
    /// The shadow output topic for membership changes (TDD §4.7). Distinct from the legacy
    /// `cohort_membership_changed` so the new pipeline can run side-by-side for parity (M1); the
    /// M4 cut-over may retarget this to the real topic.
    #[envconfig(default = "cohort_membership_changed_shadow")]
    pub cohort_membership_changed_topic: String,

    /// **Load-bearing** (key design point 1): `murmur2_random` co-partitions a given `person_id`
    /// key identically to the Node/Python producers, so the shadow topic partitions the same way
    /// the legacy producer does. Mirrors the shuffler; exposed as config only so ops can pin it.
    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: String,

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String,

    // ── Batching + commit cadence ──────────────────────────────────────────
    /// Max events pulled per consume → route cycle.
    #[envconfig(default = "1000")]
    pub recv_batch_size: usize,

    /// Max wait before a partial batch is routed (also the idle-topic heartbeat cadence).
    #[envconfig(default = "500")]
    pub recv_batch_timeout_ms: u64,

    /// How often processed offsets are committed back to Kafka.
    #[envconfig(default = "5000")]
    pub offset_commit_interval_ms: u64,

    // ── State store (RocksDB) ──────────────────────────────────────────────
    /// On-disk path for the per-process RocksDB state store.
    #[envconfig(default = "cohort-store")]
    pub store_path: String,
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn filter_catalog_refresh_interval(&self) -> Duration {
        Duration::from_secs(self.filter_catalog_refresh_secs)
    }

    pub fn filter_catalog_refresh_jitter(&self) -> Duration {
        Duration::from_secs(self.filter_catalog_refresh_jitter_secs)
    }

    fn pg_statement_timeout(&self) -> Option<u64> {
        (self.pg_statement_timeout_ms != 0).then_some(self.pg_statement_timeout_ms)
    }

    /// Pool config for the catalog reader: small (defaults min 1 / max 5) since the only query
    /// is the periodic `SELECT … FROM posthog_cohort` refresh.
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

    pub fn recv_batch_timeout(&self) -> Duration {
        Duration::from_millis(self.recv_batch_timeout_ms)
    }

    pub fn offset_commit_interval(&self) -> Duration {
        Duration::from_millis(self.offset_commit_interval_ms)
    }

    /// RocksDB settings for the state store. Only the path is configurable today; the cache /
    /// write-buffer / open-files knobs use [`StoreConfig::default`] pending the §5.1 sizing work.
    pub fn store_config(&self) -> StoreConfig {
        StoreConfig {
            path: PathBuf::from(&self.store_path),
            ..StoreConfig::default()
        }
    }

    /// Build the `rdkafka` client config for the `cohort_stream_events` group consumer.
    ///
    /// Auto-commit and auto-offset-store are **off**: the consume loop marks each partition's
    /// offset only once its sub-batch is routed, and the commit tick turns the
    /// [`OffsetTracker`](crate::partitions::OffsetTracker) snapshot into the committed
    /// `TopicPartitionList`. The session/heartbeat/poll defaults are lifted from
    /// `kafka-deduplicator`'s `for_batch_consumer`.
    pub fn consumer_client_config(&self) -> ClientConfig {
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &self.kafka_hosts)
            .set("group.id", &self.kafka_consumer_group)
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("auto.offset.reset", &self.kafka_consumer_offset_reset)
            .set("socket.timeout.ms", "10000")
            .set("session.timeout.ms", "60000")
            .set("heartbeat.interval.ms", "5000")
            .set("max.poll.interval.ms", "300000");

        if !self.kafka_client_id.is_empty() {
            config.set("client.id", &self.kafka_client_id);
        }
        if !self.kafka_client_rack.is_empty() {
            config.set("client.rack", &self.kafka_client_rack);
        }
        if self.kafka_tls {
            config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        }
        config
    }

    /// Common Kafka connection + producer config for the `cohort_membership_changed_shadow`
    /// producer, mirroring the shuffler's `build_kafka_config`. The partitioner is always set (the
    /// default `murmur2_random` is load-bearing for cross-runtime co-partitioning); the producer
    /// queue / timeout knobs use the same conservative values as other PostHog producers.
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
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> Config {
        Config {
            bind_host: "0.0.0.0".to_string(),
            bind_port: 3323,
            export_prometheus: true,
            database_url: "postgres://posthog:posthog@localhost:5432/posthog".to_string(),
            min_pg_connections: 1,
            max_pg_connections: 5,
            pg_acquire_timeout_secs: 10,
            pg_statement_timeout_ms: 5000,
            filter_catalog_refresh_secs: 300,
            filter_catalog_refresh_jitter_secs: 60,
            partition_channel_buffer: 1024,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_id: String::new(),
            kafka_client_rack: String::new(),
            cohort_stream_events_topic: "cohort_stream_events".to_string(),
            kafka_consumer_group: "cohort-stream-processor".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
            cohort_membership_changed_topic: "cohort_membership_changed_shadow".to_string(),
            kafka_producer_partitioner: "murmur2_random".to_string(),
            kafka_compression_codec: "none".to_string(),
            recv_batch_size: 1000,
            recv_batch_timeout_ms: 500,
            offset_commit_interval_ms: 5000,
            store_path: "cohort-store".to_string(),
        }
    }

    #[test]
    fn refresh_interval_and_jitter_map_from_seconds() {
        let config = test_config();
        assert_eq!(
            config.filter_catalog_refresh_interval(),
            Duration::from_secs(300)
        );
        assert_eq!(
            config.filter_catalog_refresh_jitter(),
            Duration::from_secs(60)
        );
    }

    #[test]
    fn statement_timeout_zero_means_database_default() {
        let mut config = test_config();
        config.pg_statement_timeout_ms = 0;
        assert!(config.pool_config().statement_timeout_ms.is_none());
    }

    #[test]
    fn pool_config_uses_the_named_pool() {
        let config = test_config();
        assert_eq!(config.pool_config().pool_name.as_deref(), Some(POOL_NAME));
    }

    #[test]
    fn consumer_config_disables_auto_commit_and_offset_store() {
        let config = test_config();
        let client = config.consumer_client_config();
        assert_eq!(client.get("enable.auto.commit"), Some("false"));
        assert_eq!(client.get("enable.auto.offset.store"), Some("false"));
        assert_eq!(client.get("group.id"), Some("cohort-stream-processor"));
        assert_eq!(client.get("auto.offset.reset"), Some("latest"));
        assert_eq!(client.get("bootstrap.servers"), Some("localhost:9092"));
    }

    #[test]
    fn consumer_config_sets_tls_keys_only_when_enabled() {
        let mut config = test_config();
        assert_eq!(
            config.consumer_client_config().get("security.protocol"),
            None
        );

        config.kafka_tls = true;
        assert_eq!(
            config.consumer_client_config().get("security.protocol"),
            Some("ssl"),
        );
    }

    #[test]
    fn store_config_threads_through_the_configured_path() {
        let mut config = test_config();
        config.store_path = "/var/lib/cohort/state".to_string();
        assert_eq!(
            config.store_config().path,
            std::path::PathBuf::from("/var/lib/cohort/state"),
        );
    }

    #[test]
    fn build_kafka_config_pins_the_murmur2_partitioner() {
        let kafka = test_config().build_kafka_config();
        // The partitioner is load-bearing for cross-runtime co-partitioning of the shadow topic.
        assert_eq!(
            kafka.kafka_producer_partitioner.as_deref(),
            Some("murmur2_random"),
        );
        assert_eq!(kafka.kafka_compression_codec, "none");
        assert_eq!(kafka.kafka_hosts, "localhost:9092");
    }
}
