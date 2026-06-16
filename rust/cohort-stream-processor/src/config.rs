//! Service configuration, loaded from environment variables via `envconfig`.

use std::path::PathBuf;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use common_types::cohort::TeamAllowlist;
use envconfig::Envconfig;
use rdkafka::ClientConfig;

use crate::store::StoreConfig;
use crate::workers::TransferRetryPolicy;

const POOL_NAME: &str = "posthog_cohort";

#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    /// Host for the observability HTTP server (`/_health`, `/_ready`, `/metrics`).
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    /// Port for the observability HTTP server.
    #[envconfig(default = "3323")]
    pub bind_port: u16,

    /// Install the Prometheus recorder and expose `/metrics`.
    #[envconfig(default = "true")]
    pub export_prometheus: bool,

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

    #[envconfig(default = "300")]
    pub filter_catalog_refresh_secs: u64,

    #[envconfig(default = "60")]
    pub filter_catalog_refresh_jitter_secs: u64,

    /// Teams the filter catalog is scoped to. Set `all` to disable the gate. See [`TeamAllowlist`].
    #[envconfig(from = "REALTIME_COHORT_TEAM_ALLOWLIST", default = "2")]
    pub team_allowlist: TeamAllowlist,

    /// Bounded buffer (in sub-batches) per per-partition worker channel.
    /// Routing to a partition this far behind blocks rather than growing memory unbounded.
    #[envconfig(default = "1024")]
    pub partition_channel_buffer: usize,

    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    /// The hot-path input topic.
    #[envconfig(default = "cohort_stream_events")]
    pub cohort_stream_events_topic: String,

    #[envconfig(default = "cohort-stream-processor")]
    pub kafka_consumer_group: String,

    /// Start at the tail, not the topic's retention.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    /// How long the broker waits for heartbeats before declaring this consumer dead. With static
    /// membership, a restart within this window reclaims partitions with no rebalance.
    #[envconfig(default = "60000")]
    pub kafka_session_timeout_ms: u64,

    /// The person-merge trigger topic, keyed by `hash(team_id, old_person_uuid)` so a merge lands on
    /// P_old's worker.
    #[envconfig(default = "person_merge_events")]
    pub person_merge_events_topic: String,

    /// The internal state-transfer topic, keyed by `hash(team_id, new_person_uuid)` so a packaged
    /// drain lands on P_new's worker. Must be co-partitioned with `cohort_stream_events`.
    #[envconfig(default = "cohort_merge_state_transfer")]
    pub cohort_merge_state_transfer_topic: String,

    /// Group for the `person_merge_events` follower — separate so drain-path lag is observable.
    #[envconfig(default = "cohort-stream-merges")]
    pub kafka_merge_consumer_group: String,

    /// Group for the `cohort_merge_state_transfer` follower.
    #[envconfig(default = "cohort-stream-merge-apply")]
    pub kafka_merge_apply_consumer_group: String,

    /// Inline retries after the first transfer-produce attempt. The default budget
    /// (5 x 0.5/1/2/4/8 s) keeps a blocked worker inside the liveness and graceful-shutdown
    /// windows; exhaustion leaves the transfer staged for the periodic redrive.
    #[envconfig(default = "5")]
    pub merge_transfer_max_retries: u32,

    /// First retry backoff (ms); doubles per retry.
    #[envconfig(default = "500")]
    pub merge_transfer_retry_base_ms: u64,

    /// Backoff ceiling (ms).
    #[envconfig(default = "8000")]
    pub merge_transfer_retry_cap_ms: u64,

    /// `message.timeout.ms` for the transfer producer alone — much shorter than the shared 20 s so a
    /// single produce attempt fast-fails against a black-hole broker instead of stalling a worker.
    /// The inline retry loop wraps `merge_transfer_max_retries + 1` attempts; the budget only holds
    /// inside the 30 s graceful-shutdown window if each attempt itself fast-fails. See
    /// `build_transfer_kafka_config` and the budget arithmetic in `workers::merge_path`.
    #[envconfig(default = "2000")]
    pub merge_transfer_message_timeout_ms: u32,

    /// How often the redrive scans `cf_pending_transfers` and re-produces staged transfers whose
    /// inline retry budget was exhausted.
    #[envconfig(default = "60000")]
    pub merge_redrive_interval_ms: u64,

    // --- Merge-CF garbage collection retention ---
    //
    // The merge idempotence markers (`cf_merge_drains_applied`, `cf_merge_applied`) and the redirect
    // tombstones (`cf_merge_tombstones`) are written once and never overwritten, so they accumulate
    // until evicted. A periodic scan-based sweep deletes entries whose value timestamp is older than
    // the retention floor below. Marker CFs use `merge_marker_retention_ms`; tombstones use the
    // longer `merge_tombstone_retention_ms` (they also guard the events topics, not just the merge
    // topic). `cf_pending_transfers` is the redrive's outbox and is NEVER GC'd here.
    //
    // STANDING COUPLING: these floors are derived from the Kafka topic `retention.ms` values pinned
    // in Terraform (`person_merge_events`/`cohort_merge_state_transfer` = 7d, `cohort_stream_events`
    // = 24h, `clickhouse_events_json` = 7d). If any of those `retention.ms` values change, these
    // knobs MUST follow — a marker evicted before its source topic's retention lapses re-opens the
    // replay-dedup window it exists to close.
    /// Retention floor for both merge marker CFs (`cf_merge_drains_applied`, `cf_merge_applied`). A
    /// marker is GC'd once its `drained_at_ms` / `applied_at_ms` is older than `now − this`. Default
    /// 8d = 7d merge-topic retention + 1d safety: a marker must outlive every replay of the
    /// 7d-retention `person_merge_events` / `cohort_merge_state_transfer` topics.
    #[envconfig(default = "691200000")]
    pub merge_marker_retention_ms: u64,

    /// Retention floor for `cf_merge_tombstones`. A tombstone is GC'd once its `merged_at_ms` is
    /// older than `now − this`. Default 9d = `clickhouse_events_json` 7d + `cohort_stream_events`
    /// 24h + 1d safety: a tombstone must outlive every straggler event the redirect closes.
    #[envconfig(default = "777600000")]
    pub merge_tombstone_retention_ms: u64,

    /// How often the merge-CF GC sweep fires. Default 1h.
    #[envconfig(default = "3600000")]
    pub merge_gc_interval_ms: u64,

    /// Max keys scanned (and at most deleted) per CF, per partition, per GC tick. Bounds the GC's
    /// per-tick work; the per-CF resume cursor continues where the last tick stopped. Default 10k —
    /// at the prod merge rate (~16k markers/day/partition) that is ~15× headroom over the 1h cadence.
    #[envconfig(default = "10000")]
    pub merge_gc_scan_limit: usize,

    // --- Cascade (cohort-of-cohort) depth + fan-out caps ---
    /// Max cascade hops before an outgoing cascade is dropped (`incoming.depth >= this`). Default 8.
    #[envconfig(default = "8")]
    pub cohort_cascade_depth_cap: u8,

    /// Max referrer re-evaluations per upstream flip. Default 1000.
    #[envconfig(default = "1000")]
    pub cohort_cascade_fanout_cap: usize,

    /// Promote resolvable, cycle-free cohort-of-cohort cohorts to composition. Default off:
    /// ref-bearing cohorts stay excluded.
    #[envconfig(from = "COHORT_CASCADE_ENABLED", default = "false")]
    pub cohort_cascade_enabled: bool,

    /// Stable per-pod identity for `group.instance.id` + `client.id`, enabling static membership.
    /// Read from `POD_NAME`, else `HOSTNAME`. Absent means no static membership.
    #[envconfig(from = "POD_NAME")]
    pub pod_name: Option<String>,

    #[envconfig(from = "HOSTNAME")]
    pub pod_hostname: Option<String>,

    /// The shadow output topic for membership changes.
    #[envconfig(default = "cohort_membership_changed_shadow")]
    pub cohort_membership_changed_topic: String,

    /// `murmur2_random` co-partitions a `person_id` key identically to the Node/Python producers.
    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: String,

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String,

    /// Max events pulled per consume-route cycle.
    #[envconfig(default = "1000")]
    pub recv_batch_size: usize,

    /// Max wait before a partial batch is routed.
    #[envconfig(default = "500")]
    pub recv_batch_timeout_ms: u64,

    /// How often processed offsets are committed back to Kafka.
    #[envconfig(default = "5000")]
    pub offset_commit_interval_ms: u64,

    /// How often the sweep fires to evict state whose eviction deadline has passed.
    #[envconfig(default = "30000")]
    pub sweep_interval_ms: u64,

    /// Grace period added to every eviction deadline before the sweep acts. The sweep evicts a key
    /// only once `deadline + safety_margin < now`, absorbing consumer-lag spikes.
    #[envconfig(default = "300000")]
    pub sweep_safety_margin_ms: u64,

    /// On-disk path for the per-process RocksDB state store.
    #[envconfig(default = "cohort-store")]
    pub store_path: String,

    /// Destroy any existing store at `store_path` before opening, so re-acquiring a partition never
    /// serves stale state left by a previous owner.
    #[envconfig(default = "true")]
    pub wipe_store_on_start: bool,
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

    /// Pool config for the catalog reader.
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

    /// How often the sweep fires.
    pub fn sweep_interval(&self) -> Duration {
        Duration::from_millis(self.sweep_interval_ms)
    }

    /// The grace period subtracted from `now` before a deadline is considered due.
    pub fn sweep_safety_margin(&self) -> Duration {
        Duration::from_millis(self.sweep_safety_margin_ms)
    }

    /// Inline bounded backoff for the transfer produce, from the `MERGE_TRANSFER_*` envs.
    pub fn transfer_retry_policy(&self) -> TransferRetryPolicy {
        TransferRetryPolicy {
            max_retries: self.merge_transfer_max_retries,
            base: Duration::from_millis(self.merge_transfer_retry_base_ms),
            cap: Duration::from_millis(self.merge_transfer_retry_cap_ms),
        }
    }

    /// How often the pending-transfer redrive fires.
    pub fn merge_redrive_interval(&self) -> Duration {
        Duration::from_millis(self.merge_redrive_interval_ms)
    }

    /// How often the merge-CF GC sweep fires.
    pub fn merge_gc_interval(&self) -> Duration {
        Duration::from_millis(self.merge_gc_interval_ms)
    }

    /// RocksDB settings for the state store.
    pub fn store_config(&self) -> StoreConfig {
        StoreConfig {
            path: PathBuf::from(&self.store_path),
            wipe_on_start: self.wipe_store_on_start,
            ..StoreConfig::default()
        }
    }

    /// Stable per-pod identity for static group membership, `POD_NAME` preferred over `HOSTNAME`.
    /// `None` leaves static membership off.
    pub fn pod_identity(&self) -> Option<&str> {
        [self.pod_name.as_deref(), self.pod_hostname.as_deref()]
            .into_iter()
            .flatten()
            .find(|id| !id.is_empty())
    }

    /// Build the `rdkafka` client config for the `cohort_stream_events` group consumer.
    ///
    /// Auto-commit and auto-offset-store are off: the consume loop marks offsets only after a
    /// sub-batch is routed and produced. `cooperative-sticky` + static membership ensure a
    /// membership change revokes only the partitions that move.
    pub fn consumer_client_config(&self) -> ClientConfig {
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &self.kafka_hosts)
            .set("group.id", &self.kafka_consumer_group)
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("auto.offset.reset", &self.kafka_consumer_offset_reset)
            .set("partition.assignment.strategy", "cooperative-sticky")
            .set("socket.timeout.ms", "10000")
            .set(
                "session.timeout.ms",
                self.kafka_session_timeout_ms.to_string(),
            )
            .set("heartbeat.interval.ms", "5000")
            .set("max.poll.interval.ms", "300000");

        // Static membership; an explicit `kafka_client_id` overrides `client.id` below.
        if let Some(id) = self.pod_identity() {
            config.set("group.instance.id", id).set("client.id", id);
        }
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

    /// Build the `rdkafka` client config for a merge-protocol follower consumer.
    ///
    /// Followers never `subscribe()` — the events group's rebalance mirrors assignments onto them —
    /// so there is no assignment strategy and no static membership; `group.id` exists only so
    /// commits land on an observable group. `auto.offset.reset` is hard-coded to `earliest`: a
    /// never-subscribing group is `Empty` to the broker, so its committed offsets are pruned after
    /// `offsets.retention.minutes`, and a tail reset after pruning would silently skip the merge
    /// backlog.
    pub fn follower_client_config(&self, group: &str) -> ClientConfig {
        let mut config = ClientConfig::new();
        config
            .set("bootstrap.servers", &self.kafka_hosts)
            .set("group.id", group)
            .set("enable.auto.commit", "false")
            .set("enable.auto.offset.store", "false")
            .set("auto.offset.reset", "earliest")
            .set("socket.timeout.ms", "10000");

        // `client.id` for observability only; no `group.instance.id` (no membership to make static).
        if let Some(id) = self.pod_identity() {
            config.set("client.id", id);
        }
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

    /// Kafka producer config for the membership output topic.
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

    /// Producer config for the merge state-transfer sink: the shared config with a shorter
    /// `message.timeout.ms`. The transfer produce runs inline on a partition worker under a bounded
    /// retry loop, so a long per-attempt timeout multiplies into a worst-case worker hold that blows
    /// the 30 s graceful-shutdown window (see the budget arithmetic in `workers::merge_path`).
    pub fn build_transfer_kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_message_timeout_ms: self.merge_transfer_message_timeout_ms,
            ..self.build_kafka_config()
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
            team_allowlist: TeamAllowlist::All,
            partition_channel_buffer: 1024,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_id: String::new(),
            kafka_client_rack: String::new(),
            cohort_stream_events_topic: "cohort_stream_events".to_string(),
            kafka_consumer_group: "cohort-stream-processor".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
            person_merge_events_topic: "person_merge_events".to_string(),
            cohort_merge_state_transfer_topic: "cohort_merge_state_transfer".to_string(),
            kafka_merge_consumer_group: "cohort-stream-merges".to_string(),
            kafka_merge_apply_consumer_group: "cohort-stream-merge-apply".to_string(),
            merge_transfer_max_retries: 5,
            merge_transfer_retry_base_ms: 500,
            merge_transfer_retry_cap_ms: 8000,
            merge_transfer_message_timeout_ms: 2000,
            merge_redrive_interval_ms: 60_000,
            merge_marker_retention_ms: 691_200_000,
            merge_tombstone_retention_ms: 777_600_000,
            merge_gc_interval_ms: 3_600_000,
            merge_gc_scan_limit: 10_000,
            cohort_cascade_depth_cap: 8,
            cohort_cascade_fanout_cap: 1000,
            cohort_cascade_enabled: false,
            kafka_session_timeout_ms: 60000,
            pod_name: None,
            pod_hostname: None,
            cohort_membership_changed_topic: "cohort_membership_changed_shadow".to_string(),
            kafka_producer_partitioner: "murmur2_random".to_string(),
            kafka_compression_codec: "none".to_string(),
            recv_batch_size: 1000,
            recv_batch_timeout_ms: 500,
            offset_commit_interval_ms: 5000,
            sweep_interval_ms: 30000,
            sweep_safety_margin_ms: 300000,
            store_path: "cohort-store".to_string(),
            wipe_store_on_start: true,
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
    fn sweep_interval_and_safety_margin_map_from_millis() {
        let config = test_config();
        assert_eq!(config.sweep_interval(), Duration::from_millis(30_000));
        assert_eq!(config.sweep_safety_margin(), Duration::from_millis(300_000));
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
    fn consumer_config_uses_cooperative_sticky_and_the_configured_session_timeout() {
        let mut config = test_config();
        config.kafka_session_timeout_ms = 45000;
        let client = config.consumer_client_config();
        assert_eq!(
            client.get("partition.assignment.strategy"),
            Some("cooperative-sticky"),
        );
        assert_eq!(client.get("session.timeout.ms"), Some("45000"));
    }

    #[test]
    fn consumer_config_sets_static_membership_only_when_pod_identity_is_present() {
        let mut config = test_config();
        assert_eq!(
            config.consumer_client_config().get("group.instance.id"),
            None,
        );

        config.pod_hostname = Some("cohort-stream-processor-2".to_string());
        let client = config.consumer_client_config();
        assert_eq!(
            client.get("group.instance.id"),
            Some("cohort-stream-processor-2"),
        );
        assert_eq!(client.get("client.id"), Some("cohort-stream-processor-2"));
    }

    #[test]
    fn pod_identity_prefers_pod_name_and_ignores_blanks() {
        let mut config = test_config();
        config.pod_name = Some("pod-from-downward-api".to_string());
        config.pod_hostname = Some("hostname".to_string());
        assert_eq!(config.pod_identity(), Some("pod-from-downward-api"));

        config.pod_name = Some(String::new());
        assert_eq!(config.pod_identity(), Some("hostname"));

        config.pod_hostname = None;
        assert_eq!(config.pod_identity(), None);
    }

    #[test]
    fn explicit_client_id_overrides_pod_identity() {
        let mut config = test_config();
        config.pod_hostname = Some("hostname".to_string());
        config.kafka_client_id = "explicit-client".to_string();
        let client = config.consumer_client_config();
        // Static membership still keyed on the pod identity, but client.id is the explicit override.
        assert_eq!(client.get("group.instance.id"), Some("hostname"));
        assert_eq!(client.get("client.id"), Some("explicit-client"));
    }

    #[test]
    fn store_config_threads_the_wipe_on_start_flag() {
        let mut config = test_config();
        config.wipe_store_on_start = true;
        assert!(config.store_config().wipe_on_start);
        config.wipe_store_on_start = false;
        assert!(!config.store_config().wipe_on_start);
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
    fn merge_envs_default_to_the_expected_topology() {
        let config = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert_eq!(config.person_merge_events_topic, "person_merge_events");
        assert_eq!(
            config.cohort_merge_state_transfer_topic,
            "cohort_merge_state_transfer",
        );
        assert_eq!(config.kafka_merge_consumer_group, "cohort-stream-merges");
        assert_eq!(
            config.kafka_merge_apply_consumer_group,
            "cohort-stream-merge-apply",
        );
        assert_eq!(
            config.transfer_retry_policy(),
            TransferRetryPolicy::default()
        );
        assert_eq!(
            config.merge_redrive_interval(),
            Duration::from_millis(60_000)
        );
        // The transfer sink fast-fails per attempt; the shared sink keeps the 20 s timeout.
        assert_eq!(config.merge_transfer_message_timeout_ms, 2000);
        assert_eq!(
            config
                .build_transfer_kafka_config()
                .kafka_message_timeout_ms,
            2000,
        );
        assert_eq!(config.build_kafka_config().kafka_message_timeout_ms, 20_000);
    }

    #[test]
    fn merge_gc_defaults_match_the_tdd_retention_floors() {
        let config = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        // 8d = 7d merge-topic retention + 1d safety — covers both marker CFs.
        assert_eq!(config.merge_marker_retention_ms, 691_200_000);
        assert_eq!(
            config.merge_marker_retention_ms,
            (7 + 1) * 24 * 60 * 60 * 1000,
        );
        // 9d = events 7d + stream 24h + 1d safety.
        assert_eq!(config.merge_tombstone_retention_ms, 777_600_000);
        assert_eq!(
            config.merge_tombstone_retention_ms,
            (7 * 24 + 24 + 24) * 60 * 60 * 1000,
        );
        assert_eq!(config.merge_gc_interval(), Duration::from_millis(3_600_000));
        assert_eq!(config.merge_gc_scan_limit, 10_000);
    }

    #[test]
    fn merge_gc_knobs_override_from_env() {
        let env: std::collections::HashMap<String, String> = [
            ("MERGE_MARKER_RETENTION_MS", "123"),
            ("MERGE_TOMBSTONE_RETENTION_MS", "456"),
            ("MERGE_GC_INTERVAL_MS", "789"),
            ("MERGE_GC_SCAN_LIMIT", "5"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.merge_marker_retention_ms, 123);
        assert_eq!(config.merge_tombstone_retention_ms, 456);
        assert_eq!(config.merge_gc_interval(), Duration::from_millis(789));
        assert_eq!(config.merge_gc_scan_limit, 5);
    }

    #[test]
    fn cascade_caps_default_and_override_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert_eq!(defaults.cohort_cascade_depth_cap, 8);
        assert_eq!(defaults.cohort_cascade_fanout_cap, 1000);
        assert!(
            !defaults.cohort_cascade_enabled,
            "the cascade gate defaults off",
        );

        let env: std::collections::HashMap<String, String> = [
            ("COHORT_CASCADE_DEPTH_CAP", "3"),
            ("COHORT_CASCADE_FANOUT_CAP", "50"),
            ("COHORT_CASCADE_ENABLED", "true"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.cohort_cascade_depth_cap, 3);
        assert_eq!(config.cohort_cascade_fanout_cap, 50);
        assert!(config.cohort_cascade_enabled);
    }

    #[test]
    fn build_transfer_kafka_config_overrides_only_the_message_timeout() {
        let config = test_config();
        let shared = config.build_kafka_config();
        let transfer = config.build_transfer_kafka_config();
        // Only `message.timeout.ms` differs; every other producer knob is inherited.
        assert_eq!(transfer.kafka_message_timeout_ms, 2000);
        assert_eq!(shared.kafka_message_timeout_ms, 20_000);
        assert_eq!(
            transfer.kafka_producer_partitioner,
            shared.kafka_producer_partitioner,
        );
        assert_eq!(transfer.kafka_hosts, shared.kafka_hosts);
        assert_eq!(
            transfer.kafka_compression_codec,
            shared.kafka_compression_codec
        );
        assert_eq!(
            transfer.kafka_producer_linger_ms,
            shared.kafka_producer_linger_ms
        );
        assert_eq!(
            transfer.kafka_producer_queue_mib,
            shared.kafka_producer_queue_mib
        );
    }

    #[test]
    fn merge_envs_override_the_defaults() {
        let env: std::collections::HashMap<String, String> = [
            ("PERSON_MERGE_EVENTS_TOPIC", "pme_test"),
            ("COHORT_MERGE_STATE_TRANSFER_TOPIC", "transfer_test"),
            ("KAFKA_MERGE_CONSUMER_GROUP", "merges-test"),
            ("KAFKA_MERGE_APPLY_CONSUMER_GROUP", "apply-test"),
            ("MERGE_TRANSFER_MAX_RETRIES", "2"),
            ("MERGE_TRANSFER_RETRY_BASE_MS", "100"),
            ("MERGE_TRANSFER_RETRY_CAP_MS", "400"),
            ("MERGE_TRANSFER_MESSAGE_TIMEOUT_MS", "750"),
            ("MERGE_REDRIVE_INTERVAL_MS", "5000"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.person_merge_events_topic, "pme_test");
        assert_eq!(config.cohort_merge_state_transfer_topic, "transfer_test");
        assert_eq!(config.kafka_merge_consumer_group, "merges-test");
        assert_eq!(config.kafka_merge_apply_consumer_group, "apply-test");
        assert_eq!(
            config.transfer_retry_policy(),
            TransferRetryPolicy {
                max_retries: 2,
                base: Duration::from_millis(100),
                cap: Duration::from_millis(400),
            },
        );
        assert_eq!(config.merge_redrive_interval(), Duration::from_millis(5000));
        assert_eq!(config.merge_transfer_message_timeout_ms, 750);
        assert_eq!(
            config
                .build_transfer_kafka_config()
                .kafka_message_timeout_ms,
            750,
        );
    }

    #[test]
    fn follower_config_hard_codes_earliest_regardless_of_the_events_reset() {
        let mut config = test_config();
        config.kafka_consumer_offset_reset = "latest".to_string();
        let client = config.follower_client_config("cohort-stream-merges");
        assert_eq!(client.get("auto.offset.reset"), Some("earliest"));
        assert_eq!(client.get("group.id"), Some("cohort-stream-merges"));
        assert_eq!(client.get("enable.auto.commit"), Some("false"));
        assert_eq!(client.get("enable.auto.offset.store"), Some("false"));
        assert_eq!(client.get("bootstrap.servers"), Some("localhost:9092"));
    }

    #[test]
    fn follower_config_never_joins_the_group_protocol() {
        let mut config = test_config();
        config.pod_hostname = Some("cohort-stream-processor-2".to_string());
        let client = config.follower_client_config("cohort-stream-merge-apply");
        assert_eq!(client.get("partition.assignment.strategy"), None);
        assert_eq!(client.get("group.instance.id"), None);
        assert_eq!(client.get("client.id"), Some("cohort-stream-processor-2"));
    }

    #[test]
    fn follower_config_sets_tls_keys_only_when_enabled() {
        let mut config = test_config();
        assert_eq!(
            config.follower_client_config("g").get("security.protocol"),
            None,
        );
        config.kafka_tls = true;
        assert_eq!(
            config.follower_client_config("g").get("security.protocol"),
            Some("ssl"),
        );
    }

    #[test]
    fn build_kafka_config_pins_the_murmur2_partitioner() {
        let kafka = test_config().build_kafka_config();
        assert_eq!(
            kafka.kafka_producer_partitioner.as_deref(),
            Some("murmur2_random"),
        );
        assert_eq!(kafka.kafka_compression_codec, "none");
        assert_eq!(kafka.kafka_hosts, "localhost:9092");
    }
}
