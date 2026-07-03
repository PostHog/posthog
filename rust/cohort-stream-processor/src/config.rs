//! Service configuration, loaded from environment variables via `envconfig`.

use std::path::PathBuf;
use std::time::Duration;

use anyhow::ensure;
use common_database::PoolConfig;
use common_kafka::config::KafkaConfig;
use common_types::cohort::TeamAllowlist;
use envconfig::Envconfig;
use rdkafka::ClientConfig;
use tracing::warn;

use crate::store::durability::DurabilityConfig;
use crate::store::{OffloadConfig, OffloadMode, StoreConfig};
use crate::workers::{CascadeConfig, EventNameGating, PersonMemoConfig, TransferRetryPolicy};

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

    /// Memoize person-property results per `(team, person)`, skipping re-evaluation when a person's
    /// properties are unchanged. Default on.
    #[envconfig(from = "COHORT_PERSON_MEMO_ENABLED", default = "true")]
    pub cohort_person_memo_enabled: bool,

    /// Per-worker LRU capacity (entries) for the person-property result memo.
    #[envconfig(from = "COHORT_PERSON_MEMO_CAPACITY", default = "20000")]
    pub cohort_person_memo_capacity: usize,

    /// Evaluate only the behavioral conditions whose event name matches the incoming event. Default on.
    #[envconfig(from = "COHORT_EVENT_NAME_GATING_ENABLED", default = "true")]
    pub cohort_event_name_gating_enabled: bool,

    /// Bounded buffer (in sub-batches) per per-partition worker channel.
    /// Routing to a partition this far behind blocks rather than growing memory unbounded.
    #[envconfig(default = "128")]
    pub partition_channel_buffer: usize,

    /// Per-partition ceiling on un-drained events in a worker's channel — the binding intake bound
    /// (the 128-slot buffer counts sub-batches, not the events inside them). Worst case in channels
    /// ≈ `cap × owned_partitions × avg_event_bytes`. Tune down if soak RSS runs hot; too low churns
    /// pause/resume.
    #[envconfig(from = "PARTITION_INTAKE_MAX_EVENTS", default = "1024")]
    pub partition_intake_max_events: usize,

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

    /// `queued.max.messages.kbytes` (KB). For a `subscribe()` consumer this is an *aggregate* cap
    /// across all partitions — the ceiling on librdkafka's fetch buffer. 128 MB.
    #[envconfig(from = "COHORT_KAFKA_QUEUED_MAX_MESSAGES_KBYTES", default = "131072")]
    pub kafka_queued_max_messages_kbytes: u32,

    /// `queued.min.messages` — per-partition prefetch floor. Low so a paused partition hoards fewer
    /// stragglers; too low risks `fetch.queue.backoff.ms` inter-fetch gaps.
    #[envconfig(from = "COHORT_KAFKA_QUEUED_MIN_MESSAGES", default = "2000")]
    pub kafka_queued_min_messages: u32,

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

    // STANDING COUPLING: these floors are derived from the Kafka topic `retention.ms` values
    // (`person_merge_events`/`cohort_merge_state_transfer` = 7d, `cohort_stream_events` = 24h,
    // `clickhouse_events_json` = 7d). If any of those `retention.ms` values change, these knobs
    // MUST follow — a marker evicted before its source topic's retention lapses re-opens the
    // replay-dedup window it exists to close. `cf_pending_transfers` is NEVER GC'd here.
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

    /// Whether the `cf_stage2` orphan GC pass runs on each merge-GC tick — reclaims composed-membership
    /// rows whose cohort has left the composable set. Default-on kill-switch; reuses `merge_gc_scan_limit`
    /// as the page cap.
    #[envconfig(from = "STAGE2_ORPHAN_GC_ENABLED", default = "true")]
    pub stage2_orphan_gc_enabled: bool,

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

    /// The internal cascade topic, keyed by `hash(team_id, person_id)` so a flip lands on the worker
    /// owning that person's `cf_stage2`. Must be co-partitioned with `cohort_stream_events`.
    #[envconfig(default = "cohort_cascade_events")]
    pub cohort_cascade_events_topic: String,

    /// Group for the `cohort_cascade_events` follower — separate so cascade-path lag is observable.
    #[envconfig(default = "cohort-stream-cascade")]
    pub kafka_cascade_consumer_group: String,

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

    /// Partition count of the co-partitioned cohort topics. Production is 64; test lanes lower it
    /// (e.g. 8) to fit many merge lanes on a single-node broker. The merge protocol's partition
    /// arithmetic must use this value, not a literal.
    #[envconfig(default = "64")]
    pub cohort_partition_count: u32,

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

    /// Tokio runtime worker threads. `0` (default) lets Tokio size the pool from
    /// `available_parallelism()`, which accounts for a CFS CPU *limit* (`cpu.max`) but not CPU
    /// *requests*/shares — so on a requests-only pod (no `limits.cpu`), or when the cgroup fs isn't
    /// readable, it returns the *node's* core count and over-subscribes the runtime. Set this to the
    /// pod's CPU budget to cap the pool regardless of how the limit is expressed.
    #[envconfig(default = "0")]
    pub tokio_worker_threads: usize,

    /// How often the sweep fires to evict state whose eviction deadline has passed.
    #[envconfig(default = "30000")]
    pub sweep_interval_ms: u64,

    /// Startup delay before the *first* eviction sweep, so its overdue-eviction read burst doesn't
    /// compete with backlog catch-up on a cold, idle store at boot. Counts from sweep-task spawn
    /// (≈ process boot), not "backlog drained", so raise it if the burst still lands on catch-up.
    #[envconfig(from = "COHORT_FIRST_EVICTION_SWEEP_DELAY_MS", default = "120000")]
    pub first_eviction_sweep_delay_ms: u64,

    /// Grace period added to every eviction deadline before the sweep acts. The sweep evicts a key
    /// only once `deadline + safety_margin < now`, absorbing consumer-lag spikes.
    #[envconfig(default = "300000")]
    pub sweep_safety_margin_ms: u64,

    /// How often the store-stats publisher and Tokio runtime monitor sample and emit their gauges
    /// (seconds).
    #[envconfig(from = "COHORT_STATS_PUBLISH_INTERVAL_SECS", default = "15")]
    pub stats_publish_interval_secs: u64,

    /// On-disk path for the per-process RocksDB state store.
    #[envconfig(default = "cohort-store")]
    pub store_path: String,

    /// Destroy any existing store at `store_path` before opening, so re-acquiring a partition never
    /// serves stale state left by a previous owner.
    #[envconfig(default = "true")]
    pub wipe_store_on_start: bool,

    /// Enable RocksDB statistics so the store-stats publisher can report cache tickers and per-CF
    /// sizes. See [`StoreConfig::statistics_enabled`].
    #[envconfig(from = "COHORT_STORE_STATISTICS_ENABLED", default = "true")]
    pub store_statistics_enabled: bool,

    /// Sample 1-in-N reads into the read-latency histogram; the read counter stays exact. See
    /// [`StoreConfig::read_sample_ratio`]. `1` records every read; `0` floors to `1`.
    #[envconfig(from = "COHORT_STORE_READ_SAMPLE_RATIO", default = "64")]
    pub store_read_sample_ratio: u32,

    /// RocksDB block-cache size in bytes, shared across all column families.
    #[envconfig(from = "COHORT_BLOCK_CACHE_BYTES", default = "134217728")]
    pub cohort_block_cache_bytes: usize,

    /// Cache and partition RocksDB index/filter blocks for faster point lookups.
    #[envconfig(from = "COHORT_TUNED_BLOCK_OPTIONS_ENABLED", default = "true")]
    pub cohort_tuned_block_options_enabled: bool,

    /// Mark tombstone-heavy SSTs for compaction so deletions reclaim disk.
    #[envconfig(from = "COHORT_COMPACT_ON_DELETION_ENABLED", default = "true")]
    pub cohort_compact_on_deletion_enabled: bool,

    /// Compact SSTs older than this many seconds; opt-in, `0` (the default) disables it so a
    /// persisted store isn't mass-rewritten on reopen.
    #[envconfig(from = "COHORT_PERIODIC_COMPACTION_SECONDS", default = "0")]
    pub cohort_periodic_compaction_seconds: u64,

    /// Cap on RocksDB background compaction/flush jobs. Non-positive leaves RocksDB's default.
    #[envconfig(from = "COHORT_MAX_BACKGROUND_JOBS", default = "0")]
    pub cohort_max_background_jobs: i32,

    /// Where store I/O runs relative to the runtime worker threads: `off` (inline on the caller —
    /// the pre-facade transport and the operator kill switch), `maintenance` (only maintenance-lane
    /// reads, the WAL fsync, and sections offload; the event path stays inline), or `all` (every op
    /// offloads to the blocking pool). Default `all`.
    #[envconfig(from = "COHORT_STORE_OFFLOAD_MODE", default = "all")]
    pub cohort_store_offload_mode: OffloadMode,

    /// Bound on event-path store reads executing concurrently on the blocking pool. Keeps a burst of
    /// event reads from saturating the disk queue; `0` disables the bound (unbounded lane).
    #[envconfig(from = "COHORT_STORE_EVENT_READ_PERMITS", default = "16")]
    pub cohort_store_event_read_permits: usize,

    /// Bound on maintenance-lane store reads and sections executing concurrently on the blocking
    /// pool (sweep prefetch, boot rebuild scans, GC). Held lower than the event lane so a
    /// maintenance storm leaves disk headroom for the event path; `0` disables the bound.
    #[envconfig(from = "COHORT_STORE_MAINTENANCE_PERMITS", default = "6")]
    pub cohort_store_maintenance_permits: usize,

    /// When on, reopen the existing store on restart instead of wiping it: recent Stage 1 state is
    /// restored and only the gap since the last committed offset is replayed (idempotent via per-key
    /// `AppliedOffsets`). Refused alongside `cohort_cascade_enabled` — merge column families are not
    /// restored yet. See [`Self::effective_wipe_on_start`].
    #[envconfig(from = "DURABLE_RESTORE_ENABLED", default = "false")]
    pub durable_restore_enabled: bool,

    /// Operator assertion that this is a single-pod, static-membership shadow deploy. Default off.
    ///
    /// Required to run `DURABLE_RESTORE_ENABLED` together with `COHORT_CASCADE_ENABLED`: a single pod
    /// with static membership reclaims its own partitions on a restart and never triggers a live
    /// rebalance. `pod_identity()` cannot gate this because it is set on every k8s pod (single or
    /// multi), so the single-vs-multi assertion needs its own flag.
    #[envconfig(from = "DURABLE_RESTORE_SINGLE_POD", default = "false")]
    pub durable_restore_single_pod: bool,

    /// Master gate for the whole-DB checkpoint + S3 backup/restore layer. Default off.
    #[envconfig(from = "CHECKPOINT_ENABLED", default = "false")]
    pub checkpoint_enabled: bool,

    /// How often a local PVC checkpoint is taken (ms).
    #[envconfig(default = "300000")]
    pub checkpoint_interval_ms: u64,

    /// How often the local checkpoint is also uploaded to S3 (ms). The upload rides every Nth local
    /// tick (`N = max(1, this / checkpoint_interval_ms)`), so the checkpoint is taken once and
    /// conditionally uploaded — never two racing `create_checkpoint`s.
    #[envconfig(default = "900000")]
    pub checkpoint_s3_upload_interval_ms: u64,

    /// Base directory for local checkpoints. Must be a subtree separate from `store_path` on the same
    /// filesystem (RocksDB refuses to checkpoint into its own directory and hard-links SSTs).
    #[envconfig(default = "cohort-checkpoints")]
    pub checkpoint_local_dir: String,

    /// S3 bucket for checkpoint uploads. Empty (default) makes the uploader unavailable, so uploads
    /// no-op.
    #[envconfig(default = "")]
    pub checkpoint_s3_bucket: String,

    /// S3 key prefix (bucket namespace) under which checkpoint attempts are stored.
    #[envconfig(default = "cohort-stream-checkpoints")]
    pub checkpoint_s3_prefix: String,

    /// AWS region for S3 (None → SDK default / IRSA-provided region).
    #[envconfig(from = "CHECKPOINT_S3_REGION")]
    pub checkpoint_s3_region: Option<String>,

    /// S3 endpoint override for S3-compatible stores (MinIO/SeaweedFS in dev). None → real AWS S3.
    #[envconfig(from = "CHECKPOINT_S3_ENDPOINT")]
    pub checkpoint_s3_endpoint: Option<String>,

    /// S3 access key id for local dev without an IAM role. None → IRSA → env → default chain.
    #[envconfig(from = "CHECKPOINT_S3_ACCESS_KEY_ID")]
    pub checkpoint_s3_access_key_id: Option<String>,

    /// S3 secret access key for local dev without an IAM role.
    #[envconfig(from = "CHECKPOINT_S3_SECRET_ACCESS_KEY")]
    pub checkpoint_s3_secret_access_key: Option<String>,

    /// Force path-style S3 URLs (required for MinIO/SeaweedFS).
    #[envconfig(default = "false")]
    pub checkpoint_s3_force_path_style: bool,

    /// Max concurrent S3 file uploads during a checkpoint export.
    #[envconfig(default = "40")]
    pub checkpoint_max_concurrent_uploads: usize,

    /// Max concurrent S3 file downloads during a checkpoint import.
    #[envconfig(default = "40")]
    pub checkpoint_max_concurrent_downloads: usize,

    /// Max upload futures actively polled per export (bounds memory: each holds read + write
    /// buffers).
    #[envconfig(default = "40")]
    pub checkpoint_max_upload_buffers: usize,

    /// Retries per S3 operation before giving up.
    #[envconfig(default = "3")]
    pub checkpoint_s3_max_retries: usize,

    /// Total timeout for one S3 operation including retries (secs).
    #[envconfig(default = "120")]
    pub checkpoint_s3_operation_timeout_secs: u64,

    /// Timeout for a single S3 operation attempt (secs).
    #[envconfig(default = "20")]
    pub checkpoint_s3_attempt_timeout_secs: u64,

    /// Max age of a local PVC checkpoint before it is distrusted on restore and the service falls
    /// back to S3 (secs). Tighter than the S3 listing window: if a pod was down longer than this,
    /// another pod likely consumed the partitions and the local copy is behind.
    #[envconfig(default = "7200")]
    pub checkpoint_local_max_staleness_secs: u64,

    /// Hours prior to now the S3 importer searches for checkpoint attempts in a PVC-lost recovery.
    #[envconfig(default = "24")]
    pub checkpoint_import_window_hours: u32,

    /// Historical S3 checkpoint attempts to try (newest first) before giving up on import.
    #[envconfig(default = "10")]
    pub checkpoint_import_attempt_depth: usize,

    /// Max time for a complete S3 checkpoint import — list + metadata + all files + fallbacks (secs).
    /// Kept under `max.poll.interval.ms` so a long restore does not get the consumer kicked.
    #[envconfig(default = "240")]
    pub checkpoint_import_timeout_secs: u64,
}

