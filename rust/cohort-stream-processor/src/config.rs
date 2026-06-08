//! Service configuration, loaded from environment variables via `envconfig`.

use std::collections::HashSet;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;

use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use rdkafka::ClientConfig;

use crate::store::StoreConfig;

const POOL_NAME: &str = "posthog_cohort";

/// Which teams the realtime-cohort filter catalog is scoped to, parsed from
/// `REALTIME_COHORT_TEAM_ALLOWLIST`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TeamAllowlist {
    All,
    Only(HashSet<i32>),
}

impl TeamAllowlist {
    /// Whether `team_id` is in scope.
    pub fn includes(&self, team_id: i32) -> bool {
        match self {
            TeamAllowlist::All => true,
            TeamAllowlist::Only(ids) => ids.contains(&team_id),
        }
    }
}

impl FromStr for TeamAllowlist {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let s = s.trim();
        // envconfig's `default` only covers an *unset* var; a set-but-empty value must still mean
        // "no gate", never "gate everything".
        if s.is_empty() || s.eq_ignore_ascii_case("all") || s == "*" {
            return Ok(TeamAllowlist::All);
        }
        if s.eq_ignore_ascii_case("none") {
            return Ok(TeamAllowlist::Only(HashSet::new()));
        }

        let mut ids = HashSet::new();
        for part in s.split(',').map(str::trim).filter(|p| !p.is_empty()) {
            match part.split_once(':') {
                Some((start, end)) => {
                    let start: i32 = start
                        .trim()
                        .parse()
                        .map_err(|e| format!("invalid range start in '{part}': {e}"))?;
                    let end: i32 = end
                        .trim()
                        .parse()
                        .map_err(|e| format!("invalid range end in '{part}': {e}"))?;
                    if end < start {
                        return Err(format!("invalid range '{part}': end < start"));
                    }
                    ids.extend(start..=end);
                }
                None => {
                    let id: i32 = part
                        .parse()
                        .map_err(|e| format!("invalid team id '{part}': {e}"))?;
                    ids.insert(id);
                }
            }
        }
        Ok(TeamAllowlist::Only(ids))
    }
}

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

    /// Teams the filter catalog is scoped to. Defaults to team 2 (the parity baseline's gate); set
    /// `all` to disable the gate. See [`TeamAllowlist`].
    #[envconfig(from = "REALTIME_COHORT_TEAM_ALLOWLIST", default = "2")]
    pub team_allowlist: TeamAllowlist,

    // ── Partition routing ─────────────────────────────────────────────────
    /// Bounded buffer (in sub-batches) per per-partition worker channel: the backpressure knob.
    /// Routing to a partition this far behind blocks rather than growing memory unbounded. Per
    /// active partition, so peak in-flight scales with the assigned partition count.
    #[envconfig(default = "1024")]
    pub partition_channel_buffer: usize,

    // ── Kafka (shared) ─────────────────────────────────────────────────────
    #[envconfig(default = "localhost:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "")]
    pub kafka_client_id: String,

    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    // ── Consumer (input: cohort_stream_events) ─────────────────────────────
    /// The hot-path input topic. Named specifically (not `input_topic`) so sibling topics can be
    /// added without ambiguity.
    #[envconfig(default = "cohort_stream_events")]
    pub cohort_stream_events_topic: String,

    #[envconfig(default = "cohort-stream-processor")]
    pub kafka_consumer_group: String,

    /// Start at the tail, not the topic's retention: the parity window runs forward from start.
    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    /// How long the broker waits for heartbeats before declaring this consumer dead. With static
    /// membership the broker holds this consumer's partitions for this long after it disappears, so a
    /// restart within the window reclaims them with no rebalance.
    #[envconfig(default = "60000")]
    pub kafka_session_timeout_ms: u64,

    // ── Static group membership (sticky partitions across restarts) ────────
    /// Stable per-pod identity for `group.instance.id` + `client.id`, enabling static membership so a
    /// restart reclaims its exact partitions with no rebalance. Read from `POD_NAME`, else `HOSTNAME`
    /// (which K8s sets to the pod name). Absent → no static membership, just cooperative rebalancing.
    /// See [`Config::pod_identity`].
    #[envconfig(from = "POD_NAME")]
    pub pod_name: Option<String>,

    #[envconfig(from = "HOSTNAME")]
    pub pod_hostname: Option<String>,

    // ── Producer (output: cohort_membership_changed_shadow) ────────────────
    /// The shadow output topic, distinct from the legacy `cohort_membership_changed` so the new
    /// pipeline can run side-by-side for parity.
    #[envconfig(default = "cohort_membership_changed_shadow")]
    pub cohort_membership_changed_topic: String,

    /// **Load-bearing**: `murmur2_random` co-partitions a `person_id` key identically to the
    /// Node/Python producers, so the shadow topic partitions the same way the legacy producer does.
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

    // ── Sweep (time-driven eviction) ───────────────────────────────────────
    /// How often the sweep fires to evict state whose eviction deadline has passed.
    #[envconfig(default = "30000")]
    pub sweep_interval_ms: u64,

    /// Grace period added to every eviction deadline before the sweep acts. Set high enough to
    /// absorb consumer-lag spikes during deploys/rebalances, so a late event still lands in its
    /// bucket before the bucket is evicted. The sweep evicts a key only once its
    /// `deadline + safety_margin < now` — i.e. the deadline is strictly before `now − safety_margin`.
    #[envconfig(default = "300000")]
    pub sweep_safety_margin_ms: u64,

    // ── State store (RocksDB) ──────────────────────────────────────────────
    /// On-disk path for the per-process RocksDB state store.
    #[envconfig(default = "cohort-store")]
    pub store_path: String,

    /// Destroy any existing store at `store_path` before opening, for a guaranteed stale-free start
    /// regardless of what disk the deployment mounts: re-acquiring a partition must never serve stale
    /// per-partition state left by a previous owner. See
    /// [`crate::store::StoreConfig::wipe_on_start`].
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

    /// Pool config for the catalog reader: small, since the only query is the periodic refresh.
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

    /// How often the time-driven eviction sweep fires.
    pub fn sweep_interval(&self) -> Duration {
        Duration::from_millis(self.sweep_interval_ms)
    }

    /// The grace period subtracted from `now` before a deadline is considered due (see
    /// [`sweep_safety_margin_ms`](Self::sweep_safety_margin_ms)).
    pub fn sweep_safety_margin(&self) -> Duration {
        Duration::from_millis(self.sweep_safety_margin_ms)
    }

    /// RocksDB settings for the state store. Only the path and the wipe-on-start flag are
    /// configurable; the rest use defaults.
    pub fn store_config(&self) -> StoreConfig {
        StoreConfig {
            path: PathBuf::from(&self.store_path),
            wipe_on_start: self.wipe_store_on_start,
            ..StoreConfig::default()
        }
    }

    /// Stable per-pod identity for static group membership, `POD_NAME` preferred over `HOSTNAME`.
    /// `None` (or a blank value) leaves static membership off, so the consumer joins as a dynamic
    /// member and only cooperative-sticky's incremental rebalancing applies.
    pub fn pod_identity(&self) -> Option<&str> {
        [self.pod_name.as_deref(), self.pod_hostname.as_deref()]
            .into_iter()
            .flatten()
            .find(|id| !id.is_empty())
    }

    /// Build the `rdkafka` client config for the `cohort_stream_events` group consumer.
    ///
    /// Auto-commit and auto-offset-store are **off**: the consume loop marks offsets only once a
    /// sub-batch is routed, and the commit tick turns the
    /// [`OffsetTracker`](crate::partitions::OffsetTracker) snapshot into the committed
    /// `TopicPartitionList`.
    ///
    /// `cooperative-sticky` + static membership are load-bearing for a stateful, partition-affined
    /// consumer: a membership change revokes only the partitions that actually move, and a pod that
    /// restarts within `session.timeout.ms` reclaims its exact partitions with no rebalance at all.
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

        // Static membership: a stable id lets the broker hold this pod's partitions across a quick
        // restart. Sets `client.id` too; an explicit `kafka_client_id` overrides it below.
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

    /// Kafka connection + producer config for the `cohort_membership_changed_shadow` producer. The
    /// partitioner is always set — `murmur2_random` is load-bearing for cross-runtime co-partitioning.
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
            team_allowlist: TeamAllowlist::All,
            partition_channel_buffer: 1024,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_id: String::new(),
            kafka_client_rack: String::new(),
            cohort_stream_events_topic: "cohort_stream_events".to_string(),
            kafka_consumer_group: "cohort-stream-processor".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
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
        // No pod identity → dynamic membership, no instance id.
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
    fn build_kafka_config_pins_the_murmur2_partitioner() {
        let kafka = test_config().build_kafka_config();
        assert_eq!(
            kafka.kafka_producer_partitioner.as_deref(),
            Some("murmur2_random"),
        );
        assert_eq!(kafka.kafka_compression_codec, "none");
        assert_eq!(kafka.kafka_hosts, "localhost:9092");
    }

    #[test]
    fn team_allowlist_blank_and_keywords_disable_or_clear_the_gate() {
        assert_eq!("".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("  ".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("all".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("ALL".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!("*".parse::<TeamAllowlist>().unwrap(), TeamAllowlist::All);
        assert_eq!(
            "none".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::new()),
        );
    }

    #[test]
    fn team_allowlist_parses_lists_and_ranges() {
        assert_eq!(
            "2".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([2])),
        );
        assert_eq!(
            "2, 42 ,7".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([2, 42, 7])),
        );
        assert_eq!(
            "1:3".parse::<TeamAllowlist>().unwrap(),
            TeamAllowlist::Only(HashSet::from([1, 2, 3])),
        );
    }

    #[test]
    fn team_allowlist_rejects_garbage_and_inverted_ranges() {
        assert!("nope".parse::<TeamAllowlist>().is_err());
        assert!("3:1".parse::<TeamAllowlist>().is_err());
        assert!("2,x".parse::<TeamAllowlist>().is_err());
    }

    #[test]
    fn team_allowlist_includes_honours_scope() {
        assert!(TeamAllowlist::All.includes(999));
        let only = TeamAllowlist::Only(HashSet::from([2]));
        assert!(only.includes(2));
        assert!(!only.includes(3));
        assert!(!TeamAllowlist::Only(HashSet::new()).includes(2));
    }
}
