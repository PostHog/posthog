use std::fs;
use std::net::SocketAddr;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "127.0.0.1:50053")]
    pub grpc_address: SocketAddr,

    /// Per-partition person-cache capacity in bytes. Entries are weighed
    /// by their approximate serialized size, so this bounds memory, not
    /// entry count. Sized against full ownership: a lone survivor owns
    /// every partition, so the worst-case cache footprint is this value
    /// times the partition count — 16 MiB × 16 partitions = 256 MiB —
    /// and in-memory size can run a small multiple of serialized weight
    /// for key-dense documents.
    #[envconfig(default = "16777216")]
    pub cache_memory_capacity_bytes: usize,

    /// Broker-enforced epoch fencing: the changelog is produced through
    /// per-partition transactional producers, so a new owner's
    /// acquisition fences every predecessor at the broker. Off by
    /// default while the latency cost is being measured.
    #[envconfig(default = "false")]
    pub kafka_transactional_fencing: bool,

    /// How long a fencing transaction window admits joining writes
    /// before committing. Amortizes the commit round trip across
    /// concurrent same-partition writes.
    #[envconfig(default = "5")]
    pub fencing_window_ms: u64,

    /// Timeout for transactional init (fencing acquisition) and
    /// commit/abort operations.
    #[envconfig(default = "0")]
    pub fencing_txn_timeout_ms: u64,

    /// `message.timeout.ms` for the fenced changelog producer only. It is
    /// separate from the shared producer's because a fenced write's total
    /// must fit inside the lease self-fence runway — see
    /// [`Config::validate_fencing_timescales`].
    #[envconfig(default = "0")]
    pub fencing_message_timeout_ms: u32,

    #[envconfig(default = "9102")]
    pub metrics_port: u16,

    /// Maximum concurrent partition warms. Warms are broker-bound reads
    /// on MSK, so this can sit well above the S3-era default of 4.
    #[envconfig(default = "8")]
    pub warm_concurrency: usize,

    // ── gRPC server ──────────────────────────────────────────────
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

    /// Maximum age of a gRPC server connection before it is gracefully
    /// closed (GOAWAY), guarding against half-dead long-lived connections.
    /// 0 = disabled (connections live indefinitely).
    #[envconfig(default = "300")]
    pub grpc_max_connection_age_secs: u64,

    /// Maximum concurrent in-flight gRPC requests before the server sheds
    /// load with RESOURCE_EXHAUSTED so the router retries on another pod.
    /// 0 = disabled.
    #[envconfig(default = "0")]
    pub max_concurrent_requests: usize,

    // ── Response compression ─────────────────────────────────────
    /// When true, gzip-compress responses for clients that advertise gzip
    /// in `grpc-accept-encoding`. Compression runs on a blocking thread
    /// pool instead of the tokio runtime.
    #[envconfig(default = "false")]
    pub gzip_response_compression: bool,

    /// Gzip compression level (1–9). Lower is faster, higher compresses more.
    #[envconfig(default = "6")]
    pub gzip_compression_level: u32,

    /// Minimum response payload size in bytes to compress. Payloads smaller
    /// than this pass through uncompressed.
    #[envconfig(default = "256")]
    pub gzip_min_payload_size: usize,

    /// Log a warning when a response exceeds this size in bytes, even
    /// for uncompressed passthrough. 0 = disabled. Default 4 MiB.
    #[envconfig(default = "4194304")]
    pub gzip_max_response_size: usize,

    /// When true, responses exceeding `gzip_max_response_size` are rejected
    /// with RESOURCE_EXHAUSTED; when false, the oversized
    /// response is delivered normally (monitor mode).
    #[envconfig(default = "false")]
    pub gzip_max_response_size_enforce: bool,

    // ── Kafka durability ─────────────────────────────────────────
    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "personhog_updates")]
    pub kafka_person_state_topic: String,

    // ── Warming ──────────────────────────────────────────────────
    /// Consumer group name used by the writer pod. The leader queries this
    /// group's committed offsets during warming: any Kafka message at or
    /// after the writer's committed offset has not yet been persisted to PG,
    /// so it must live in the leader's cache to avoid stale PG fallback
    /// reads.
    #[envconfig(default = "personhog-writer")]
    pub writer_consumer_group: String,

    /// How many offsets to rewind past the writer's committed offset when
    /// warming. Pure safety margin — any non-negative value is correct, but
    /// a larger value is more forgiving of momentary races between the
    /// writer's commit and our observation of it. Bounded above by Kafka's
    /// earliest available offset.
    #[envconfig(default = "1000")]
    pub warm_lookback_offsets: i64,

    /// Timeout for the OffsetFetch round-trip that asks the writer's
    /// consumer group for its committed offset.
    #[envconfig(default = "5")]
    pub warm_committed_offsets_timeout_secs: u64,

    /// Timeout for the per-partition `fetch_watermarks` metadata call.
    #[envconfig(default = "5")]
    pub warm_fetch_watermarks_timeout_secs: u64,

    /// Per-message receive timeout while consuming the warming range. If
    /// hit, warming aborts with the offsets seen so far so the partition
    /// can be retried fresh.
    #[envconfig(default = "10")]
    pub warm_recv_timeout_secs: u64,

    /// Maximum attempts for retryable warming metadata calls
    /// (committed-offset query, fetch-watermarks).
    #[envconfig(default = "3")]
    pub warm_retry_max_attempts: u32,

    /// Initial backoff between warming-step retries; doubles each attempt
    /// up to `warm_retry_max_backoff_ms`.
    #[envconfig(default = "500")]
    pub warm_retry_initial_backoff_ms: u64,

    /// Cap on the exponential backoff between warming-step retries.
    #[envconfig(default = "5000")]
    pub warm_retry_max_backoff_ms: u64,

    // ── Property size admission ──────────────────────────────────
    /// Ceiling for a person's properties, measured exactly as the
    /// `check_properties_size` constraint on `posthog_person` measures it:
    /// `pg_column_size(properties)`, the JSONB binary size. An update
    /// that would newly push a within-limit row over this is rejected; a
    /// row already over it (predating the constraint, or from another
    /// writer) is remediated by trimming to the target below, discarding
    /// the triggering update — mirroring the Node pipeline's policy. So
    /// every acked record is applyable by the writer verbatim: the cache,
    /// the changelog, and Postgres can never disagree about an acked row.
    #[envconfig(default = "655360")]
    pub properties_size_threshold: usize,

    /// Size to trim already-oversized properties down to during
    /// remediation, comfortably below the threshold so remediated rows
    /// keep headroom under the constraint.
    #[envconfig(default = "524288")]
    pub properties_trim_target: usize,

    /// Topic for in-product ingestion warnings emitted when admission
    /// trims or rejects an update.
    #[envconfig(default = "clickhouse_ingestion_warnings")]
    pub ingestion_warnings_topic: String,

    // ── Dirty index / changelog recovery ─────────────────────────
    /// How often to poll the writer's committed offsets and prune dirty
    /// index marks the writer has applied to PG. A tick costs one batched
    /// OffsetFetch plus work proportional to the marks actually reclaimed
    /// (the index is never scanned), so a short interval is cheap — and it
    /// bounds how long an applied-but-unpruned mark keeps sending reads to
    /// the changelog for state PG already has.
    #[envconfig(default = "1")]
    pub dirty_index_prune_interval_secs: u64,

    /// Overall deadline for recovering one evicted dirty person from the
    /// changelog, including transient-failure retries. A point read that
    /// hasn't returned in a few seconds isn't going to, and each recovery
    /// occupies a pooled consumer for its whole duration — a long deadline
    /// amplifies a broker blip into pool exhaustion.
    #[envconfig(default = "5")]
    pub recovery_recv_timeout_secs: u64,

    /// Number of pooled changelog-recovery consumers, bounding concurrent
    /// recoveries the way a DB connection pool bounds queries. Each is a
    /// full Kafka client (its own connections and background threads), but
    /// even 16 is fewer than the per-partition consumers this pool
    /// replaced. Under a benchmarked writer outage a pool of 4 queued
    /// recoveries for ~10ms on average and tripled write p99; 16 zeroed
    /// the queueing. The `personhog_leader_recovery_pool_wait_ms`
    /// histogram shows when this is undersized.
    #[envconfig(default = "16")]
    pub recovery_pool_size: usize,

    /// Soft bound on dirty index entries (~100 bytes each). The index
    /// grows one mark per unique person written since the writer's
    /// committed offset, so this bound is the memory runway a writer
    /// outage gets before new-person writes shed with RESOURCE_EXHAUSTED.
    /// The default (~1 GB worst case) buys hours at heavy churn.
    #[envconfig(default = "10000000")]
    pub dirty_index_max_entries: usize,

    // ── PG fallback ───────────────────────────────────────────────
    /// Postgres URL for cache miss fallback. If empty, cache misses
    /// return NotFound without querying PG. Must point at the primary:
    /// the dirty index prunes a mark as soon as the writer's committed
    /// offset shows the primary has the row, so reading an async replica
    /// here would serve stale rows for unmarked persons and silently
    /// break read-your-write. Leader reads are strong reads.
    #[envconfig(default = "")]
    pub fallback_database_url: String,

    /// Table the fallback reads. Must be the table the writer maintains
    /// (its PG_TARGET_TABLE): the dirty index treats an unmarked person's
    /// PG row as current, which is only true of the writer's own target.
    /// Prod pairs posthog_person on both sides; the dev validation stack
    /// pairs personhog_person_tmp on both — flip them together at cutover.
    #[envconfig(default = "posthog_person")]
    pub fallback_table: String,

    #[envconfig(default = "5")]
    pub fallback_pg_max_connections: u32,

    /// Keep at least this many connections warm so the first cache-miss
    /// after a quiet period doesn't pay the TCP+auth handshake tax.
    #[envconfig(default = "1")]
    pub fallback_pg_min_connections: u32,

    // ── etcd coordination ────────────────────────────────────────
    #[envconfig(default = "http://localhost:2379")]
    pub etcd_endpoints: String,

    #[envconfig(default = "/personhog/")]
    pub etcd_prefix: String,

    /// Pod name for etcd registration (typically set from K8s downward API)
    #[envconfig(default = "leader-0")]
    pub pod_name: String,

    /// Pod IP from the K8s downward API (`status.podIP`), injected by the
    /// chart. Used to derive the advertised gRPC address when binding a
    /// wildcard. Unset in local runs, which bind a concrete address.
    #[envconfig(default = "")]
    pub pod_ip: String,

    /// Enable K8s awareness: at startup the leader discovers its owning
    /// controller (Deployment) and generation (pod-template-hash) and
    /// registers them, so the coordinator can steer placement away from
    /// old-generation pods during rollouts instead of handing partitions
    /// to pods that are about to be replaced. Requires RBAC to read
    /// pods, replicasets, and deployments in the pod's namespace.
    #[envconfig(default = "false")]
    pub k8s_awareness_enabled: bool,

    /// Kubernetes namespace for controller discovery. If empty,
    /// auto-reads from the service account mount.
    #[envconfig(default = "")]
    pub k8s_namespace: String,

    #[envconfig(default = "30")]
    pub lease_ttl: i64,

    #[envconfig(default = "10")]
    pub heartbeat_interval_secs: u64,
}