/// librdkafka consumer fetch-queue bounds: an aggregate byte cap across all partitions and a
/// per-partition prefetch floor.
#[derive(Clone, Copy, Debug)]
pub struct FetchQueueConfig {
    pub queued_max_messages_kbytes: u32,
    pub queued_min_messages: u32,
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

    pub fn sweep_interval(&self) -> Duration {
        Duration::from_millis(self.sweep_interval_ms)
    }

    pub fn first_eviction_sweep_delay(&self) -> Duration {
        Duration::from_millis(self.first_eviction_sweep_delay_ms)
    }

    pub fn fetch_queue_config(&self) -> FetchQueueConfig {
        FetchQueueConfig {
            queued_max_messages_kbytes: self.kafka_queued_max_messages_kbytes,
            queued_min_messages: self.kafka_queued_min_messages,
        }
    }

    pub fn sweep_safety_margin(&self) -> Duration {
        Duration::from_millis(self.sweep_safety_margin_ms)
    }

    pub fn stats_publish_interval(&self) -> Duration {
        // Floor at 1s: `tokio::time::interval` panics on a zero period.
        Duration::from_secs(self.stats_publish_interval_secs).max(Duration::from_secs(1))
    }

    pub fn transfer_retry_policy(&self) -> TransferRetryPolicy {
        TransferRetryPolicy {
            max_retries: self.merge_transfer_max_retries,
            base: Duration::from_millis(self.merge_transfer_retry_base_ms),
            cap: Duration::from_millis(self.merge_transfer_retry_cap_ms),
        }
    }

