use std::collections::HashSet;
use std::{net::SocketAddr, num::NonZeroU32};

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;
use sha2::{Digest, Sha256};
use tracing::Level;

#[derive(Debug, PartialEq, Eq, Clone, Copy, Hash)]
pub enum CaptureMode {
    Events,
    Recordings,
    Ai,
    /// Analytics ingestion dedicated to historical backfills (the
    /// batch-import-worker). Like `Events` for the batch/event paths, but with
    /// three differences: it never applies the global rate limiter, it drops any
    /// batch not flagged `historical_migration: true`, and it does not register
    /// the AI or OTEL routes (those handlers hardcode `historical_migration:
    /// false` and would bypass both gates). See `applies_global_rate_limit`,
    /// `requires_historical_migration`, and the router's per-mode arm.
    Import,
}

impl CaptureMode {
    pub fn as_tag(&self) -> &'static str {
        match self {
            CaptureMode::Events => "events",
            CaptureMode::Recordings => "recordings",
            CaptureMode::Ai => "ai",
            CaptureMode::Import => "import",
        }
    }

    /// Whether this mode subjects incoming events to the per-(token,
    /// distinct_id) global rate limiter. `Import` opts out: historical
    /// backfills are internal traffic that must not be throttled.
    ///
    /// Note this is necessary but not sufficient: only the analytics processing
    /// paths (legacy `events::analytics` and `v1::analytics`) actually consult
    /// the limiter, so `Recordings` never rate-limits despite returning `true`
    /// here. The predicate gates the two analytics paths; other paths ignore it.
    pub fn applies_global_rate_limit(&self) -> bool {
        !matches!(self, CaptureMode::Import)
    }

    /// Whether this mode drops any batch not marked `historical_migration:
    /// true`. Only `Import` does — it exclusively ingests historical data.
    pub fn requires_historical_migration(&self) -> bool {
        matches!(self, CaptureMode::Import)
    }
}

impl std::str::FromStr for CaptureMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "events" => Ok(CaptureMode::Events),
            "recordings" => Ok(CaptureMode::Recordings),
            "ai" => Ok(CaptureMode::Ai),
            "import" => Ok(CaptureMode::Import),
            _ => Err(format!("Unknown Capture Type: {s}")),
        }
    }
}

/// Compression algorithm applied at the Kafka message payload (envelope) level,
/// independent of the broker-level `compression.codec` setting.
/// Enables Warpstream billing reduction by storing compressed bytes.
#[derive(Debug, PartialEq, Eq, Clone, Copy, Default)]
pub enum EnvelopeCompression {
    #[default]
    None,
    Lz4,
}

impl std::str::FromStr for EnvelopeCompression {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "none" => Ok(EnvelopeCompression::None),
            "lz4" => Ok(EnvelopeCompression::Lz4),
            _ => Err(format!("Unknown EnvelopeCompression: {s}")),
        }
    }
}

/// Routing mode for AI capture events between the primary cluster and a
/// secondary (e.g. WarpStream) cluster. Only consulted in `CaptureMode::Ai`.
#[derive(Debug, PartialEq, Eq, Clone, Copy, Default)]
pub enum AiSinkMode {
    /// All AI events stay on the primary sink (current behavior).
    #[default]
    Primary,
    /// Only tokens listed in `ai_secondary_allowlist_tokens` go to the
    /// secondary sink; everything else stays on the primary.
    SecondaryAllowlist,
    /// Tokens whose deterministic hash bucket falls under the configured
    /// percentage go to the secondary sink; everything else stays on the
    /// primary.
    SecondaryPercentage,
    /// All AI events go to the secondary sink.
    Secondary,
}

impl std::str::FromStr for AiSinkMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "primary" => Ok(AiSinkMode::Primary),
            "secondary_allowlist" | "secondary-allowlist" => Ok(AiSinkMode::SecondaryAllowlist),
            "secondary_percentage" | "secondary-percentage" => Ok(AiSinkMode::SecondaryPercentage),
            "secondary" => Ok(AiSinkMode::Secondary),
            _ => Err(format!("Unknown AiSinkMode: {s}")),
        }
    }
}

/// Resolved AI routing policy: the configured `AiSinkMode` with the token
/// allowlist or percentage it needs attached to the variant that uses it.
/// Built from the raw `ai_sink_mode` + companion config in `setup` and
/// carried by `SplitKafkaSink`, so routing needs nothing but the event's token.
#[derive(Debug, Clone)]
pub enum AiRouting {
    Primary,
    SecondaryAllowlist(HashSet<String>),
    SecondaryPercentage(u8),
    Secondary,
}