/// A fenced write must resolve inside the runway the lease keepalive
/// reserves for self-fencing (a third of the TTL). The bound is on the
/// *queued* write, not the lucky one: an arrival can park behind a
/// window that is already committing, so it pays that window's send and
/// commit before its own — hence the factor of two below.
///
/// A commit may also be re-attempted, and the shares are sized so that
/// every attempt the code will make still fits. The alternative was a
/// bound that quietly assumed a single attempt while the retry loop
/// spent three times it: an assertion the runway could not honour is
/// worse than a tighter timeout, because the whole point of deriving
/// these from the lease is that a write cannot outlive the fence that
/// ends its session.
///
/// librdkafka additionally requires `message.timeout.ms <= transaction
/// .timeout.ms`, and rejects a `transaction.timeout.ms` under a second.
/// Deriving both from the runway satisfies every relation by
/// construction wherever the lease TTL leaves room, and
/// [`Config::validate_fencing_timescales`] refuses the configurations
/// where it does not.
const FENCING_MESSAGE_SHARE: u32 = 2;
const FENCING_TXN_SHARE: u32 = 4;
const FENCING_SHARE_BASE: u32 = 10;

/// How many times a window's commit is attempted in total, counting the
/// first. The shares above are sized around this number, so changing one
/// without the other breaks the runway bound.
pub const FENCING_COMMIT_ATTEMPTS: u32 = 2;