    pub fn merge_redrive_interval(&self) -> Duration {
        Duration::from_millis(self.merge_redrive_interval_ms)
    }

    pub fn cascade_config(&self) -> CascadeConfig {
        CascadeConfig {
            enabled: self.cohort_cascade_enabled,
            depth_cap: self.cohort_cascade_depth_cap,
            fanout_cap: self.cohort_cascade_fanout_cap,
        }
    }

    pub fn person_memo_config(&self) -> PersonMemoConfig {
        PersonMemoConfig {
            enabled: self.cohort_person_memo_enabled,
            capacity: self.cohort_person_memo_capacity,
        }
    }

    pub fn event_name_gating(&self) -> EventNameGating {
        EventNameGating::from_enabled(self.cohort_event_name_gating_enabled)
    }

    pub fn merge_gc_interval(&self) -> Duration {
        Duration::from_millis(self.merge_gc_interval_ms)
    }

    pub fn checkpoint_interval(&self) -> Duration {
        Duration::from_millis(self.checkpoint_interval_ms)
    }

    pub fn checkpoint_s3_upload_interval(&self) -> Duration {
        Duration::from_millis(self.checkpoint_s3_upload_interval_ms)
    }

    pub fn checkpoint_local_max_staleness(&self) -> Duration {
        Duration::from_secs(self.checkpoint_local_max_staleness_secs)
    }