impl AiRouting {
    /// Whether an AI event for `token` should be routed to the secondary sink.
    /// `Primary` never does; `Secondary` always does; `SecondaryAllowlist` routes
    /// only allowlisted tokens; `SecondaryPercentage` routes tokens whose bucket
    /// falls under the percentage.
    pub fn routes_to_secondary(&self, token: &str) -> bool {
        match self {
            AiRouting::Primary => false,
            AiRouting::Secondary => true,
            AiRouting::SecondaryAllowlist(allowlist) => allowlist.contains(token),
            AiRouting::SecondaryPercentage(percentage) => {
                token_percentage_bucket(token) < *percentage
            }
        }
    }
}

/// Deterministic 0-99 bucket for a project API token, used by
/// `AiRouting::SecondaryPercentage`. Keying on the token (not the distinct id)
/// keeps a whole team on one side of the split, and SHA-256 keeps the bucket
/// stable across pods, restarts, and deploys — a process-seeded hash would
/// reshuffle which teams sit under a given percentage. Raising the percentage
/// only ever adds teams to the secondary; it never moves routed teams back.
fn token_percentage_bucket(token: &str) -> u8 {
    let digest = Sha256::digest(token.as_bytes());
    let n = u64::from_be_bytes(digest[..8].try_into().expect("SHA-256 digest is 32 bytes"));
    (n % 100) as u8
}

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "false")]
    pub print_sink: bool,

    #[envconfig(default = "false")]
    pub noop_sink: bool,

    #[envconfig(default = "127.0.0.1:3000")]
    pub address: SocketAddr,

    pub redis_url: String,

    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,

    #[envconfig(default = "false")]
    pub global_rate_limit_enabled: bool,

    /// When true, the global rate limiter evaluates and emits metrics/logs
    /// but does not enforce (events pass through as if not limited).
    #[envconfig(default = "false")]
    pub global_rate_limit_dry_run: bool,

    /// Sliding window interval to apply global rate limiting threshold to
    #[envconfig(default = "60")]
    pub global_rate_limit_window_interval_secs: u64,

    /// Max staleness before re-sync with Redis (seconds)
    #[envconfig(default = "15")]
    pub global_rate_limit_sync_interval_secs: u64,

    /// Background task cadence for pipeline reads + writes (milliseconds)
    #[envconfig(default = "1000")]
    pub global_rate_limit_tick_interval_ms: u64,

    // --- Token+DistinctId limiter config ---
    /// Per-(token, distinct_id) rate limit threshold per window interval
    /// Note: default is too high to trigger limiting in production
    #[envconfig(default = "300000")]
    pub global_rate_limit_token_distinctid_threshold: u64,

    /// CSV list of key=value pairs for custom per-(token, distinct_id) thresholds
    pub global_rate_limit_token_distinctid_overrides_csv: Option<String>,

    /// Max local cache entries for the per-(token, distinct_id) limiter
    #[envconfig(default = "5000000")]
    pub global_rate_limit_token_distinctid_local_cache_max_entries: u64,

    // --- Token-only limiter config (not currently used in production, retained for new_token()) ---
    /// Per-token rate limit threshold per window interval
    /// Note: default is too high to trigger limiting in production
    #[envconfig(default = "5000000")]
    pub global_rate_limit_token_threshold: u64,

    /// CSV list of key=value pairs for custom per-token thresholds
    pub global_rate_limit_token_overrides_csv: Option<String>,

    /// Max local cache entries for the per-token limiter
    #[envconfig(default = "300000")]
    pub global_rate_limit_token_local_cache_max_entries: u64,

    /// Optional dedicated Redis URL for global rate limiter.
    /// If set, creates a separate Redis client for the limiter.
    /// Falls back to the shared redis_url if unset.
    pub global_rate_limit_redis_url: Option<String>,

    /// Optional Redis reader URL for global rate limiter (replica).
    /// When set alongside global_rate_limit_redis_url, creates a ReadWriteClient
    /// that routes reads to replicas and writes to the primary.
    pub global_rate_limit_redis_reader_url: Option<String>,

    /// Response timeout for dedicated global rate limiter Redis (milliseconds).
    /// Defaults to redis_response_timeout_ms if unset.
    pub global_rate_limit_redis_response_timeout_ms: Option<u64>,

    /// Connection timeout for dedicated global rate limiter Redis (milliseconds).
    /// Defaults to redis_connection_timeout_ms if unset.
    pub global_rate_limit_redis_connection_timeout_ms: Option<u64>,

    /// Redis key holding the dynamic custom per-key rate-limit thresholds
    /// (JSON object of `{key: threshold}`), written by Django. When set, the
    /// per-(token, distinct_id) limiter refreshes its custom thresholds from
    /// this key on a timer, overriding the static CSV overrides. Sourced from
    /// the same Redis as event restrictions (`event_restrictions_redis_url`).
    /// When unset, the limiter uses only the static CSV overrides.
    pub global_rate_limit_custom_threshold_key: Option<String>,

    /// How often to refresh the dynamic custom thresholds from Redis (seconds).
    #[envconfig(default = "60")]
    pub global_rate_limit_custom_threshold_refresh_secs: u64,

    // Event restrictions configuration (reads from Redis, synced by Django)
    #[envconfig(default = "false")]
    pub event_restrictions_enabled: bool,

    /// Redis URL for event restrictions (separate from main redis_url)
    pub event_restrictions_redis_url: Option<String>,

    #[envconfig(default = "30")]
    pub event_restrictions_refresh_interval_secs: u64,

    #[envconfig(default = "300")]
    pub event_restrictions_fail_open_after_secs: u64,

    pub otel_url: Option<String>,

    #[envconfig(default = "false")]
    pub overflow_enabled: bool,

    #[envconfig(default = "false")]
    pub overflow_preserve_partition_locality: bool,

    #[envconfig(default = "100")]
    pub overflow_per_second_limit: NonZeroU32,

    #[envconfig(default = "1000")]
    pub overflow_burst_limit: NonZeroU32,

    pub ingestion_force_overflow_by_token_distinct_id: Option<String>, // Comma-delimited keys

    pub drop_events_by_token_distinct_id: Option<String>, // "<token>:<distinct_id or *>,<distinct_id or *>;<token>..."

    #[envconfig(default = "false")]
    pub enable_historical_rerouting: bool,

    #[envconfig(default = "1")]
    pub historical_rerouting_threshold_days: i64,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "1.0")]
    pub otel_sampling_rate: f64,

    #[envconfig(default = "capture")]
    pub otel_service_name: String,

    // Used for integration tests
    #[envconfig(default = "true")]
    pub export_prometheus: bool,
    pub redis_key_prefix: Option<String>,

    #[envconfig(default = "events")]
    pub capture_mode: CaptureMode,

    pub concurrency_limit: Option<usize>,

    #[envconfig(default = "false")]
    pub s3_fallback_enabled: bool,
    pub s3_fallback_bucket: Option<String>,
    pub s3_fallback_endpoint: Option<String>,

    #[envconfig(default = "")]
    pub s3_fallback_prefix: String,

    #[envconfig(default = "false")]
    pub is_mirror_deploy: bool,

    #[envconfig(default = "info")]
    pub log_level: Level,

    // deploy var [0.0..100.0] to sample behavior of interest for verbose logging
    #[envconfig(default = "0.0")]
    pub verbose_sample_percent: f32,

    // AI endpoint size limits
    #[envconfig(default = "26214400")] // 25MB in bytes
    pub ai_max_sum_of_parts_bytes: usize,

    // AI endpoint S3 blob storage configuration
    pub ai_s3_bucket: Option<String>,
    #[envconfig(default = "llma/")]
    pub ai_s3_prefix: String,
    pub ai_s3_endpoint: Option<String>,
    #[envconfig(default = "us-east-1")]
    pub ai_s3_region: String,
    pub ai_s3_access_key_id: Option<String>,
    pub ai_s3_secret_access_key: Option<String>,

    // HMAC-SHA256 key shared with the AI gateway. When set, $ai_generation events
    // carrying a valid PostHog-Ai-Gateway-* signature are stamped verified and
    // exempted from the llm_events quota limiter. Unset disables verification
    // (all $ai_gateway* props are stripped as untrusted).
    pub ai_gateway_signing_secret: Option<String>,

    // --- AI secondary sink (e.g. WarpStream cluster) routing ---
    /// `primary` keeps all AI events on the primary sink; `secondary_allowlist`
    /// sends only `ai_secondary_allowlist_tokens` to the secondary; `secondary`
    /// sends every AI event to the secondary. `secondary_percentage` is not
    /// supported here (it exists for `capture_analytics_ai_events_mode`).
    /// Only consulted in `CaptureMode::Ai`.
    #[envconfig(default = "primary")]
    pub ai_sink_mode: AiSinkMode,

    /// Comma-separated tokens routed to the secondary AI sink when
    /// `ai_sink_mode = secondary_allowlist`.
    pub ai_secondary_allowlist_tokens: Option<String>,

    /// Secondary AI Kafka cluster connection. When `ai_sink_mode` is not
    /// `primary`, `ai_secondary_kafka_hosts` and `ai_secondary_kafka_topic` are
    /// required; the secondary producer inherits all other tuning from `kafka`.
    pub ai_secondary_kafka_hosts: Option<String>,
    pub ai_secondary_kafka_topic: Option<String>,
    #[envconfig(default = "false")]
    pub ai_secondary_kafka_tls: bool,
    #[envconfig(default = "")]
    pub ai_secondary_kafka_client_id: String,

    // --- Dedicated $ai_* topic routing on analytics deployments ---
    /// Routing mode for `$ai_*` events into the dedicated AI topic
    /// (`kafka.capture_analytics_ai_events_topic`, i.e. `CAPTURE_ANALYTICS_AI_EVENTS_TOPIC`): `primary` (default)
    /// diverts nothing, `secondary` diverts all `$ai_*` events,
    /// `secondary_allowlist` diverts only tokens listed in
    /// `capture_analytics_ai_events_allowlist_tokens`, and `secondary_percentage`
    /// diverts the `capture_analytics_ai_events_percentage` share of teams (by
    /// token hash). The topic is required whenever the mode is not `primary`.
    #[envconfig(default = "primary")]
    pub capture_analytics_ai_events_mode: AiSinkMode,

    /// Comma-separated project API tokens whose `$ai_*` events are diverted to
    /// `capture_analytics_ai_events_topic` when `capture_analytics_ai_events_mode` is `secondary_allowlist`.
    pub capture_analytics_ai_events_allowlist_tokens: Option<String>,

    /// Percent of teams (0-100, by deterministic token hash) whose `$ai_*`
    /// events are diverted to `capture_analytics_ai_events_topic`. Required
    /// when `capture_analytics_ai_events_mode` is `secondary_percentage`.
    pub capture_analytics_ai_events_percentage: Option<u8>,

    // HTTP/1 header read timeout in milliseconds - closes connections that don't
    // send complete headers within this duration (slow loris protection).
    // Set env var to enable; unset to disable.
    pub http1_header_read_timeout_ms: Option<u64>,

    // Body chunk read timeout in milliseconds. If a client stops sending data
    // for this duration mid-upload, the request is aborted with 408 to avoid
    // pointless gateway retries of stalled mobile requests that can't succeed.
    // Set env var to enable; unset to disable (existing behavior).
    pub body_chunk_read_timeout_ms: Option<u64>,

    // Initial buffer size for body reads in KB. The buffer starts at this size
    // (or the request limit, whichever is smaller) and grows as needed.
    #[envconfig(default = "256")]
    pub body_read_chunk_size_kb: usize,

    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    /// Comma-separated list of active v1 sinks (e.g. "msk" or "msk,ws").
    /// Parsed by `v1::sinks::load_sinks()` after `Config::init_from_env()`.
    /// Empty string means the v1 sink layer is disabled.
    #[envconfig(default = "")]
    pub capture_v1_sinks: String,

    /// Maximum compressed (wire) body size the v1 endpoint will accept (bytes).
    #[envconfig(default = "10485760")]
    pub capture_v1_max_compressed_body_bytes: usize,

    /// Maximum decompressed body size the v1 endpoint will accept (bytes).
    #[envconfig(default = "52428800")]
    pub capture_v1_max_decompressed_body_bytes: usize,

    /// Batch size threshold for parallel scatter-gather serialization; 0 disables fanout.
    #[envconfig(default = "8")]
    pub capture_v1_scatter_gather_min_batch: usize,

    // --- Ingestion warnings emitter (fire-and-forget, best-effort) ---
    // Warnings are emitted as `$$client_ingestion_warning` events onto the
    // existing `client_ingestion_warning` topic, by default on the main event
    // cluster: absent the warnings-cluster overrides below, the producer
    // reuses the main cluster's hosts/TLS — but it gets its OWN dedicated
    // `common_kafka::config::KafkaConfig` (below) with fire-and-forget
    // acks/retries and a small queue, so a saturated or slow warnings topic
    // can never behave like — or contend with — the main event producer.
    // Defaults off (fail open).
    #[envconfig(default = "false")]
    pub capture_ingestion_warnings_enabled: bool,

    // The producer's fire-and-forget policy (acks, retries, linger, queue
    // depth in messages, message timeout) is fixed in code — see the
    // `WARNINGS_KAFKA_*` constants in `setup.rs` — not env-configurable, since
    // those define the "a warning is worth less than the cost of retrying it"
    // contract rather than operator knobs. Only the two capacity/safety limits
    // below stay tunable.
    #[envconfig(default = "16")]
    pub capture_ingestion_warnings_kafka_queue_mib: u32,

    // rdkafka "message.max.bytes": a hard per-message ceiling, independent of
    // the main producer's, so an oversized warning envelope (e.g. built from
    // attacker-controlled input) cannot inflate past this regardless of what
    // the main event producer allows.
    #[envconfig(default = "1048576")]
    pub capture_ingestion_warnings_kafka_message_max_bytes: u32,

    // The warnings emitter's own destination. It runs in the v1 analytics
    // handler but is independent of the v0 `KAFKA_*` block: it reads only these
    // three vars, never `kafka_hosts` / `kafka_tls` /
    // `kafka_client_ingestion_warning_topic`. charts sets all three per env,
    // pointed at the MSK cluster the clientwarnings consumer reads from.
    //
    // Defaults are inert on purpose: empty hosts or topic makes
    // `create_ingestion_warning_emitter` report the emitter disabled and return
    // (fail open) rather than produce to a wrong or empty destination. TLS is a
    // separate knob from hosts because the warnings cluster's TLS requirement
    // need not match the main one — capture-ai is the live example, with a
    // PLAINTEXT WarpStream event sink and a TLS MSK warnings destination.
    #[envconfig(default = "")]
    pub capture_ingestion_warnings_kafka_topic: String,
    #[envconfig(default = "")]
    pub capture_ingestion_warnings_kafka_hosts: String,
    #[envconfig(default = "false")]
    pub capture_ingestion_warnings_kafka_tls: bool,
}

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic
    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes
    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds
    #[envconfig(default = "1000000")]
    pub kafka_producer_message_max_bytes: u32, // message.max.bytes - max kafka message size we will produce
    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd
    /// Application-level compression for session replay (snapshot) Kafka payloads.
    /// Independent of broker-level compression; consumers must detect and decompress.
    /// Set to "lz4" to enable. Default "none" for safe rollout and rollback.
    #[envconfig(default = "none")]
    pub kafka_replay_envelope_compression: EnvelopeCompression,
    pub kafka_hosts: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_topic: String,
    #[envconfig(default = "ingestion-traces")]
    pub kafka_traces_topic: String,
    #[envconfig(default = "ingestion-metrics")]
    pub kafka_metrics_topic: String,
    #[envconfig(default = "events_plugin_ingestion_overflow")]
    pub kafka_overflow_topic: String,
    #[envconfig(default = "events_plugin_ingestion_historical")]
    pub kafka_historical_topic: String,
    #[envconfig(default = "ingestion-clientwarnings-main-1")]
    pub kafka_client_ingestion_warning_topic: String,
    #[envconfig(default = "error_tracking_events")]
    pub kafka_error_tracking_topic: String,
    #[envconfig(default = "heatmaps_ingestion")]
    pub kafka_heatmaps_topic: String,
    #[envconfig(default = "session_recording_snapshot_item_overflow")]
    pub kafka_replay_overflow_topic: String,
    #[envconfig(default = "events_plugin_ingestion_dlq")]
    pub kafka_dlq_topic: String,
    /// Dedicated Kafka topic for `$ai_*` events (env: `CAPTURE_ANALYTICS_AI_EVENTS_TOPIC`).
    /// Unlike the `ai_secondary_*` family on `Config` (which picks a secondary
    /// CLUSTER on `CaptureMode::Ai` deployments), this picks a TOPIC on the
    /// same sink: per `Config::capture_analytics_ai_events_mode`, both the v0 pipeline
    /// (via `DataType::AiEvents`) and the v1 pipeline (via
    /// `Destination::AiEvents`) divert `$ai_*` events here instead of the
    /// analytics main topic. Setup also injects it into every v1 sink config.
    pub capture_analytics_ai_events_topic: Option<String>,
    /// Optional overflow topic for the AI lane (env: `CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC`).
    /// Unset means AI events never overflow (the pre-overflow behavior). When
    /// set, the AI lane participates in the same overflow limiter and
    /// restriction-driven force_overflow as the analytics main lane, rerouting
    /// here instead of the analytics overflow topic. Settable in advance of
    /// the AI routing mode, so no startup validation ties it to the mode.
    pub capture_analytics_ai_events_overflow_topic: Option<String>,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
    #[envconfig(default = "")]
    pub kafka_client_id: String,
    #[envconfig(default = "2")]
    pub kafka_producer_max_retries: u32,
    #[envconfig(default = "all")]
    pub kafka_producer_acks: String,
    // interval between metadata refreshes from the Kafka brokers
    #[envconfig(default = "20000")]
    pub kafka_topic_metadata_refresh_interval_ms: u32,
    // default is 3x metadata refresh interval so we maintain that here
    #[envconfig(default = "60000")]
    pub kafka_metadata_max_age_ms: u32,
    #[envconfig(default = "60000")] // lib default, can tweak in env overrides
    pub kafka_socket_timeout_ms: u32,
    #[envconfig(default = "10000")] // librdkafka default
    pub kafka_producer_batch_num_messages: u32, // batch.num.messages - max messages per batch
    #[envconfig(default = "1000000")] // librdkafka default
    pub kafka_producer_batch_size: u32, // batch.size - max batch size in bytes
    #[envconfig(default = "1000000")] // librdkafka default
    pub kafka_producer_max_in_flight_requests: u32, // max.in.flight.requests.per.connection
    #[envconfig(default = "10")] // librdkafka default
    pub kafka_producer_sticky_partitioning_linger_ms: u32, // sticky.partitioning.linger.ms
    #[envconfig(default = "false")] // librdkafka default
    pub kafka_producer_enable_idempotence: bool, // enable.idempotence
    #[envconfig(default = "murmur2_random")]
    pub kafka_producer_partitioner: String, // partitioner
    #[envconfig(default = "")]
    pub kafka_broker_address_family: String, // broker.address.family - v4, v6, any; empty = don't set
    #[envconfig(default = "true")] // librdkafka default
    pub kafka_log_connection_close: bool, // log.connection.close
    #[envconfig(default = "100000")] // librdkafka default
    pub kafka_producer_queue_buffering_max_messages: u32, // queue.buffering.max.messages
    #[envconfig(default = "1000")] // librdkafka default
    pub kafka_retry_backoff_max_ms: u32, // retry.backoff.max.ms
    #[envconfig(default = "0")] // librdkafka default (OS auto-tune)
    pub kafka_socket_send_buffer_bytes: u32, // socket.send.buffer.bytes
    #[envconfig(default = "0")] // librdkafka default (OS auto-tune)
    pub kafka_socket_receive_buffer_bytes: u32, // socket.receive.buffer.bytes

    // Traces-cluster overrides (consumed by capture-logs). When unset, the
    // traces producer reuses the corresponding `kafka_*` value above.
    pub kafka_traces_hosts: Option<String>,
    pub kafka_traces_tls: Option<bool>,
    pub kafka_traces_client_id: Option<String>,
    pub kafka_traces_compression_codec: Option<String>,
    pub kafka_traces_producer_acks: Option<String>,
    pub kafka_traces_producer_linger_ms: Option<u32>,
    pub kafka_traces_producer_queue_mib: Option<u32>,
    pub kafka_traces_message_timeout_ms: Option<u32>,
    pub kafka_traces_producer_message_max_bytes: Option<u32>,
    pub kafka_traces_producer_max_retries: Option<u32>,
    pub kafka_traces_topic_metadata_refresh_interval_ms: Option<u32>,
    pub kafka_traces_metadata_max_age_ms: Option<u32>,

    // Metrics-cluster overrides (consumed by capture-logs). When unset, the
    // metrics producer reuses the corresponding `kafka_*` value above.
    pub kafka_metrics_hosts: Option<String>,
    pub kafka_metrics_tls: Option<bool>,
    pub kafka_metrics_client_id: Option<String>,
    pub kafka_metrics_compression_codec: Option<String>,
    pub kafka_metrics_producer_acks: Option<String>,
    pub kafka_metrics_producer_linger_ms: Option<u32>,
    pub kafka_metrics_producer_queue_mib: Option<u32>,
    pub kafka_metrics_message_timeout_ms: Option<u32>,
    pub kafka_metrics_producer_message_max_bytes: Option<u32>,
    pub kafka_metrics_producer_max_retries: Option<u32>,
    pub kafka_metrics_topic_metadata_refresh_interval_ms: Option<u32>,
    pub kafka_metrics_metadata_max_age_ms: Option<u32>,
}

