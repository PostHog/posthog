use std::fs;
use std::net::SocketAddr;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use personhog_coordination::authority::AuthorityClock;
use personhog_coordination::pod::{
    PodConfig, DRAIN_SETUP_BOUND, REVOKE_TIMEOUT, SHUTDOWN_FENCE_BOUND,
};

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
    /// before committing, when it does not fill first (see
    /// FENCING_WINDOW_MAX_WRITES). Amortizes the commit round trip
    /// across concurrent same-partition writes.
    #[envconfig(default = "5")]
    pub fencing_window_ms: u64,

    /// Closes a fencing window early once this many writes have joined,
    /// rather than holding it open for the rest of FENCING_WINDOW_MS.
    /// Under a backlog, windows fill and commit at once, so a drain
    /// cycle is bounded by the commit round trip instead of the window;
    /// the window still bounds ack latency at light load. A close
    /// trigger, not a hard cap: writes arriving while the close
    /// propagates still ride the window.
    #[envconfig(default = "32")]
    pub fencing_window_max_writes: usize,

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
    /// load with RESOURCE_EXHAUSTED. That code is terminal end to end —
    /// the router treats a delivered response as an outcome and the
    /// client does not retry it — so this is backpressure to the caller,
    /// not a redirect. 0 = disabled.
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

    /// Bound on the unresolved-version floors, its own knob rather than
    /// borrowing the dirty index's. The two grow under different
    /// failures: dirty marks accumulate whenever the writer lags, floors
    /// only when writes end without an answer — cancellations and
    /// ambiguous commits — which is orders of magnitude rarer. Past the
    /// bound, floors spill to one coarse per-partition value (safety
    /// survives; precision degrades), so this sizes memory, not
    /// correctness. The default is a fraction of the dirty index's.
    #[envconfig(default = "1000000")]
    pub emitted_versions_max_entries: usize,

    /// Hard cap on live lifecycle fences (~100 bytes each). The fence map
    /// grows one entry per person frozen by a lifecycle op and has no
    /// eviction, so this is the memory fuse against a surge of ops from a
    /// huge customer: at the cap, new FencePerson calls shed with
    /// RESOURCE_EXHAUSTED — backpressure the saga's retries absorb —
    /// while re-seals of already-fenced persons and the takeover scan
    /// (marks already live; the freeze must hold) are exempt.
    #[envconfig(default = "250000")]
    pub fence_map_max_entries: usize,

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

    /// Refuse strong reads and fence acquisition once this pod's lease
    /// may have expired, instead of serving until the keepalive notices.
    /// Trades availability during an etcd outage for never answering as
    /// an owner the protocol may already have replaced.
    #[envconfig(default = "false")]
    pub lease_gated_authority: bool,

    #[envconfig(default = "30")]
    pub lease_ttl: i64,

    #[envconfig(default = "10")]
    pub heartbeat_interval_secs: u64,

    // ── Shutdown budgets ─────────────────────────────────────────
    // The lifecycle manager's per-phase windows. Configurable because
    // the terms validated against them — the drain timeout, the
    // heartbeat interval — are, and a fixed ceiling under adjustable
    // terms is a configuration an operator cannot resolve. Their
    // relations are checked by `validate_shutdown_budgets` at startup.
    /// How long the lifecycle manager lets the coordination component
    /// exit gracefully. The pod's whole teardown — drain setup, drain,
    /// fence, keepalive join, revoke — must fit inside it, which
    /// `validate_lease_timescales` enforces.
    #[envconfig(default = "55")]
    pub coordination_graceful_shutdown_secs: u64,

    /// The phase-1 components' shared budget: the gRPC server and the
    /// producer stop in parallel after coordination finishes.
    #[envconfig(default = "15")]
    pub phase1_graceful_shutdown_secs: u64,

    /// Phase 0 (coordination) plus phase 1, with slack. Must stay under
    /// the chart's termination grace period so shutdown concludes
    /// process-side.
    #[envconfig(default = "75")]
    pub global_shutdown_timeout_secs: u64,
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
const FENCING_MESSAGE_SHARE: u32 = 1;
const FENCING_TXN_SHARE: u32 = 3;
const FENCING_SHARE_BASE: u32 = 10;

/// How many times a window's commit is attempted in total, counting the
/// first.
pub const FENCING_COMMIT_ATTEMPTS: u32 = 2;