    pub fn durability_config(&self) -> DurabilityConfig {
        DurabilityConfig {
            local_checkpoint_dir: self.checkpoint_local_dir.clone(),
            s3_bucket: self.checkpoint_s3_bucket.clone(),
            s3_key_prefix: self.checkpoint_s3_prefix.clone(),
            aws_region: self.checkpoint_s3_region.clone(),
            s3_endpoint: self.checkpoint_s3_endpoint.clone(),
            s3_access_key_id: self.checkpoint_s3_access_key_id.clone(),
            s3_secret_access_key: self.checkpoint_s3_secret_access_key.clone(),
            s3_force_path_style: self.checkpoint_s3_force_path_style,
            checkpoint_import_window_hours: self.checkpoint_import_window_hours,
            s3_operation_timeout: Duration::from_secs(self.checkpoint_s3_operation_timeout_secs),
            s3_attempt_timeout: Duration::from_secs(self.checkpoint_s3_attempt_timeout_secs),
            s3_max_retries: self.checkpoint_s3_max_retries,
            checkpoint_import_attempt_depth: self.checkpoint_import_attempt_depth,
            max_concurrent_checkpoint_file_downloads: self.checkpoint_max_concurrent_downloads,
            max_concurrent_checkpoint_file_uploads: self.checkpoint_max_concurrent_uploads,
            max_upload_buffers: self.checkpoint_max_upload_buffers,
            checkpoint_import_timeout: Duration::from_secs(self.checkpoint_import_timeout_secs),
            local_checkpoint_max_staleness: self.checkpoint_local_max_staleness(),
        }
    }

    /// Refuse unsafe durability startup combinations. Pure (no I/O), so unit-testable without a broker.
    ///
    /// Guards:
    /// - `checkpoint_enabled` requires `durable_restore_enabled`: without it the restored DB is wiped
    ///   on open, silently discarding the restore.
    /// - `durable_restore_enabled` + `cohort_cascade_enabled` requires `durable_restore_single_pod`
    ///   and a pod identity: `pod_identity()` alone is not a single-pod signal (set on every k8s pod).
    pub fn validate_durability_startup(&self) -> anyhow::Result<()> {
        ensure!(
            !self.checkpoint_enabled || self.durable_restore_enabled,
            "CHECKPOINT_ENABLED requires DURABLE_RESTORE_ENABLED: restoring a checkpoint without \
             reopen-live is meaningless.",
        );

        if self.durable_restore_enabled && self.cohort_cascade_enabled {
            let single_pod_static =
                self.durable_restore_single_pod && self.pod_identity().is_some();
            ensure!(
                single_pod_static,
                "DURABLE_RESTORE_ENABLED=true is unsafe with COHORT_CASCADE_ENABLED=true: merge \
                 column families are not restored yet. Disable one of them, or set \
                 DURABLE_RESTORE_SINGLE_POD=true on a single-pod static-membership (POD_NAME/HOSTNAME \
                 set) shadow deploy.",
            );
            warn!(
                durable_restore_single_pod = self.durable_restore_single_pod,
                pod_identity = self.pod_identity().unwrap_or("<none>"),
                "DURABLE_RESTORE_ENABLED + COHORT_CASCADE_ENABLED allowed on a single-pod \
                 static-membership shadow. RESIDUALS deferred to Slice 3: multi-pod rebalance \
                 F3-on-revoke and the post-join↔delete REVOKE race are NOT covered (single-pod \
                 membership sidesteps them); merge column-family *content* resume after an S3 restore \
                 is validated only on this shadow, NOT production multi-pod merge durability.",
            );
        }

        Ok(())
    }

    /// Whether to wipe the store on start, folding in the durable-restore gate: keep the live store
    /// only when restore is on and one already exists on disk. Touches the filesystem (`.exists()`) —
    /// a one-shot decision evaluated once at store open.
    pub fn effective_wipe_on_start(&self) -> bool {
        let db_dir_exists = PathBuf::from(&self.store_path).exists();
        self.wipe_store_on_start && !(self.durable_restore_enabled && db_dir_exists)
    }

    pub fn store_config(&self) -> StoreConfig {
        StoreConfig {
            path: PathBuf::from(&self.store_path),
            wipe_on_start: self.effective_wipe_on_start(),
            statistics_enabled: self.store_statistics_enabled,
            read_sample_ratio: self.store_read_sample_ratio,
            block_cache_bytes: self.cohort_block_cache_bytes,
            tuned_block_options: self.cohort_tuned_block_options_enabled,
            compact_on_deletion: self.cohort_compact_on_deletion_enabled,
            periodic_compaction_seconds: self.cohort_periodic_compaction_seconds,
            max_background_jobs: self.cohort_max_background_jobs,
            ..StoreConfig::default()
        }
    }