/// librdkafka's documented minimum for `transaction.timeout.ms`.
const MIN_TXN_TIMEOUT: Duration = Duration::from_millis(1000);
/// A floor for the send timeout; zero means *no timeout* to librdkafka,
/// the opposite of what this bound exists to express.
const MIN_MESSAGE_TIMEOUT: Duration = Duration::from_millis(250);

impl Config {
    /// The runway the keepalive reserves for the local fence: it
    /// declares lease loss after two thirds of the TTL, leaving the
    /// final third for the fence to land before the coordinator can
    /// treat the lease as expired.
    pub fn lease_fence_runway(&self) -> Duration {
        Duration::from_millis((self.lease_ttl.max(0) as u64).saturating_mul(1000) / 3)
    }

    /// The budget one write may spend, derived so that a write queued
    /// behind another still finishes inside the runway.
    fn fencing_budget(&self) -> Duration {
        self.lease_fence_runway()
            .saturating_sub(Duration::from_millis(self.fencing_window_ms))
            / 2
    }

    /// How long a fenced send may take.
    pub fn fencing_message_timeout(&self) -> Duration {
        if self.fencing_message_timeout_ms > 0 {
            return Duration::from_millis(u64::from(self.fencing_message_timeout_ms));
        }
        (self.fencing_budget() * FENCING_MESSAGE_SHARE / FENCING_SHARE_BASE)
            .max(MIN_MESSAGE_TIMEOUT)
    }