/// How many times a window's abort is attempted in total.
///
/// One, deliberately. An abort that does not land leaves the producer in
/// a state it cannot begin another transaction from — which is now a
/// condemned fence, given up on the next write and re-taken by the
/// healing pass, whose `init_transactions` aborts the pending
/// transaction at the broker as a side effect. Retrying the abort is
/// therefore a slower, less reliable version of a recovery that already
/// exists, and it is not free: every attempt is bounded by the
/// transaction timeout and has to fit the same runway.
pub const FENCING_ABORT_ATTEMPTS: u32 = 1;

/// Every call bounded by the transaction timeout that one window can
/// make. Both the runway bound and the broker's own patience are sized
/// from this, so the two cannot drift apart.
pub const FENCING_TXN_CALLS: u32 = FENCING_COMMIT_ATTEMPTS + FENCING_ABORT_ATTEMPTS;

/// librdkafka's documented minimum for `transaction.timeout.ms`.
const MIN_TXN_TIMEOUT: Duration = Duration::from_millis(1000);
/// A floor for the send timeout; zero means *no timeout* to librdkafka,
/// the opposite of what this bound exists to express.
const MIN_MESSAGE_TIMEOUT: Duration = Duration::from_millis(250);

/// Apache Kafka's default `transaction.max.timeout.ms`. A producer that
/// asks for longer is refused at `init_transactions` rather than trimmed.
const MAX_BROKER_TXN_TIMEOUT: Duration = Duration::from_secs(900);

impl Config {
    /// The runway the keepalive reserves for the local fence: it
    /// declares lease loss after two thirds of the TTL, leaving the
    /// final third for the fence to land before the coordinator can
    /// treat the lease as expired.
    pub fn lease_fence_runway(&self) -> Duration {
        Duration::from_millis((self.lease_ttl.max(0) as u64).saturating_mul(1000) / 3)
    }

    /// Slack the drain spends outside the writes themselves: the settle
    /// wait that follows `wait_until_empty`, plus one poll interval of
    /// granularity on the wait (the coordination drain polls at 50ms).
    /// Subtracted from the runway before sizing the write budget — sizing
    /// against the full runway left the lease-loss drain oversubscribed
    /// by construction, so worst-case queueing failed the drain and cost
    /// a restart to load rather than to failure.
    fn fencing_drain_slack(&self) -> Duration {
        self.fencing_settle_budget() + Duration::from_millis(50)
    }