    /// Resolve the store-offload strategy and per-lane concurrency bounds handed to the
    /// [`StoreHandle`](crate::store::StoreHandle).
    pub fn offload_config(&self) -> OffloadConfig {
        OffloadConfig {
            mode: self.cohort_store_offload_mode,
            event_read_permits: self.cohort_store_event_read_permits,
            maintenance_permits: self.cohort_store_maintenance_permits,
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

        // Bound librdkafka's fetch buffer: an aggregate byte ceiling plus a per-partition prefetch floor.
        let fetch = self.fetch_queue_config();
        config
            .set(
                "queued.max.messages.kbytes",
                fetch.queued_max_messages_kbytes.to_string(),
            )
            .set("queued.min.messages", fetch.queued_min_messages.to_string());

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
            cohort_person_memo_enabled: true,
            cohort_person_memo_capacity: 20000,
            cohort_event_name_gating_enabled: true,
            partition_channel_buffer: 128,
            partition_intake_max_events: 1024,
            kafka_hosts: "localhost:9092".to_string(),
            kafka_tls: false,
            kafka_client_id: String::new(),
            kafka_client_rack: String::new(),
            cohort_stream_events_topic: "cohort_stream_events".to_string(),
            kafka_consumer_group: "cohort-stream-processor".to_string(),
            kafka_consumer_offset_reset: "latest".to_string(),
            kafka_queued_max_messages_kbytes: 131_072,
            kafka_queued_min_messages: 2000,
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
            stage2_orphan_gc_enabled: true,
            cohort_cascade_depth_cap: 8,
            cohort_cascade_fanout_cap: 1000,
            cohort_cascade_enabled: false,
            cohort_cascade_events_topic: "cohort_cascade_events".to_string(),
            kafka_cascade_consumer_group: "cohort-stream-cascade".to_string(),
            kafka_session_timeout_ms: 60000,
            pod_name: None,
            pod_hostname: None,
            cohort_membership_changed_topic: "cohort_membership_changed_shadow".to_string(),
            kafka_producer_partitioner: "murmur2_random".to_string(),
            cohort_partition_count: 64,
            kafka_compression_codec: "none".to_string(),
            recv_batch_size: 1000,
            recv_batch_timeout_ms: 500,
            offset_commit_interval_ms: 5000,
            tokio_worker_threads: 0,
            sweep_interval_ms: 30000,
            first_eviction_sweep_delay_ms: 120_000,
            sweep_safety_margin_ms: 300000,
            stats_publish_interval_secs: 15,
            store_path: "cohort-store".to_string(),
            wipe_store_on_start: true,
            store_statistics_enabled: true,
            store_read_sample_ratio: 64,
            cohort_block_cache_bytes: 134_217_728,
            cohort_tuned_block_options_enabled: true,
            cohort_compact_on_deletion_enabled: true,
            cohort_periodic_compaction_seconds: 0,
            cohort_max_background_jobs: 0,
            cohort_store_offload_mode: OffloadMode::All,
            cohort_store_event_read_permits: 16,
            cohort_store_maintenance_permits: 6,
            durable_restore_enabled: false,
            durable_restore_single_pod: false,
            checkpoint_enabled: false,
            checkpoint_interval_ms: 300_000,
            checkpoint_s3_upload_interval_ms: 900_000,
            checkpoint_local_dir: "cohort-checkpoints".to_string(),
            checkpoint_s3_bucket: String::new(),
            checkpoint_s3_prefix: "cohort-stream-checkpoints".to_string(),
            checkpoint_s3_region: None,
            checkpoint_s3_endpoint: None,
            checkpoint_s3_access_key_id: None,
            checkpoint_s3_secret_access_key: None,
            checkpoint_s3_force_path_style: false,
            checkpoint_max_concurrent_uploads: 40,
            checkpoint_max_concurrent_downloads: 40,
            checkpoint_max_upload_buffers: 40,
            checkpoint_s3_max_retries: 3,
            checkpoint_s3_operation_timeout_secs: 120,
            checkpoint_s3_attempt_timeout_secs: 20,
            checkpoint_local_max_staleness_secs: 7200,
            checkpoint_import_window_hours: 24,
            checkpoint_import_attempt_depth: 10,
            checkpoint_import_timeout_secs: 240,
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
    fn consumer_config_sets_the_fetch_queue_bounds() {
        let config = test_config();
        let client = config.consumer_client_config();
        assert_eq!(client.get("queued.max.messages.kbytes"), Some("131072"));
        assert_eq!(client.get("queued.min.messages"), Some("2000"));
    }

    #[test]
    fn intake_and_boot_ordering_knobs_default_and_override_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert_eq!(defaults.partition_intake_max_events, 1024);
        assert_eq!(defaults.kafka_queued_max_messages_kbytes, 131_072);
        assert_eq!(defaults.kafka_queued_min_messages, 2000);
        assert_eq!(
            defaults.first_eviction_sweep_delay(),
            Duration::from_millis(120_000),
        );

        let env: std::collections::HashMap<String, String> = [
            ("PARTITION_INTAKE_MAX_EVENTS", "512"),
            ("COHORT_KAFKA_QUEUED_MAX_MESSAGES_KBYTES", "65536"),
            ("COHORT_KAFKA_QUEUED_MIN_MESSAGES", "1000"),
            ("COHORT_FIRST_EVICTION_SWEEP_DELAY_MS", "30000"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.partition_intake_max_events, 512);
        assert_eq!(
            config.fetch_queue_config().queued_max_messages_kbytes,
            65536
        );
        assert_eq!(config.fetch_queue_config().queued_min_messages, 1000);
        assert_eq!(
            config.first_eviction_sweep_delay(),
            Duration::from_millis(30_000),
        );
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
    fn stats_knobs_default_on_and_thread_into_store_config() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(defaults.store_statistics_enabled);
        assert!(defaults.store_config().statistics_enabled);
        assert_eq!(defaults.stats_publish_interval(), Duration::from_secs(15));
        assert_eq!(defaults.store_read_sample_ratio, 64);
        assert_eq!(defaults.store_config().read_sample_ratio, 64);

        let env: std::collections::HashMap<String, String> = [
            ("COHORT_STORE_STATISTICS_ENABLED", "false"),
            ("COHORT_STATS_PUBLISH_INTERVAL_SECS", "30"),
            ("COHORT_STORE_READ_SAMPLE_RATIO", "8"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(!config.store_statistics_enabled);
        assert!(
            !config.store_config().statistics_enabled,
            "the flag reaches StoreConfig",
        );
        assert_eq!(config.stats_publish_interval(), Duration::from_secs(30));
        assert_eq!(config.store_read_sample_ratio, 8);
        assert_eq!(
            config.store_config().read_sample_ratio,
            8,
            "the sample ratio reaches StoreConfig",
        );
    }

    #[test]
    fn offload_knobs_default_and_override_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        let offload = defaults.offload_config();
        assert_eq!(offload.mode, OffloadMode::All, "offload defaults to All");
        assert_eq!(offload.event_read_permits, 16);
        assert_eq!(offload.maintenance_permits, 6);

        // Override all three, including `maintenance` mode and a `0` (unbounded) permit lane.
        let env: std::collections::HashMap<String, String> = [
            ("COHORT_STORE_OFFLOAD_MODE", "maintenance"),
            ("COHORT_STORE_EVENT_READ_PERMITS", "8"),
            ("COHORT_STORE_MAINTENANCE_PERMITS", "0"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        let offload = config.offload_config();
        assert_eq!(offload.mode, OffloadMode::Maintenance);
        assert_eq!(offload.event_read_permits, 8);
        assert_eq!(offload.maintenance_permits, 0, "0 = unbounded lane");

        // `off` parses.
        let off_env: std::collections::HashMap<String, String> =
            [("COHORT_STORE_OFFLOAD_MODE", "off")]
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect();
        assert_eq!(
            Config::init_from_hashmap(&off_env)
                .unwrap()
                .offload_config()
                .mode,
            OffloadMode::Off,
        );

        // An unknown mode string fails init (the FromStr error surfaces through envconfig).
        let bad_env: std::collections::HashMap<String, String> =
            [("COHORT_STORE_OFFLOAD_MODE", "occasionally")]
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect();
        assert!(
            Config::init_from_hashmap(&bad_env).is_err(),
            "an invalid offload mode must fail config init",
        );
    }

    #[test]
    fn stats_publish_interval_floors_zero_at_one_second() {
        // Zero would panic `tokio::time::interval`; the accessor clamps to 1s.
        let env: std::collections::HashMap<String, String> =
            [("COHORT_STATS_PUBLISH_INTERVAL_SECS", "0")]
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.stats_publish_interval(), Duration::from_secs(1));
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
    fn durable_restore_defaults_off_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(
            !defaults.durable_restore_enabled,
            "durable restore defaults off"
        );

        let env: std::collections::HashMap<String, String> = [("DURABLE_RESTORE_ENABLED", "true")]
            .into_iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(config.durable_restore_enabled);
    }

    #[test]
    fn durable_restore_single_pod_defaults_off_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(
            !defaults.durable_restore_single_pod,
            "the single-pod assertion defaults off (inert)",
        );

        let env: std::collections::HashMap<String, String> =
            [("DURABLE_RESTORE_SINGLE_POD", "true")]
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(config.durable_restore_single_pod);
    }

    #[test]
    fn durability_startup_guard_passes_for_the_default_config() {
        assert!(test_config().validate_durability_startup().is_ok());
    }

    #[test]
    fn durability_startup_guard_passes_for_a_plain_durable_restore() {
        let mut config = test_config();
        config.durable_restore_enabled = true;
        assert!(config.validate_durability_startup().is_ok());
    }

    #[test]
    fn durability_startup_guard_refuses_durable_plus_cascade_without_the_opt_in() {
        let mut config = test_config();
        config.durable_restore_enabled = true;
        config.cohort_cascade_enabled = true;
        config.pod_name = Some("pod-0".to_string());
        let err = config
            .validate_durability_startup()
            .expect_err("durable + cascade without the opt-in must be refused");
        assert!(
            err.to_string().contains("DURABLE_RESTORE_SINGLE_POD"),
            "the refusal points the operator at the single-pod opt-in: {err}",
        );
    }

    #[test]
    fn durability_startup_guard_refuses_durable_plus_cascade_with_opt_in_but_no_pod_identity() {
        let mut config = test_config();
        config.durable_restore_enabled = true;
        config.cohort_cascade_enabled = true;
        config.durable_restore_single_pod = true;
        config.pod_name = None;
        config.pod_hostname = None;
        assert!(
            config.validate_durability_startup().is_err(),
            "single-pod opt-in without a pod identity must still refuse the combo",
        );
    }

    #[test]
    fn durability_startup_guard_allows_durable_plus_cascade_with_opt_in_and_pod_identity() {
        let mut config = test_config();
        config.durable_restore_enabled = true;
        config.cohort_cascade_enabled = true;
        config.durable_restore_single_pod = true;
        config.pod_name = Some("cohort-stream-processor-0".to_string());
        assert!(
            config.validate_durability_startup().is_ok(),
            "durable + cascade is allowed on a single-pod static-membership deploy",
        );
    }

    #[test]
    fn durability_startup_guard_refuses_checkpoint_without_durable_restore() {
        let mut config = test_config();
        config.checkpoint_enabled = true;
        config.durable_restore_enabled = false;
        let err = config
            .validate_durability_startup()
            .expect_err("checkpoint without durable restore must be refused");
        assert!(
            err.to_string().contains("DURABLE_RESTORE_ENABLED"),
            "the refusal names the durable-restore requirement: {err}",
        );
    }

    #[test]
    fn durability_startup_guard_allows_checkpoint_with_durable_restore() {
        let mut config = test_config();
        config.checkpoint_enabled = true;
        config.durable_restore_enabled = true;
        assert!(config.validate_durability_startup().is_ok());
    }

    #[test]
    fn checkpoint_config_defaults_off_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(
            !defaults.checkpoint_enabled,
            "the checkpoint master gate defaults off",
        );
        assert_eq!(
            defaults.checkpoint_interval(),
            Duration::from_millis(300_000)
        );
        assert_eq!(
            defaults.checkpoint_s3_upload_interval(),
            Duration::from_millis(900_000),
        );
        assert_eq!(defaults.checkpoint_local_dir, "cohort-checkpoints");
        assert!(
            defaults.checkpoint_s3_bucket.is_empty(),
            "no S3 bucket by default → uploader inert",
        );
        assert_eq!(
            defaults.checkpoint_local_max_staleness(),
            Duration::from_secs(7200),
        );
        assert_eq!(defaults.checkpoint_import_window_hours, 24);
        assert_eq!(defaults.checkpoint_import_attempt_depth, 10);

        let env: std::collections::HashMap<String, String> = [
            ("CHECKPOINT_ENABLED", "true"),
            ("CHECKPOINT_INTERVAL_MS", "60000"),
            ("CHECKPOINT_S3_UPLOAD_INTERVAL_MS", "120000"),
            ("CHECKPOINT_LOCAL_DIR", "/data/ckpt"),
            ("CHECKPOINT_S3_BUCKET", "my-bucket"),
            ("CHECKPOINT_S3_PREFIX", "ckpt-prefix"),
            ("CHECKPOINT_S3_REGION", "us-east-1"),
            ("CHECKPOINT_S3_ENDPOINT", "http://minio:9000"),
            ("CHECKPOINT_S3_ACCESS_KEY_ID", "ak"),
            ("CHECKPOINT_S3_SECRET_ACCESS_KEY", "sk"),
            ("CHECKPOINT_S3_FORCE_PATH_STYLE", "true"),
            ("CHECKPOINT_MAX_CONCURRENT_UPLOADS", "8"),
            ("CHECKPOINT_MAX_CONCURRENT_DOWNLOADS", "9"),
            ("CHECKPOINT_MAX_UPLOAD_BUFFERS", "10"),
            ("CHECKPOINT_S3_MAX_RETRIES", "5"),
            ("CHECKPOINT_S3_OPERATION_TIMEOUT_SECS", "60"),
            ("CHECKPOINT_S3_ATTEMPT_TIMEOUT_SECS", "11"),
            ("CHECKPOINT_LOCAL_MAX_STALENESS_SECS", "3600"),
            ("CHECKPOINT_IMPORT_WINDOW_HOURS", "12"),
            ("CHECKPOINT_IMPORT_ATTEMPT_DEPTH", "4"),
            ("CHECKPOINT_IMPORT_TIMEOUT_SECS", "90"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(config.checkpoint_enabled);
        assert_eq!(config.checkpoint_interval(), Duration::from_millis(60_000));
        assert_eq!(
            config.checkpoint_s3_upload_interval(),
            Duration::from_millis(120_000),
        );
        assert_eq!(config.checkpoint_local_dir, "/data/ckpt");
        assert_eq!(config.checkpoint_s3_bucket, "my-bucket");
        assert_eq!(config.checkpoint_import_window_hours, 12);
        assert_eq!(config.checkpoint_import_attempt_depth, 4);
    }

    #[test]
    fn durability_config_maps_the_checkpoint_fields() {
        let mut config = test_config();
        config.checkpoint_local_dir = "/data/ckpt".to_string();
        config.checkpoint_s3_bucket = "bkt".to_string();
        config.checkpoint_s3_prefix = "pfx".to_string();
        config.checkpoint_s3_region = Some("eu-central-1".to_string());
        config.checkpoint_s3_endpoint = Some("http://seaweedfs:8333".to_string());
        config.checkpoint_s3_access_key_id = Some("ak".to_string());
        config.checkpoint_s3_secret_access_key = Some("sk".to_string());
        config.checkpoint_s3_force_path_style = true;
        config.checkpoint_max_concurrent_uploads = 7;
        config.checkpoint_max_concurrent_downloads = 8;
        config.checkpoint_max_upload_buffers = 9;
        config.checkpoint_s3_max_retries = 2;
        config.checkpoint_s3_operation_timeout_secs = 60;
        config.checkpoint_s3_attempt_timeout_secs = 11;
        config.checkpoint_local_max_staleness_secs = 3600;
        config.checkpoint_import_window_hours = 6;
        config.checkpoint_import_attempt_depth = 4;
        config.checkpoint_import_timeout_secs = 90;

        let durability = config.durability_config();
        assert_eq!(durability.local_checkpoint_dir, "/data/ckpt");
        assert_eq!(durability.s3_bucket, "bkt");
        assert_eq!(durability.s3_key_prefix, "pfx");
        assert_eq!(durability.aws_region.as_deref(), Some("eu-central-1"));
        assert_eq!(
            durability.s3_endpoint.as_deref(),
            Some("http://seaweedfs:8333"),
        );
        assert_eq!(durability.s3_access_key_id.as_deref(), Some("ak"));
        assert!(durability.s3_force_path_style);
        assert_eq!(durability.max_concurrent_checkpoint_file_uploads, 7);
        assert_eq!(durability.max_concurrent_checkpoint_file_downloads, 8);
        assert_eq!(durability.max_upload_buffers, 9);
        assert_eq!(durability.s3_max_retries, 2);
        assert_eq!(durability.s3_operation_timeout, Duration::from_secs(60));
        assert_eq!(durability.s3_attempt_timeout, Duration::from_secs(11));
        assert_eq!(
            durability.local_checkpoint_max_staleness,
            Duration::from_secs(3600),
        );
        assert_eq!(durability.checkpoint_import_window_hours, 6);
        assert_eq!(durability.checkpoint_import_attempt_depth, 4);
        assert_eq!(
            durability.checkpoint_import_timeout,
            Duration::from_secs(90)
        );
    }

    #[test]
    fn effective_wipe_on_start_truth_table() {
        let dir = tempfile::TempDir::new().unwrap();
        let existing = dir.path().join("db");
        std::fs::create_dir_all(&existing).unwrap();
        let missing = dir.path().join("does-not-exist");

        // (wipe_store_on_start, durable_restore_enabled, store exists) -> effective wipe.
        let cases = [
            (true, false, true, true, "wipe-on + restore-off + present"),
            (true, false, false, true, "wipe-on + restore-off + absent"),
            (
                false,
                false,
                true,
                false,
                "wipe-off + restore-off + present",
            ),
            (
                true,
                true,
                true,
                false,
                "wipe-on + restore-on + present → reopen-live",
            ),
            (
                true,
                true,
                false,
                true,
                "wipe-on + restore-on + absent → fresh wipe (no-op)",
            ),
            (false, true, true, false, "wipe-off + restore-on + present"),
        ];
        for (wipe, durable, exists, expected, why) in cases {
            let mut config = test_config();
            config.wipe_store_on_start = wipe;
            config.durable_restore_enabled = durable;
            config.store_path = if exists {
                existing.to_string_lossy().into_owned()
            } else {
                missing.to_string_lossy().into_owned()
            };
            assert_eq!(config.effective_wipe_on_start(), expected, "{why}");
            assert_eq!(
                config.store_config().wipe_on_start,
                expected,
                "store_config must thread the effective wipe: {why}",
            );
        }
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
        assert!(
            config.stage2_orphan_gc_enabled,
            "the cf_stage2 orphan GC defaults on",
        );
    }

    #[test]
    fn merge_gc_knobs_override_from_env() {
        let env: std::collections::HashMap<String, String> = [
            ("MERGE_MARKER_RETENTION_MS", "123"),
            ("MERGE_TOMBSTONE_RETENTION_MS", "456"),
            ("MERGE_GC_INTERVAL_MS", "789"),
            ("MERGE_GC_SCAN_LIMIT", "5"),
            ("STAGE2_ORPHAN_GC_ENABLED", "false"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.merge_marker_retention_ms, 123);
        assert_eq!(config.merge_tombstone_retention_ms, 456);
        assert_eq!(config.merge_gc_interval(), Duration::from_millis(789));
        assert_eq!(config.merge_gc_scan_limit, 5);
        assert!(
            !config.stage2_orphan_gc_enabled,
            "the kill-switch disables the cf_stage2 orphan GC",
        );
    }

    #[test]
    fn person_memo_defaults_on_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(
            defaults.cohort_person_memo_enabled,
            "the person memo defaults on",
        );
        assert_eq!(defaults.cohort_person_memo_capacity, 20000);
        assert!(
            defaults.person_memo_config().enabled,
            "person_memo_config threads the enabled flag",
        );
        assert_eq!(defaults.person_memo_config().capacity, 20000);

        let env: std::collections::HashMap<String, String> = [
            ("COHORT_PERSON_MEMO_ENABLED", "false"),
            ("COHORT_PERSON_MEMO_CAPACITY", "5000"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(
            !config.cohort_person_memo_enabled,
            "the kill-switch disables the memo",
        );
        assert_eq!(config.cohort_person_memo_capacity, 5000);
    }

    #[test]
    fn event_name_gating_defaults_on_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert!(
            defaults.cohort_event_name_gating_enabled,
            "the event-name gate defaults on",
        );
        assert_eq!(defaults.event_name_gating(), EventNameGating::Enabled);

        let env: std::collections::HashMap<String, String> =
            [("COHORT_EVENT_NAME_GATING_ENABLED", "false")]
                .into_iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert!(!config.cohort_event_name_gating_enabled);
        assert_eq!(config.event_name_gating(), EventNameGating::Disabled);
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
        assert_eq!(
            defaults.cohort_cascade_events_topic,
            "cohort_cascade_events"
        );
        assert_eq!(
            defaults.kafka_cascade_consumer_group,
            "cohort-stream-cascade"
        );

        let env: std::collections::HashMap<String, String> = [
            ("COHORT_CASCADE_DEPTH_CAP", "3"),
            ("COHORT_CASCADE_FANOUT_CAP", "50"),
            ("COHORT_CASCADE_ENABLED", "true"),
            ("COHORT_CASCADE_EVENTS_TOPIC", "cascade_test"),
            ("KAFKA_CASCADE_CONSUMER_GROUP", "cascade-group-test"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();

        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.cohort_cascade_depth_cap, 3);
        assert_eq!(config.cohort_cascade_fanout_cap, 50);
        assert!(config.cohort_cascade_enabled);
        assert_eq!(config.cohort_cascade_events_topic, "cascade_test");
        assert_eq!(config.kafka_cascade_consumer_group, "cascade-group-test");
        assert_eq!(
            config.cascade_config(),
            CascadeConfig {
                enabled: true,
                depth_cap: 3,
                fanout_cap: 50,
            },
        );
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
    fn cohort_partition_count_defaults_to_64_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert_eq!(
            defaults.cohort_partition_count, 64,
            "production default is 64 so behavior stays byte-identical",
        );

        let env: std::collections::HashMap<String, String> = [("COHORT_PARTITION_COUNT", "8")]
            .into_iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.cohort_partition_count, 8);
    }

    #[test]
    fn store_tuning_config_defaults_and_overrides_from_env() {
        let defaults = Config::init_from_hashmap(&std::collections::HashMap::new()).unwrap();
        assert_eq!(defaults.cohort_block_cache_bytes, 134_217_728);
        assert!(defaults.cohort_tuned_block_options_enabled);
        assert!(defaults.cohort_compact_on_deletion_enabled);
        assert_eq!(defaults.cohort_periodic_compaction_seconds, 0);
        assert_eq!(defaults.cohort_max_background_jobs, 0);
        assert_eq!(defaults.partition_channel_buffer, 128);

        let env: std::collections::HashMap<String, String> = [
            ("COHORT_BLOCK_CACHE_BYTES", "3221225472"),
            ("COHORT_TUNED_BLOCK_OPTIONS_ENABLED", "false"),
            ("COHORT_COMPACT_ON_DELETION_ENABLED", "false"),
            ("COHORT_PERIODIC_COMPACTION_SECONDS", "3600"),
            ("COHORT_MAX_BACKGROUND_JOBS", "2"),
            ("PARTITION_CHANNEL_BUFFER", "256"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
        let config = Config::init_from_hashmap(&env).unwrap();
        assert_eq!(config.cohort_block_cache_bytes, 3_221_225_472);
        assert!(!config.cohort_tuned_block_options_enabled);
        assert!(!config.cohort_compact_on_deletion_enabled);
        assert_eq!(config.cohort_periodic_compaction_seconds, 3600);
        assert_eq!(config.cohort_max_background_jobs, 2);
        assert_eq!(config.partition_channel_buffer, 256);
    }

    #[test]
    fn store_config_threads_the_rocksdb_tuning_knobs() {
        let mut config = test_config();
        config.cohort_block_cache_bytes = 3_221_225_472;
        config.cohort_tuned_block_options_enabled = false;
        config.cohort_compact_on_deletion_enabled = false;
        config.cohort_periodic_compaction_seconds = 3600;
        config.cohort_max_background_jobs = 2;

        let store = config.store_config();
        assert_eq!(store.block_cache_bytes, 3_221_225_472);
        assert!(!store.tuned_block_options);
        assert!(!store.compact_on_deletion);
        assert_eq!(store.periodic_compaction_seconds, 3600);
        assert_eq!(store.max_background_jobs, 2);
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