#[cfg(test)]
mod tests {
    use super::{AiRouting, AiSinkMode, CaptureMode, Config};
    use std::collections::HashMap;
    use std::str::FromStr;

    fn required_config_env() -> HashMap<String, String> {
        [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("KAFKA_HOSTS", "localhost:9092"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
    }

    #[test]
    fn capture_analytics_ai_events_topic_defaults() {
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&required_config_env()).unwrap();
        assert_eq!(config.kafka.capture_analytics_ai_events_topic, None);
        assert_eq!(config.capture_analytics_ai_events_mode, AiSinkMode::Primary);
        assert_eq!(config.capture_analytics_ai_events_allowlist_tokens, None);
        assert_eq!(config.capture_analytics_ai_events_percentage, None);
    }

    #[test]
    fn capture_analytics_ai_events_percentage_parses() {
        let mut env = required_config_env();
        env.insert(
            "CAPTURE_ANALYTICS_AI_EVENTS_MODE".into(),
            "secondary_percentage".into(),
        );

        // 150 parses here on purpose: the env layer only types the value, the
        // 0-100 range check lives in setup so it can refuse to start.
        for (raw, expected) in [("0", 0u8), ("25", 25), ("100", 100), ("150", 150)] {
            env.insert("CAPTURE_ANALYTICS_AI_EVENTS_PERCENTAGE".into(), raw.into());
            let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
            assert_eq!(
                config.capture_analytics_ai_events_mode,
                AiSinkMode::SecondaryPercentage
            );
            assert_eq!(
                config.capture_analytics_ai_events_percentage,
                Some(expected),
                "raw={raw}"
            );
        }
    }

    #[test]
    fn capture_analytics_ai_events_percentage_rejects_malformed_values() {
        // Locks the fail-fast contract: the field is a typed u8, so malformed
        // env values abort startup. Loosening it (e.g. to a string parsed
        // later) would let a broken rollout config through init silently.
        for bad in ["", " 25 ", "abc", "-1", "25%", "12.5", "300"] {
            let mut env = required_config_env();
            env.insert("CAPTURE_ANALYTICS_AI_EVENTS_PERCENTAGE".into(), bad.into());
            let result: Result<Config, _> = envconfig::Envconfig::init_from_hashmap(&env);
            assert!(result.is_err(), "expected init to fail for {bad:?}");
        }
    }

    #[test]
    fn capture_analytics_ai_events_topic_parses() {
        let mut env = required_config_env();
        env.insert(
            "CAPTURE_ANALYTICS_AI_EVENTS_TOPIC".into(),
            "ai_events".into(),
        );
        env.insert(
            "CAPTURE_ANALYTICS_AI_EVENTS_MODE".into(),
            "secondary_allowlist".into(),
        );
        env.insert(
            "CAPTURE_ANALYTICS_AI_EVENTS_ALLOWLIST_TOKENS".into(),
            "tok_a,tok_b".into(),
        );
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        assert_eq!(
            config.kafka.capture_analytics_ai_events_topic.as_deref(),
            Some("ai_events")
        );
        assert_eq!(
            config.capture_analytics_ai_events_mode,
            AiSinkMode::SecondaryAllowlist
        );
        assert_eq!(
            config
                .capture_analytics_ai_events_allowlist_tokens
                .as_deref(),
            Some("tok_a,tok_b")
        );
    }

    #[test]
    fn capture_mode_from_str_and_tag_roundtrip() {
        // Locks the CAPTURE_MODE env contract, including the new `import` mode
        // and case/whitespace handling, plus the tag used as a metric label.
        let ok = [
            ("events", CaptureMode::Events, "events"),
            ("Recordings", CaptureMode::Recordings, "recordings"),
            (" ai ", CaptureMode::Ai, "ai"),
            ("import", CaptureMode::Import, "import"),
            ("IMPORT", CaptureMode::Import, "import"),
        ];
        for (input, expected, tag) in ok {
            let parsed = CaptureMode::from_str(input).unwrap();
            assert_eq!(parsed, expected, "input={input}");
            assert_eq!(parsed.as_tag(), tag, "input={input}");
        }

        for bad in ["", "imports", "backfill", "historical"] {
            assert!(
                CaptureMode::from_str(bad).is_err(),
                "expected err for {bad:?}"
            );
        }
    }

    #[test]
    fn capture_mode_import_policy_differs_from_events() {
        // The whole point of Import mode: it skips the global rate limiter and
        // drops non-historical batches, while every other mode does neither.
        assert!(!CaptureMode::Import.applies_global_rate_limit());
        assert!(CaptureMode::Import.requires_historical_migration());

        for mode in [
            CaptureMode::Events,
            CaptureMode::Recordings,
            CaptureMode::Ai,
        ] {
            assert!(
                mode.applies_global_rate_limit(),
                "{mode:?} should apply GRL"
            );
            assert!(
                !mode.requires_historical_migration(),
                "{mode:?} should not require historical_migration"
            );
        }
    }

    #[test]
    fn ai_sink_mode_from_str() {
        // Locks the AI_SINK_MODE env contract: accepted spellings (incl. the
        // dash/underscore allowlist alias), case-insensitivity, and rejection
        // of anything else.
        let ok = [
            ("primary", AiSinkMode::Primary),
            ("PRIMARY", AiSinkMode::Primary),
            ("secondary", AiSinkMode::Secondary),
            (" Secondary ", AiSinkMode::Secondary),
            ("secondary_allowlist", AiSinkMode::SecondaryAllowlist),
            ("secondary-allowlist", AiSinkMode::SecondaryAllowlist),
            ("Secondary_Allowlist", AiSinkMode::SecondaryAllowlist),
            ("secondary_percentage", AiSinkMode::SecondaryPercentage),
            ("secondary-percentage", AiSinkMode::SecondaryPercentage),
            ("Secondary_Percentage", AiSinkMode::SecondaryPercentage),
        ];
        for (input, expected) in ok {
            assert_eq!(
                AiSinkMode::from_str(input).unwrap(),
                expected,
                "input={input}"
            );
        }

        for bad in [
            "",
            "secondaryallowlist",
            "secondarypercentage",
            "percentage",
            "warpstream",
            "allowlist",
        ] {
            assert!(
                AiSinkMode::from_str(bad).is_err(),
                "expected err for {bad:?}"
            );
        }
    }

    #[test]
    fn ai_routing_routes_to_secondary() {
        // Locks the routing decision: a flipped arm or the allowlist being
        // consulted in the wrong variant would send AI traffic to the wrong
        // cluster mid-cutover.
        use std::collections::HashSet;
        let allowlist: HashSet<String> = ["tok_a".to_string()].into_iter().collect();

        // (routing, token, expected_secondary)
        let cases = [
            (AiRouting::Primary, "tok_a", false),
            (AiRouting::Secondary, "tok_a", true),
            (AiRouting::Secondary, "unlisted", true),
            (
                AiRouting::SecondaryAllowlist(allowlist.clone()),
                "tok_a",
                true,
            ),
            (AiRouting::SecondaryAllowlist(allowlist), "unlisted", false),
            (
                AiRouting::SecondaryAllowlist(HashSet::new()),
                "tok_a",
                false,
            ),
            (AiRouting::SecondaryPercentage(0), "tok_a", false),
            (AiRouting::SecondaryPercentage(100), "tok_a", true),
        ];
        for (routing, token, expected) in cases {
            assert_eq!(
                routing.routes_to_secondary(token),
                expected,
                "routing={routing:?} token={token}"
            );
        }
    }

    #[test]
    fn token_percentage_buckets_are_stable() {
        // The bucket values are part of the rollout contract: a hash change
        // reshuffles which teams sit under a given percentage mid-rollout,
        // flipping already-migrated teams back and forth between destinations.
        // These pin the exact SHA-256-derived buckets for fixed tokens.
        let buckets = [("tok_a", 27), ("tok_b", 40), ("phc_other", 29)];
        for (token, expected) in buckets {
            assert_eq!(
                super::token_percentage_bucket(token),
                expected,
                "token={token}"
            );
        }
    }

    #[test]
    fn secondary_percentage_routes_exactly_at_bucket_boundary() {
        // `bucket < percentage` makes the split monotonic: raising the
        // percentage only ever adds teams to the secondary. A flipped
        // comparison (or off-by-one) would silently invert who migrates first.
        let bucket = super::token_percentage_bucket("tok_a");
        assert!(!AiRouting::SecondaryPercentage(bucket).routes_to_secondary("tok_a"));
        assert!(AiRouting::SecondaryPercentage(bucket + 1).routes_to_secondary("tok_a"));
    }
}