    /// How long a transaction init, commit, or abort may take.
    pub fn fencing_txn_timeout(&self) -> Duration {
        if self.fencing_txn_timeout_ms > 0 {
            return Duration::from_millis(self.fencing_txn_timeout_ms);
        }
        (self.fencing_budget() * FENCING_TXN_SHARE / FENCING_SHARE_BASE).max(MIN_TXN_TIMEOUT)
    }

    /// How long the broker may hold one of this pod's transactions open
    /// before abandoning it.
    ///
    /// A window lives from `begin_transaction` through its admission
    /// interval, its sends, and its commit, so the broker's patience has
    /// to cover all three — bounding it by the commit alone would let the
    /// broker abort a window this pod is still legitimately filling, and
    /// the resulting epoch bump reads exactly like a fence from a real
    /// successor.
    pub fn fencing_broker_txn_timeout(&self) -> Duration {
        Duration::from_millis(self.fencing_window_ms)
            + self.fencing_message_timeout()
            + self.fencing_txn_timeout()
    }

    /// Every relation the fenced produce path depends on, checked at
    /// startup: the derivation satisfies them wherever the lease TTL
    /// leaves room, and an operator can override either knob.
    pub fn validate_fencing_timescales(&self) -> Result<(), String> {
        if !self.kafka_transactional_fencing {
            return Ok(());
        }
        let (message, txn, runway, window) = (
            self.fencing_message_timeout(),
            self.fencing_txn_timeout(),
            self.lease_fence_runway(),
            Duration::from_millis(self.fencing_window_ms),
        );
        if txn < MIN_TXN_TIMEOUT {
            return Err(format!(
                "fencing transaction timeout ({txn:?}) is below librdkafka's minimum \
                 ({MIN_TXN_TIMEOUT:?}); the producer would not start"
            ));
        }
        if message < MIN_MESSAGE_TIMEOUT {
            return Err(format!(
                "fencing message timeout ({message:?}) is below {MIN_MESSAGE_TIMEOUT:?}; \
                 zero means no timeout at all to librdkafka"
            ));
        }
        if message > txn {
            return Err(format!(
                "fencing message timeout ({message:?}) exceeds the transaction timeout \
                 ({txn:?}); librdkafka rejects the producer outright"
            ));
        }
        // A write parked behind a committing window pays that window's
        // send and commit before its own, so the runway has to cover
        // two — each of them including every commit attempt the code
        // will make, not just the first.
        let queued_worst_case = window + (message + txn * FENCING_COMMIT_ATTEMPTS) * 2;
        if queued_worst_case > runway {
            return Err(format!(
                "a fenced write queued behind another can take {queued_worst_case:?} \
                 (window {window:?} + 2 × (send {message:?} + {FENCING_COMMIT_ATTEMPTS} × commit \
                 {txn:?})), longer than the lease self-fence runway ({runway:?} = LEASE_TTL \
                 {}s / 3); raise LEASE_TTL or lower the fencing timeouts",
                self.lease_ttl,
            ));
        }
        Ok(())
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

    pub fn etcd_endpoint_list(&self) -> Vec<String> {
        self.etcd_endpoints
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    pub fn heartbeat_interval(&self) -> Duration {
        Duration::from_secs(self.heartbeat_interval_secs)
    }

    /// Resolve the K8s namespace from config or the service account mount.
    pub fn resolve_k8s_namespace(&self) -> Result<String, String> {
        if !self.k8s_namespace.is_empty() {
            return Ok(self.k8s_namespace.clone());
        }
        fs::read_to_string("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
            .map(|s| s.trim().to_string())
            .map_err(|e| {
                format!("k8s_namespace not set and failed to read from service account: {e}")
            })
    }
}

/// Derive the `host:port` this leader should advertise for routing.
///
/// The advertised port is always the serving port (taken from the bind
/// address), so it cannot drift from reality. The host is the bind host
/// when it is concrete (local runs bind `127.0.0.1:<port>`), or POD_IP
/// when binding a wildcard (deployments bind `0.0.0.0`). Wildcard with no
/// POD_IP fails closed: a leader that cannot say where it is reachable
/// must not register and claim partitions.
pub fn derive_advertise_address(
    grpc_address: &std::net::SocketAddr,
    pod_ip: &str,
) -> Result<String, String> {
    if !grpc_address.ip().is_unspecified() {
        return Ok(grpc_address.to_string());
    }
    if pod_ip.is_empty() {
        return Err(format!(
            "cannot derive an advertise address: GRPC_ADDRESS binds the wildcard \
             {grpc_address} and POD_IP is not set — routers would have nowhere to dial"
        ));
    }
    Ok(format!("{pod_ip}:{}", grpc_address.port()))
}

#[cfg(test)]
mod tests {
    use super::derive_advertise_address;

    #[test]
    fn advertise_address_prefers_concrete_bind_and_requires_pod_ip_for_wildcards() {
        let concrete = "127.0.0.1:50060".parse().unwrap();
        assert_eq!(
            derive_advertise_address(&concrete, "").unwrap(),
            "127.0.0.1:50060"
        );

        let wildcard = "0.0.0.0:50053".parse().unwrap();
        assert_eq!(
            derive_advertise_address(&wildcard, "10.1.2.3").unwrap(),
            "10.1.2.3:50053"
        );
        assert!(derive_advertise_address(&wildcard, "").is_err());

        let wildcard6 = "[::]:50053".parse().unwrap();
        assert!(derive_advertise_address(&wildcard6, "").is_err());
    }
}

#[cfg(test)]
mod fencing_timescale_tests {
    use super::*;

    fn fenced(lease_ttl: i64) -> Config {
        let mut config = Config::init_from_env().expect("defaults");
        config.kafka_transactional_fencing = true;
        config.lease_ttl = lease_ttl;
        config.fencing_txn_timeout_ms = 0;
        config.fencing_message_timeout_ms = 0;
        config
    }

    /// At any lease TTL the derivation must either satisfy every
    /// relation or be rejected — never produce a config that starts and
    /// then violates the runway, and never one librdkafka refuses.
    #[test]
    fn derived_timeouts_are_either_valid_or_rejected() {
        for lease_ttl in [0, 1, 5, 10, 30, 60, 300] {
            let config = fenced(lease_ttl);
            if config.validate_fencing_timescales().is_ok() {
                let (message, txn) = (
                    config.fencing_message_timeout(),
                    config.fencing_txn_timeout(),
                );
                assert!(txn >= MIN_TXN_TIMEOUT, "LEASE_TTL={lease_ttl}");
                assert!(message >= MIN_MESSAGE_TIMEOUT, "LEASE_TTL={lease_ttl}");
                assert!(message <= txn, "LEASE_TTL={lease_ttl}");
                // Mirrors the production bound, retries included: a
                // check that models fewer attempts than the code makes
                // would accept exactly the configurations that break it.
                let queued = Duration::from_millis(config.fencing_window_ms)
                    + (message + txn * FENCING_COMMIT_ATTEMPTS) * 2;
                assert!(
                    queued <= config.lease_fence_runway(),
                    "LEASE_TTL={lease_ttl}: queued worst case {queued:?} exceeds runway"
                );
            }
        }
    }

    /// The retry budget and the timeout shares are one decision split
    /// across two constants. Raising the attempt count without shrinking
    /// the shares puts the code back outside the runway it validates
    /// against — silently, because every existing test would still pass.
    #[test]
    fn the_production_ttl_affords_every_commit_attempt() {
        let config = fenced(30);
        let (message, txn, runway, window) = (
            config.fencing_message_timeout(),
            config.fencing_txn_timeout(),
            config.lease_fence_runway(),
            Duration::from_millis(config.fencing_window_ms),
        );
        let queued = window + (message + txn * FENCING_COMMIT_ATTEMPTS) * 2;
        assert!(
            queued <= runway,
            "{FENCING_COMMIT_ATTEMPTS} commit attempts need {queued:?}, runway is {runway:?}: \
             lower FENCING_TXN_SHARE / FENCING_MESSAGE_SHARE, or lower the attempt count"
        );
        // And it must be the attempts that are tight, not the shares
        // being trivially small: a budget that fits ten attempts would
        // mean the timeouts had collapsed toward their floors.
        let one_more = window + (message + txn * (FENCING_COMMIT_ATTEMPTS + 1)) * 2;
        assert!(
            one_more > runway,
            "the shares leave room for more attempts than are configured; raise \
             FENCING_COMMIT_ATTEMPTS or the shares rather than leaving runway unused"
        );
    }

    /// The production lease TTL must actually be usable with fencing on,
    /// or the flag could never be enabled.
    #[test]
    fn the_production_lease_ttl_supports_fencing() {
        fenced(30)
            .validate_fencing_timescales()
            .expect("LEASE_TTL=30 must support fencing with derived timeouts");
    }

    #[test]
    fn a_lease_ttl_too_short_for_fencing_is_rejected() {
        assert!(fenced(5).validate_fencing_timescales().is_err());
    }

    #[test]
    fn an_override_that_can_outlive_the_fence_is_rejected() {
        let mut config = fenced(30);
        config.fencing_txn_timeout_ms = 60_000;
        assert!(config.validate_fencing_timescales().is_err());
    }

    #[test]
    fn an_override_librdkafka_would_reject_is_caught() {
        let mut config = fenced(30);
        config.fencing_txn_timeout_ms = 1_000;
        config.fencing_message_timeout_ms = 2_000;
        let err = config
            .validate_fencing_timescales()
            .expect_err("must reject");
        assert!(err.contains("librdkafka"), "got: {err}");
    }
}