    /// The budget one write may spend, derived so that a write queued
    /// behind another — and the settle that follows the queue draining —
    /// still finishes inside the runway.
    fn fencing_budget(&self) -> Duration {
        self.lease_fence_runway()
            .saturating_sub(Duration::from_millis(self.fencing_window_ms))
            .saturating_sub(self.fencing_drain_slack())
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

    /// The producer queue each fenced producer gets, in MiB.
    ///
    /// The shared producer's queue is sized for one client; the fenced
    /// path creates one producer *per owned partition*, so inheriting
    /// that figure multiplies it by the partition count. A lone survivor
    /// owning every partition would be entitled to the whole product,
    /// which for the deployed shape is several gigabytes against a pod
    /// sized for one — a client spreading large property updates across
    /// partitions while Kafka is slow could fill the independent queues
    /// and exhaust the leader.
    ///
    /// So the budget is the aggregate, divided. The floor keeps a
    /// high-partition-count deployment from starving any single producer
    /// below a workable depth; it trades the guarantee for a bound that
    /// is still far under the un-divided figure.
    pub fn fencing_queue_mib(&self, partitions: u32) -> u32 {
        // The floor cannot be unconditional: above roughly fifty
        // partitions it would start multiplying again, and the aggregate
        // this exists to bound would scale with partition count exactly
        // as it did before. So it applies only while it stays inside the
        // aggregate, and past that point the division wins and each
        // producer gets a shallow queue — which is the honest answer for
        // a deployment with more partitions than a producer's worth of
        // memory to give them.
        // No floor. One was tried and was dead code: inside a guard that
        // only admits it when `MIN * partitions <= aggregate`, the
        // division already yields at least `MIN`, so the `max` never
        // fired. Applying it *outside* such a guard is worse — it
        // multiplies back up, which is the defect this division exists to
        // remove. The honest bound is the aggregate, and one MiB is the
        // smallest queue librdkafka will take.
        (self.kafka.kafka_producer_queue_mib / partitions.max(1)).max(1)
    }

    /// The same division for the message-count limit, which bounds the
    /// queue independently of record size.
    pub fn fencing_queue_messages(&self, partitions: u32) -> u32 {
        (self.kafka.kafka_producer_queue_messages / partitions.max(1)).max(1)
    }

    /// How long fence acquisition may take.
    ///
    /// Deliberately not the transaction timeout. That one is sized so
    /// that a *queued write* still resolves inside the lease runway, and
    /// acquisition is neither queued nor a write — it is two broker round
    /// trips, one of which makes the coordinator abort a predecessor's
    /// open transaction. Tying it to the runway meant re-budgeting the
    /// write path silently tightened acquisition, and acquisition happens
    /// fleet-wide during a deploy, which is the worst moment to have
    /// shortened it.
    ///
    /// It still has to fit inside the runway as a whole: a warm that
    /// outlives the lease it is warming for has nothing to serve.
    pub fn fencing_init_timeout(&self) -> Duration {
        const MIN_INIT_TIMEOUT: Duration = Duration::from_secs(2);
        self.fencing_txn_timeout()
            .max(MIN_INIT_TIMEOUT)
            .min(self.lease_fence_runway())
    }

    /// Ceiling on the drain's wait for an open window to commit.
    ///
    /// The wait exists to catch a committer about to fire anyway — it
    /// sleeps for the window, then commits — so a longer budget only
    /// helps when the commit is retrying, which is the case where the
    /// successor's abort is the right answer regardless.
    ///
    /// Absolute rather than derived from the lease, because what it has
    /// to fit inside is absolute: the pre-revoke self-fence allows three
    /// seconds for a whole drain. Bounding it by the broker's own
    /// patience instead would be inert — `fencing_txn_timeout` floors at
    /// a second and the window can make three such calls, so that bound
    /// never falls below four and a half, and every accepted lease would
    /// leave the cap doing all the work. Before the drain slack was paid
    /// out of the write budget it sat at 7.5s at the production lease
    /// (about 6s now), truncating on every shutdown with an open window
    /// and reporting the drain as failed.
    ///
    /// Residual: a `drain_timeout` configured under two seconds shrinks
    /// that allowance below this budget, and the leader cannot see the
    /// coordination-side value to derive against. Truncating is safe —
    /// the wait is best-effort — so the cost is a spurious drain
    /// failure, not a correctness one.
    pub fn fencing_settle_budget(&self) -> Duration {
        Duration::from_secs(2)
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
        // Every transaction-timeout-bounded call the window can make, not
        // just the first: a commit that retries, or a commit followed by
        // an abort, keeps the transaction open for all of them. A bound
        // that covers only one call lets the broker abandon a window this
        // pod is still legitimately working, and that epoch bump is
        // indistinguishable from a real successor's fence — so a
        // retriable blip would read as "this pod's claim is stale" and
        // cost the partition its fence.
        //
        // Half again on top, because the arithmetic is a floor: the
        // window sleep can overshoot and each blocking call waits its
        // turn on the blocking pool.
        let lifetime = Duration::from_millis(self.fencing_window_ms)
            + self.fencing_message_timeout()
            + self.fencing_txn_timeout() * FENCING_TXN_CALLS;
        lifetime + lifetime / 2
    }

    /// The lease relations that hold whether or not fencing is on.
    ///
    /// `PodHandle::new` asserts that the heartbeat fits inside the
    /// keepalive's renewal margin, but it does so several hundred lines
    /// into startup — after etcd, Kafka and the Postgres pool are
    /// established — and its message names the heartbeat rather than the
    /// TTL that decides the margin. Checking it here turns a late panic
    /// into an early refusal that names both.
    pub fn validate_lease_timescales(&self) -> Result<(), String> {
        let margin = AuthorityClock::renewal_margin(self.lease_ttl);
        let heartbeat = self.heartbeat_interval();
        // Zero is under every margin, so the comparison below waves it
        // through — but the keepalive uses this interval as the *timeout*
        // for each renewal round, so a zero one times out instantly,
        // exhausts the margin through its retry pace, and ends the
        // session. The pod then releases every partition and starts over,
        // for as long as it runs, without ever serving or crashing.
        if heartbeat.is_zero() {
            return Err(
                "HEARTBEAT_INTERVAL_SECS must be greater than zero: the keepalive uses it as \
                 the timeout for each renewal round, so a zero interval fences the pod against \
                 healthy etcd in a loop it cannot leave"
                    .to_string(),
            );
        }
        if heartbeat >= margin {
            return Err(format!(
                "HEARTBEAT_INTERVAL_SECS ({heartbeat:?}) must be well under the keepalive \
                 renewal margin ({margin:?} = 2/3 of LEASE_TTL {}s): the sleep between \
                 renewals would exhaust the margin on its own, and the pod would fence \
                 itself against healthy etcd",
                self.lease_ttl,
            ));
        }
        // The pod's graceful exit — drain setup, drain, shutdown-path
        // fence, one keepalive round's join, bounded revoke — has to
        // fit the coordination budget, or the lifecycle manager
        // abandons it mid-teardown while this pod is still the
        // registered owner. The drain term reads the same
        // `base_pod_config` the running pod is built from, so a future
        // knob cannot decouple the validated sum from the deployed one.
        let drain = self.base_pod_config().drain_timeout;
        let teardown =
            DRAIN_SETUP_BOUND + drain + SHUTDOWN_FENCE_BOUND + heartbeat + REVOKE_TIMEOUT;
        let budget = self.coordination_graceful_shutdown();
        if teardown >= budget {
            return Err(format!(
                "the pod's teardown ({teardown:?} = setup {DRAIN_SETUP_BOUND:?} + drain \
                 {drain:?} + fence {SHUTDOWN_FENCE_BOUND:?} + a {heartbeat:?} keepalive join \
                 + revoke {REVOKE_TIMEOUT:?}) must finish inside the coordination \
                 component's {budget:?} graceful shutdown budget; lower \
                 HEARTBEAT_INTERVAL_SECS or raise COORDINATION_GRACEFUL_SHUTDOWN_SECS"
            ));
        }
        Ok(())
    }

    /// The lifecycle manager's phases must fit the window that
    /// supervises them, or its own deadline fires before theirs.
    ///
    /// Checked at startup rather than compile time because the budgets
    /// are configuration: a fixed ceiling under adjustable phase
    /// timings is a configuration an operator cannot resolve.
    pub fn validate_shutdown_budgets(&self) -> Result<(), String> {
        let phases = self.coordination_graceful_shutdown() + self.phase1_graceful_shutdown();
        let global = self.global_shutdown_timeout();
        if phases >= global {
            return Err(format!(
                "the shutdown phases ({phases:?} = a {:?} coordination drain plus a {:?} \
                 server and producer stop) must finish inside the {global:?} global window \
                 with room to spare; raise GLOBAL_SHUTDOWN_TIMEOUT_SECS or lower the phases",
                self.coordination_graceful_shutdown(),
                self.phase1_graceful_shutdown(),
            ));
        }
        Ok(())
    }

    pub fn coordination_graceful_shutdown(&self) -> Duration {
        Duration::from_secs(self.coordination_graceful_shutdown_secs)
    }

    pub fn phase1_graceful_shutdown(&self) -> Duration {
        Duration::from_secs(self.phase1_graceful_shutdown_secs)
    }

    pub fn global_shutdown_timeout(&self) -> Duration {
        Duration::from_secs(self.global_shutdown_timeout_secs)
    }

    /// The coordination-relevant half of the pod's configuration, shared
    /// by `main`'s construction and the teardown validation above so the
    /// two cannot drift: a drain or heartbeat knob added here is summed
    /// by the validation automatically, where one added at the
    /// construction site would be invisible to it.
    pub fn base_pod_config(&self) -> PodConfig {
        PodConfig {
            lease_ttl: self.lease_ttl,
            heartbeat_interval: self.heartbeat_interval(),
            // Zero would park every warm on an unobtainable permit and
            // wedge handoffs; treat it as fully sequential instead.
            warm_concurrency: self.warm_concurrency.max(1),
            ..Default::default()
        }
    }

    /// Every relation the fenced produce path depends on, checked at
    /// startup: the derivation satisfies them wherever the lease TTL
    /// leaves room, and an operator can override either knob.
    pub fn validate_fencing_timescales(&self) -> Result<(), String> {
        if !self.kafka_transactional_fencing {
            return Ok(());
        }
        // Fencing without the lease gate is the combination the e2e
        // zombie scenario breaks: acquisition takes the partition's epoch
        // from whoever holds it, so a pod waking inside its lease window
        // fences the legitimate owner on its way to noticing it is dead.
        // The gate is what gives acquisition the standing to be safe, so
        // the dependency is refused at startup rather than documented.
        if !self.lease_gated_authority {
            return Err(
                "KAFKA_TRANSACTIONAL_FENCING requires LEASE_GATED_AUTHORITY: unless \
                 acquisition is gated on holding the lease, a pod whose lease has lapsed \
                 can take the changelog fence away from the partition's real owner"
                    .to_string(),
            );
        }
        if self.fencing_window_max_writes == 0 {
            return Err(
                "FENCING_WINDOW_MAX_WRITES must be at least 1: zero would close every \
                 window at its first write, which is the per-write-commit shape the \
                 window exists to avoid"
                    .to_string(),
            );
        }
        let (message, txn, runway, window) = (
            self.fencing_message_timeout(),
            self.fencing_txn_timeout(),
            self.lease_fence_runway(),
            Duration::from_millis(self.fencing_window_ms),
        );
        // librdkafka fails `init_transactions` outright when this
        // exceeds the broker's `transaction.max.timeout.ms`, and it does
        // so on every partition, forever, with nothing but a heal-failure
        // counter to say why. The default broker ceiling is fifteen
        // minutes; a lease TTL of an hour or more derives past it.
        let broker_txn = self.fencing_broker_txn_timeout();
        if broker_txn > MAX_BROKER_TXN_TIMEOUT {
            return Err(format!(
                "the derived broker transaction timeout ({broker_txn:?}) exceeds the usual \
                 broker ceiling ({MAX_BROKER_TXN_TIMEOUT:?} = transaction.max.timeout.ms): \
                 init_transactions would fail on every partition; lower LEASE_TTL"
            ));
        }
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
        // Acquisition spends its timeout twice — once on the metadata
        // ping, once on init_transactions — and both have to land inside
        // the runway the keepalive reserves. The queued-write bound below
        // caps the derived value transitively at the defaults, but an
        // override can move the inputs, so the two-call bound is checked
        // by name.
        if self.fencing_init_timeout() * 2 > runway {
            return Err(format!(
                "fencing acquisition spends its timeout ({:?}) on two broker calls, which \
                 does not fit the lease fence runway ({runway:?}); raise LEASE_TTL or lower \
                 the transaction-timeout override",
                self.fencing_init_timeout()
            ));
        }
        // A write parked behind a committing window pays that window's
        // send and commit before its own, so the runway has to cover
        // two — each of them including every commit attempt the code
        // will make, not just the first.
        let queued_worst_case = window + (message + txn * FENCING_TXN_CALLS) * 2;
        let drain_room = runway.saturating_sub(self.fencing_drain_slack());
        if queued_worst_case > drain_room {
            return Err(format!(
                "a fenced write queued behind another can take {queued_worst_case:?} \
                 (window {window:?} + 2 × (send {message:?} + {FENCING_TXN_CALLS} × commit/abort \
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
mod lease_timescale_tests {
    use super::*;

    /// The phase budgets have to fit the window supervising them. This
    /// held at compile time while they were constants; as configuration
    /// it is a startup refusal, and the defaults must still satisfy it.
    #[test]
    fn shutdown_phases_that_overrun_the_global_window_are_refused() {
        let config =
            Config::init_from_hashmap(&std::collections::HashMap::new()).expect("defaults");
        assert!(
            config.validate_shutdown_budgets().is_ok(),
            "the defaults must satisfy their own relations"
        );

        let mut overrun =
            Config::init_from_hashmap(&std::collections::HashMap::new()).expect("defaults");
        overrun.global_shutdown_timeout_secs =
            overrun.coordination_graceful_shutdown_secs + overrun.phase1_graceful_shutdown_secs;
        assert!(
            overrun.validate_shutdown_budgets().is_err(),
            "phases summing to the whole global window leave the manager no slack"
        );
    }

    /// The pod's teardown must fit the coordination component's budget,
    /// and the keepalive join is the one term an operator can move. A
    /// heartbeat the renewal margin accepts can still blow the budget —
    /// that band is exactly what a check on the margin alone missed.
    #[test]
    fn a_teardown_the_shutdown_budget_cannot_fit_is_refused() {
        let mut config =
            Config::init_from_hashmap(&std::collections::HashMap::new()).expect("defaults");
        config.lease_ttl = 30;
        // Inside the 20s renewal margin, so the pair check passes — but
        // setup (5s) + drain (30s) + fence (3s) + a 16s join + revoke
        // (5s) = 59s overruns the 55s budget. Sixteen, not a rounder
        // number, because it discriminates on every term: without the
        // setup bound the sum is 54s, which a broken validation would
        // accept — a 17s join sums to exactly 55s either way and pins
        // nothing about the setup term.
        config.heartbeat_interval_secs = 16;
        assert!(config.validate_lease_timescales().is_err());

        config.heartbeat_interval_secs = 10;
        assert!(
            config.validate_lease_timescales().is_ok(),
            "the default heartbeat must fit the budget"
        );
    }
}

#[cfg(test)]
mod fencing_timescale_tests {
    use super::*;

    /// The envconfig defaults with no environment behind them, so an
    /// ambient variable in a developer's shell cannot change what these
    /// tests assert.
    fn fenced(lease_ttl: i64) -> Config {
        let mut config =
            Config::init_from_hashmap(&std::collections::HashMap::new()).expect("defaults");
        config.kafka_transactional_fencing = true;
        config.lease_gated_authority = true;
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
        // 16 and 20 are the band where the bound's attempt count is the
        // only thing that decides acceptance — without them the sweep
        // cannot tell a two-call model from a three-call one.
        for lease_ttl in [0, 1, 5, 10, 16, 20, 21, 30, 60, 300] {
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
                    + (message + txn * FENCING_TXN_CALLS) * 2;
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
    fn the_production_ttl_affords_every_transaction_call() {
        let config = fenced(30);
        let (message, txn, runway, window) = (
            config.fencing_message_timeout(),
            config.fencing_txn_timeout(),
            config.lease_fence_runway(),
            Duration::from_millis(config.fencing_window_ms),
        );
        let queued = window + (message + txn * FENCING_TXN_CALLS) * 2;
        assert!(
            queued <= runway,
            "{FENCING_TXN_CALLS} transaction calls need {queued:?}, runway is {runway:?}: \
             lower FENCING_TXN_SHARE / FENCING_MESSAGE_SHARE, or lower the attempt counts"
        );
        // And it must be the attempts that are tight, not the shares
        // being trivially small: a budget that fits ten attempts would
        // mean the timeouts had collapsed toward their floors.
        let one_more = window + (message + txn * (FENCING_TXN_CALLS + 1)) * 2;
        assert!(
            one_more > runway,
            "the shares leave room for more attempts than are configured; raise \
             the attempt counts or the shares rather than leaving runway unused"
        );
    }

    /// The gap that made the fencing check misleading: a TTL it accepts
    /// can still be one the pod refuses to start on, and that refusal
    /// arrived hundreds of lines later, blamed the heartbeat, and never
    /// mentioned the TTL that actually decides the margin.
    ///
    /// The fencing floor and the heartbeat happen not to overlap at the
    /// default heartbeat today, so the pairs below raise it — which is
    /// the point: the two checks constrain different things, and nothing
    /// keeps a future change to the timeout shares from moving the
    /// fencing floor back under the heartbeat.
    #[test]
    fn a_lease_ttl_the_heartbeat_cannot_fit_is_refused_up_front() {
        for (lease_ttl, heartbeat_secs) in [(27, 18), (30, 20), (60, 40)] {
            let mut config = fenced(lease_ttl);
            config.heartbeat_interval_secs = heartbeat_secs;
            assert!(
                config.validate_fencing_timescales().is_ok(),
                "LEASE_TTL={lease_ttl} is meant to pass the fencing check"
            );
            let err = config
                .validate_lease_timescales()
                .expect_err("but must not pass the lease check");
            assert!(
                err.contains("LEASE_TTL"),
                "the refusal must name the knob to change, got: {err}"
            );
        }
    }

    /// Zero passes the margin comparison — it is under every margin — but
    /// the keepalive uses the interval as each round's timeout, so it
    /// fences the pod against healthy etcd forever.
    #[test]
    fn a_zero_heartbeat_is_refused() {
        let mut config = fenced(30);
        config.heartbeat_interval_secs = 0;
        let err = config
            .validate_lease_timescales()
            .expect_err("a zero heartbeat must not start");
        assert!(
            err.contains("greater than zero"),
            "the refusal must name the constraint, got: {err}"
        );
    }

    /// And the production pairing must survive it, or the check would
    /// refuse the fleet it was written to protect.
    #[test]
    fn the_production_lease_and_heartbeat_agree() {
        let mut config = fenced(30);
        config.heartbeat_interval_secs = 10;
        config
            .validate_lease_timescales()
            .expect("LEASE_TTL=30 with a 10s heartbeat must start");
    }

    /// The broker's patience has to cover the whole window, not the first
    /// call into it. A bound shorter than the lifetime lets the broker
    /// abandon a window this pod is still working, and that epoch bump
    /// is indistinguishable from a real successor's fence — so a
    /// retriable blip would cost the partition its fence and read as a
    /// stale claim.
    #[test]
    fn the_broker_waits_out_the_whole_window() {
        for lease_ttl in [21, 30, 60, 300] {
            let config = fenced(lease_ttl);
            if config.validate_fencing_timescales().is_err() {
                continue;
            }
            let lifetime = Duration::from_millis(config.fencing_window_ms)
                + config.fencing_message_timeout()
                + config.fencing_txn_timeout() * FENCING_TXN_CALLS;
            assert!(
                config.fencing_broker_txn_timeout() >= lifetime + lifetime / 2,
                "LEASE_TTL={lease_ttl}: broker bound {:?} leaves no slack over the window's \
                 own worst case {lifetime:?} — the sleep overshoots and each blocking call \
                 waits its turn on the pool",
                config.fencing_broker_txn_timeout(),
            );
        }
    }

    /// The fenced path creates one producer per owned partition, so the
    /// shared producer's queue limits are an aggregate to divide rather
    /// than a per-producer figure to copy. Inheriting them let a lone
    /// survivor owning every partition claim the whole product — several
    /// gigabytes on a pod sized for one — which a client can reach by
    /// spreading large property updates across partitions while Kafka is
    /// slow.
    #[test]
    fn fenced_producer_queues_do_not_scale_with_partition_count() {
        let config = fenced(30);
        let shared_mib = config.kafka.kafka_producer_queue_mib;
        let shared_messages = config.kafka.kafka_producer_queue_messages;

        for partitions in [1, 8, 16, 50, 64, 256, 1024, 4096] {
            let per_partition_mib = config.fencing_queue_mib(partitions);
            let per_partition_messages = config.fencing_queue_messages(partitions);
            assert!(
                per_partition_mib <= shared_mib,
                "partitions={partitions}: a single fenced producer must never be entitled \
                 to more than the shared producer's whole queue"
            );
            // The aggregate is the invariant: every individual value
            // looked reasonable while the total scaled with the partition
            // count, which is how the original defect hid.
            // Either the whole fleet of producers fits the aggregate, or
            // every one of them is already at the smallest queue
            // librdkafka will take — past that point the budget cannot be
            // honoured at all, and the honest answer is the floor rather
            // than a number that quietly multiplies.
            let aggregate_mib = per_partition_mib * partitions;
            assert!(
                aggregate_mib <= shared_mib || per_partition_mib == 1,
                "partitions={partitions}: fenced producers together claim {aggregate_mib} MiB \
                 against a shared budget of {shared_mib} MiB, with room to divide further"
            );
            let aggregate_messages = per_partition_messages as u64 * partitions as u64;
            assert!(
                aggregate_messages <= shared_messages as u64 || per_partition_messages == 1,
                "partitions={partitions}: fenced producers together claim \
                 {aggregate_messages} queued messages against {shared_messages}"
            );
        }
    }

    /// Dividing must not round a producer down to a depth that cannot
    /// hold a window's worth of writes.
    /// Overrides are the only way to reach the librdkafka limits the
    /// derivation floors away from, so they are the only way these two
    /// checks ever fire — and without them a pod starts with a producer
    /// librdkafka refuses to create, or with no send timeout at all.
    #[test]
    fn overrides_outside_librdkafkas_limits_are_refused() {
        for (txn_ms, message_ms, fragment) in [
            (500u64, 0u32, "below librdkafka's minimum"),
            (2000, 100, "is below"),
        ] {
            let mut config = fenced(30);
            config.fencing_txn_timeout_ms = txn_ms;
            config.fencing_message_timeout_ms = message_ms;
            let err = config
                .validate_fencing_timescales()
                .expect_err("an override outside librdkafka's limits must not start");
            assert!(
                err.contains(fragment),
                "the refusal must say which limit it trips, got: {err}"
            );
        }
    }

    /// The pre-revoke self-fence allows three seconds for a whole drain,
    /// and the drain is `wait_until_empty` *then* this wait. A budget
    /// that ate the whole allowance would turn every shutdown with an
    /// open window into a reported drain failure — while a budget under
    /// the admission window cannot outwait the window it exists to
    /// settle.
    #[test]
    fn settling_fits_inside_the_shutdown_fence_bound() {
        for lease_ttl in [21, 30, 60, 300, 3599] {
            let config = fenced(lease_ttl);
            if config.validate_fencing_timescales().is_err() {
                continue;
            }
            assert!(
                config.fencing_settle_budget() < Duration::from_secs(3),
                "LEASE_TTL={lease_ttl}: settle budget {:?} does not leave the drain room \
                 inside the self-fence's three-second allowance",
                config.fencing_settle_budget()
            );
            // The wait exists to catch a committer that sleeps for the
            // window and then commits, so a budget at or under the window
            // can never see one fire: every drain with an open window
            // would abandon the records it was meant to commit.
            assert!(
                config.fencing_settle_budget() > Duration::from_millis(config.fencing_window_ms),
                "LEASE_TTL={lease_ttl}: settle budget {:?} cannot outwait the {}ms admission \
                 window it exists to settle",
                config.fencing_settle_budget(),
                config.fencing_window_ms
            );
        }
    }

    /// Acquisition is two broker round trips and happens fleet-wide
    /// during a deploy. Nothing asserted on its budget, and tying it to
    /// the write path's once already shortened it by a quarter as a side
    /// effect of re-budgeting writes.
    #[test]
    fn acquisition_keeps_its_own_budget() {
        for lease_ttl in [21, 30, 60, 300] {
            let config = fenced(lease_ttl);
            if config.validate_fencing_timescales().is_err() {
                continue;
            }
            assert!(
                config.fencing_init_timeout() >= Duration::from_secs(2),
                "LEASE_TTL={lease_ttl}: acquisition needs room for a broker round trip"
            );
            // The timeout bounds each of the two calls acquisition makes
            // — `fetch_metadata` then `init_transactions` — so the budget
            // the lease has to cover is twice what it names.
            assert!(
                config.fencing_init_timeout() * 2 <= config.lease_fence_runway(),
                "LEASE_TTL={lease_ttl}: a warm cannot outlive the lease it warms for"
            );
        }
    }

    #[test]
    fn a_high_partition_count_still_leaves_a_workable_queue() {
        let config = fenced(30);
        // The division alone leaves a workable depth at the deployed
        // shape, and never rounds to a value librdkafka would reject.
        assert_eq!(config.fencing_queue_mib(16), 25);
        assert_eq!(config.fencing_queue_messages(16), 625_000);
        assert!(config.fencing_queue_mib(1024) >= 1);
        assert!(config.fencing_queue_messages(1024) >= 1);
        assert!(
            config.fencing_queue_mib(0) >= 1,
            "partitions=0 must not divide by zero"
        );
    }

    /// A lease TTL long enough to derive past the broker's own ceiling
    /// must be refused at startup, not discovered as an acquisition that
    /// fails on every partition with only a counter to explain it.
    #[test]
    fn a_lease_ttl_that_outruns_the_broker_ceiling_is_refused() {
        let err = fenced(3607)
            .validate_fencing_timescales()
            .expect_err("an hour-long lease derives a transaction timeout no broker accepts");
        assert!(
            err.contains("transaction.max.timeout.ms"),
            "the refusal must name the broker setting it would trip, got: {err}"
        );
        // The band's edges, both sides: the last accepted TTL under the
        // broker ceiling, and the first accepted one above the librdkafka
        // floors once the drain slack is paid.
        fenced(3606)
            .validate_fencing_timescales()
            .expect("LEASE_TTL=3606 sits just inside the broker ceiling");
        fenced(27)
            .validate_fencing_timescales()
            .expect("LEASE_TTL=27 is the acceptance floor");
        assert!(
            fenced(26).validate_fencing_timescales().is_err(),
            "below the floor, the librdkafka minimums cannot fit the drain room"
        );
        // And the production value must stay comfortably inside it.
        fenced(30)
            .validate_fencing_timescales()
            .expect("LEASE_TTL=30 must remain usable");
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

    /// The dependency is a startup failure, not a comment: fencing on a
    /// pod that will acquire without checking its lease is the shape the
    /// zombie gate reproduces.
    #[test]
    fn fencing_without_the_lease_gate_is_refused() {
        let mut config = fenced(30);
        config.lease_gated_authority = false;
        let err = config
            .validate_fencing_timescales()
            .expect_err("fencing must require the gate");
        assert!(err.contains("LEASE_GATED_AUTHORITY"), "got: {err}");
    }
}
