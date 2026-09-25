use std::{net::SocketAddr, num::NonZeroU32};

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;
use tracing::Level;

use crate::producers::ProducerName;
use crate::v0_request::AiLanePredicate;

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

    /// Minimum effective event count before a key earns a Redis sync. Keys below
    /// this cannot be limited whatever other nodes report, so syncing them costs
    /// two Redis keys per tick for no enforcement value. With an unbounded key
    /// space this is what keeps the pipeline sized to enforceable keys rather
    /// than to total traffic. 0 syncs every key.
    ///
    /// The level is per-pod, so this must stay well under
    /// `threshold / pod_count` or a key sitting at the threshold but spread
    /// evenly across the fleet would never sync and could never be limited.
    #[envconfig(default = "10")]
    pub global_rate_limit_min_sync_floor: u64,

    /// Max keys drained from the pending-sync set per tick. Excess stays queued,
    /// so a backlog shows up as sync staleness rather than a tick that overruns
    /// its interval.
    #[envconfig(default = "20000")]
    pub global_rate_limit_max_sync_keys_per_tick: usize,

    /// Max Redis keys per individual command. Reads cost two keys per entity, so
    /// an entity chunk is half this. Bounds how long any single command can take,
    /// which is what the per-command timeouts below are budgeting for.
    #[envconfig(default = "2000")]
    pub global_rate_limit_max_keys_per_command: usize,

    /// How many chunked commands may be in flight at once per Redis instance.
    #[envconfig(default = "4")]
    pub global_rate_limit_max_concurrent_commands: usize,

    /// Max distinct (key, epoch) entries held in the deferred write batch per
    /// limiter. Merges are always accepted; at the cap, updates for new keys
    /// are dropped and counted (fail-open). Bounds limiter memory under
    /// unique-key floods that outrun the per-tick write drain.
    #[envconfig(default = "200000")]
    pub global_rate_limit_max_write_batch_entries: usize,

    /// Max keys held in the pending-sync set per limiter. At the cap, new sync
    /// requests drop and re-queue on the key's next request (fail-open).
    /// Bounds limiter memory alongside the write-batch cap.
    #[envconfig(default = "200000")]
    pub global_rate_limit_max_pending_sync_entries: usize,

    /// How long a local cache entry survives regardless of access (seconds).
    /// Bounds how stale a key's cached count can be before it is rebuilt.
    #[envconfig(default = "600")]
    pub global_rate_limit_local_cache_ttl_secs: u64,

    /// Evict local cache entries not accessed within this window (seconds).
    /// This is the main lever on cache cardinality: with a key space dominated
    /// by one-shot identities, most entries are pure churn and hold a slot for
    /// the full idle window. Must stay at or above the rate-limit window, or
    /// entries expire inside the enforcement window and the limiter loses the
    /// counts it is supposed to be accumulating -- values below the window are
    /// clamped up, with a warning.
    #[envconfig(default = "300")]
    pub global_rate_limit_local_cache_idle_timeout_secs: u64,

    /// Timeout for a single global rate limiter Redis read command (milliseconds).
    #[envconfig(default = "250")]
    pub global_rate_limit_read_timeout_ms: u64,

    /// Timeout for a single global rate limiter Redis write command (milliseconds).
    #[envconfig(default = "250")]
    pub global_rate_limit_write_timeout_ms: u64,

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
    pub outputs: OutputsConfig,

    /// Application-level compression of session replay payloads, independent of
    /// broker-level compression. Consumers detect and decompress it.
    #[envconfig(from = "KAFKA_REPLAY_ENVELOPE_COMPRESSION", default = "none")]
    pub replay_envelope_compression: EnvelopeCompression,

    /// Refuse to boot when a registered output has an empty topic name (see
    /// `OutputTable::check_complete`). Off by default so that a deployment which
    /// blanks a topic it never produces to still boots.
    #[envconfig(from = "CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED", default = "false")]
    pub outputs_completeness_check_enabled: bool,

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

    /// Largest single AI-lane event this deployment accepts. Measured on the
    /// serialized event body, except on v1, which measures the properties blob
    /// — see [`crate::v0_request::exceeds_max_ai_event_bytes`]. `0` disables
    /// the ceiling.
    ///
    /// Set it below what the deployment's broker accepts, leaving room for the
    /// `CapturedEvent` envelope and the JSON-escaping of `data`:
    /// `KAFKA_INGESTION_PRODUCER_MESSAGE_MAX_BYTES` bounds the produced message, not the
    /// event inside it. capture-analytics needs a smaller value than capture-ai
    /// because its AI topic is on MSK.
    ///
    /// What an over-ceiling event gets back differs by path, because each one
    /// keeps its own convention:
    ///
    /// * `/i/v0/ai/batch` and the diverted legacy path — 413, whole request
    ///   refused, like every other oversize check there.
    /// * `/i/v1/analytics/events` — the one event is dropped and reported as
    ///   `ai_event_too_big` in the 200 body; the rest of the batch publishes.
    /// * `/i/v0/ai` (multipart) — 413, the endpoint's pre-existing behavior.
    /// * `/i/v0/ai/otel` — the span is shed and the export still succeeds. A
    ///   collector retries a rejected export, so refusing would stall every
    ///   span behind one that can never fit. That loss is invisible in the
    ///   response, so it raises a `MessageSizeTooLarge` ingestion warning.
    ///
    /// The legacy, v1, and OTEL paths count the loss under `ai_event_too_big`,
    /// on `capture_events_dropped_total` or `capture_v1_events_dropped`. The
    /// legacy path charges the whole batch, because the refusal loses every
    /// event in it, not just the offender. The multipart handler counts no
    /// drop at all: like every other error it raises, the refusal shows up
    /// only on `capture_error_by_stage_and_type`.
    /// Keep this under the deployment's `KAFKA_INGESTION_PRODUCER_MESSAGE_MAX_BYTES`.
    /// Above it the ceiling stops being a guard: capture reads the body, builds
    /// the event, and the producer refuses it anyway. A deployment that has not
    /// raised its producer cap wants a lower value than this default; the boot
    /// warning says so when the two are out of order.
    #[envconfig(default = "8388608")] // 8MiB
    pub ai_max_event_bytes: u64,

    /// AI lane membership: `allowlist` (exact `AI_EVENT_NAMES`) or `prefix` (any `$ai_*`).
    /// Set `prefix` only once the environment's AI ingestion pipeline admits by prefix,
    /// or it DLQs every unlisted `$ai_*` name capture diverts.
    #[envconfig(from = "CAPTURE_AI_LANE_PREDICATE", default = "allowlist")]
    pub ai_lane_predicate: AiLanePredicate,

    // HMAC-SHA256 key shared with the AI gateway. When set, $ai_generation events
    // carrying a valid PostHog-Ai-Gateway-* signature are stamped verified and
    // exempted from the llm_events quota limiter. Unset disables verification
    // (all $ai_gateway* props are stripped as untrusted).
    pub ai_gateway_signing_secret: Option<String>,

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

    // The warnings emitter's own destination. It serves every pipeline that
    // emits (v1 and legacy analytics, both AI endpoints, and replay) but reads
    // only these three vars, never the ingestion producer's settings or
    // `CAPTURE_OUTPUT_CLIENT_WARNINGS_TOPIC`. charts sets all three per env,
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

    /// Per-token byte/second budget for the AI lane. `0` disables the limiter.
    ///
    /// The budget is enforced fleet-wide by the global rate limiter, over the
    /// shared `GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS` sliding window, so the
    /// cap a token actually sees is this value times the window length. Within
    /// a window the token may spend the whole budget at once.
    #[envconfig(default = "0")]
    pub ai_byte_limit_per_second: u64,

    /// CSV list of `token=bytesPerSecond` pairs raising specific tokens' budgets.
    /// Same unit as `ai_byte_limit_per_second`.
    pub ai_byte_limit_overrides_csv: Option<String>,

    /// When true, the AI byte limiter evaluates and reports but does not drop.
    /// Separate from `global_rate_limit_dry_run` so this rollout and the
    /// token+distinct_id limiter's can move independently.
    #[envconfig(default = "false")]
    pub ai_byte_limit_dry_run: bool,

    /// Window the AI byte budget is enforced over. Falls back to
    /// `GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS` when unset.
    ///
    /// The AI byte budget is shared across capture deployments through one
    /// Redis counter, and the epoch key derives from this window, so every
    /// deployment must set the same value or the shared budget splits. Kept
    /// separate so the token+distinct_id window can be tuned per deployment.
    pub ai_byte_limit_window_interval_secs: Option<u64>,

    /// Max local cache entries for the AI byte limiter. Keyed per token, so this
    /// is bounded by the number of projects sending AI traffic — far smaller
    /// than the per-(token, distinct_id) limiter's key space.
    #[envconfig(default = "300000")]
    pub ai_byte_limit_local_cache_max_entries: u64,
}

/// Each output capture produces to: a topic and the named producer that
/// carries it, read from `CAPTURE_OUTPUT_<OUTPUT>_TOPIC` and
/// `CAPTURE_OUTPUT_<OUTPUT>_PRODUCER` as in Node.js ingestion's outputs.
#[derive(Envconfig, Clone)]
pub struct OutputsConfig {
    #[envconfig(
        from = "CAPTURE_OUTPUT_ANALYTICS_MAIN_TOPIC",
        default = "events_plugin_ingestion"
    )]
    pub analytics_main_topic: String,
    #[envconfig(from = "CAPTURE_OUTPUT_ANALYTICS_MAIN_PRODUCER", default = "INGESTION")]
    pub analytics_main_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_ANALYTICS_OVERFLOW_TOPIC",
        default = "events_plugin_ingestion_overflow"
    )]
    pub analytics_overflow_topic: String,
    #[envconfig(
        from = "CAPTURE_OUTPUT_ANALYTICS_OVERFLOW_PRODUCER",
        default = "INGESTION"
    )]
    pub analytics_overflow_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_ANALYTICS_HISTORICAL_TOPIC",
        default = "events_plugin_ingestion_historical"
    )]
    pub analytics_historical_topic: String,
    #[envconfig(
        from = "CAPTURE_OUTPUT_ANALYTICS_HISTORICAL_PRODUCER",
        default = "INGESTION"
    )]
    pub analytics_historical_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_SESSION_REPLAY_MAIN_TOPIC",
        default = "events_plugin_ingestion"
    )]
    pub session_replay_main_topic: String,
    #[envconfig(
        from = "CAPTURE_OUTPUT_SESSION_REPLAY_MAIN_PRODUCER",
        default = "INGESTION"
    )]
    pub session_replay_main_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_SESSION_REPLAY_OVERFLOW_TOPIC",
        default = "session_recording_snapshot_item_overflow"
    )]
    pub session_replay_overflow_topic: String,
    #[envconfig(
        from = "CAPTURE_OUTPUT_SESSION_REPLAY_OVERFLOW_PRODUCER",
        default = "INGESTION"
    )]
    pub session_replay_overflow_producer: ProducerName,
    #[envconfig(from = "CAPTURE_OUTPUT_HEATMAPS_TOPIC", default = "heatmaps_ingestion")]
    pub heatmaps_topic: String,
    #[envconfig(from = "CAPTURE_OUTPUT_HEATMAPS_PRODUCER", default = "INGESTION")]
    pub heatmaps_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_CLIENT_WARNINGS_TOPIC",
        default = "ingestion-clientwarnings-main-1"
    )]
    pub client_warnings_topic: String,
    #[envconfig(
        from = "CAPTURE_OUTPUT_CLIENT_WARNINGS_PRODUCER",
        default = "INGESTION"
    )]
    pub client_warnings_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_ERROR_TRACKING_TOPIC",
        default = "error_tracking_events"
    )]
    pub error_tracking_topic: String,
    #[envconfig(from = "CAPTURE_OUTPUT_ERROR_TRACKING_PRODUCER", default = "INGESTION")]
    pub error_tracking_producer: ProducerName,
    #[envconfig(
        from = "CAPTURE_OUTPUT_DLQ_TOPIC",
        default = "events_plugin_ingestion_dlq"
    )]
    pub dlq_topic: String,
    #[envconfig(from = "CAPTURE_OUTPUT_DLQ_PRODUCER", default = "INGESTION")]
    pub dlq_producer: ProducerName,
    /// The v0 (`DataType::AiEvents`) and v1 (`Destination::AiEvents`) pipelines
    /// divert AI events here instead of the main topic on every deployment,
    /// capture-ai included. Setup also injects it into every v1 sink config.
    #[envconfig(
        from = "CAPTURE_OUTPUT_AI_MAIN_TOPIC",
        default = "events_plugin_ingestion_ai"
    )]
    pub ai_main_topic: String,
    #[envconfig(from = "CAPTURE_OUTPUT_AI_MAIN_PRODUCER", default = "INGESTION")]
    pub ai_main_producer: ProducerName,
    /// Unset means AI events never overflow. When set, the AI lane uses the
    /// analytics main lane's overflow limiter and restriction-driven
    /// force_overflow, and reroutes here. Import mode refuses it at boot
    /// because imports must never overflow.
    #[envconfig(from = "CAPTURE_OUTPUT_AI_OVERFLOW_TOPIC")]
    pub ai_overflow_topic: Option<String>,
    #[envconfig(from = "CAPTURE_OUTPUT_AI_OVERFLOW_PRODUCER", default = "INGESTION")]
    pub ai_overflow_producer: ProducerName,
    /// Carries event-restriction redirects to an admin-supplied topic.
    #[envconfig(from = "CAPTURE_OUTPUT_CUSTOM_PRODUCER", default = "INGESTION")]
    pub custom_producer: ProducerName,
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
    pub kafka_hosts: String,
    #[envconfig(default = "events_plugin_ingestion")]
    pub kafka_topic: String,
    #[envconfig(default = "ingestion-traces")]
    pub kafka_traces_topic: String,
    #[envconfig(default = "ingestion-metrics")]
    pub kafka_metrics_topic: String,
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
    use super::{CaptureMode, Config};
    use crate::producers::ProducerName;
    use crate::v0_request::AiLanePredicate;
    use std::collections::HashMap;
    use std::str::FromStr;

    fn required_config_env() -> HashMap<String, String> {
        [("REDIS_URL", "redis://localhost:6379/")]
            .into_iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn ai_output_topic_defaults() {
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&required_config_env()).unwrap();
        assert_eq!(config.outputs.ai_main_topic, "events_plugin_ingestion_ai");
        assert_eq!(config.outputs.ai_overflow_topic, None);
    }

    #[rstest::rstest]
    #[case("CAPTURE_OUTPUT_ANALYTICS_MAIN_TOPIC", |c: &Config| c.outputs.analytics_main_topic.clone())]
    #[case("CAPTURE_OUTPUT_ANALYTICS_OVERFLOW_TOPIC", |c: &Config| c.outputs.analytics_overflow_topic.clone())]
    #[case("CAPTURE_OUTPUT_ANALYTICS_HISTORICAL_TOPIC", |c: &Config| c.outputs.analytics_historical_topic.clone())]
    #[case("CAPTURE_OUTPUT_SESSION_REPLAY_MAIN_TOPIC", |c: &Config| c.outputs.session_replay_main_topic.clone())]
    #[case("CAPTURE_OUTPUT_SESSION_REPLAY_OVERFLOW_TOPIC", |c: &Config| c.outputs.session_replay_overflow_topic.clone())]
    #[case("CAPTURE_OUTPUT_HEATMAPS_TOPIC", |c: &Config| c.outputs.heatmaps_topic.clone())]
    #[case("CAPTURE_OUTPUT_CLIENT_WARNINGS_TOPIC", |c: &Config| c.outputs.client_warnings_topic.clone())]
    #[case("CAPTURE_OUTPUT_ERROR_TRACKING_TOPIC", |c: &Config| c.outputs.error_tracking_topic.clone())]
    #[case("CAPTURE_OUTPUT_DLQ_TOPIC", |c: &Config| c.outputs.dlq_topic.clone())]
    #[case("CAPTURE_OUTPUT_AI_MAIN_TOPIC", |c: &Config| c.outputs.ai_main_topic.clone())]
    #[case("CAPTURE_OUTPUT_AI_OVERFLOW_TOPIC", |c: &Config| c.outputs.ai_overflow_topic.clone().unwrap_or_default())]
    fn topic_env_var_binds_to_its_field(
        #[case] env_var: &str,
        #[case] field: fn(&Config) -> String,
    ) {
        let mut env = required_config_env();
        env.insert(env_var.into(), "configured_topic".into());
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        assert_eq!(field(&config), "configured_topic");
    }

    #[rstest::rstest]
    #[case("KAFKA_TOPIC")]
    #[case("KAFKA_OVERFLOW_TOPIC")]
    #[case("KAFKA_HISTORICAL_TOPIC")]
    #[case("KAFKA_CLIENT_INGESTION_WARNING_TOPIC")]
    #[case("KAFKA_ERROR_TRACKING_TOPIC")]
    #[case("KAFKA_HEATMAPS_TOPIC")]
    #[case("KAFKA_REPLAY_OVERFLOW_TOPIC")]
    #[case("KAFKA_DLQ_TOPIC")]
    #[case("CAPTURE_ANALYTICS_AI_EVENTS_TOPIC")]
    #[case("CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC")]
    fn legacy_topic_env_var_is_not_read(#[case] env_var: &str) {
        let mut env = required_config_env();
        env.insert(env_var.into(), "legacy_topic".into());
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        let outputs = &config.outputs;
        let topics = [
            outputs.analytics_main_topic.as_str(),
            outputs.analytics_overflow_topic.as_str(),
            outputs.analytics_historical_topic.as_str(),
            outputs.session_replay_main_topic.as_str(),
            outputs.session_replay_overflow_topic.as_str(),
            outputs.heatmaps_topic.as_str(),
            outputs.client_warnings_topic.as_str(),
            outputs.error_tracking_topic.as_str(),
            outputs.dlq_topic.as_str(),
            outputs.ai_main_topic.as_str(),
            outputs.ai_overflow_topic.as_deref().unwrap_or_default(),
        ];
        assert!(!topics.contains(&"legacy_topic"), "{env_var} is still read");
    }

    #[test]
    fn output_producers_default_to_ingestion_and_parse_their_env_var() {
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&required_config_env()).unwrap();
        assert_eq!(
            config.outputs.analytics_main_producer,
            ProducerName::Ingestion
        );
        assert_eq!(config.outputs.custom_producer, ProducerName::Ingestion);

        let mut env = required_config_env();
        env.insert(
            "CAPTURE_OUTPUT_HEATMAPS_PRODUCER".into(),
            "WARPSTREAM".into(),
        );
        let bad: Result<Config, _> = envconfig::Envconfig::init_from_hashmap(&env);
        assert!(bad.is_err(), "an undeclared producer must fail startup");
    }

    #[test]
    fn moved_output_settings_keep_their_env_vars() {
        let mut env = required_config_env();
        env.insert("KAFKA_REPLAY_ENVELOPE_COMPRESSION".into(), "lz4".into());
        env.insert(
            "CAPTURE_OUTPUTS_COMPLETENESS_CHECK_ENABLED".into(),
            "true".into(),
        );
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        assert_eq!(
            config.replay_envelope_compression,
            super::EnvelopeCompression::Lz4
        );
        assert!(config.outputs_completeness_check_enabled);
    }

    #[test]
    fn ai_lane_predicate_binds_to_its_env_var_and_defaults_to_allowlist() {
        // Unset must mean `allowlist` so the toggle is a no-op until an env opts in.
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&required_config_env()).unwrap();
        assert_eq!(config.ai_lane_predicate, AiLanePredicate::Allowlist);

        let mut env = required_config_env();
        env.insert("CAPTURE_AI_LANE_PREDICATE".into(), "prefix".into());
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        assert_eq!(config.ai_lane_predicate, AiLanePredicate::Prefix);

        env.insert("CAPTURE_AI_LANE_PREDICATE".into(), "everything".into());
        let bad: Result<Config, _> = envconfig::Envconfig::init_from_hashmap(&env);
        assert!(
            bad.is_err(),
            "an unknown predicate must fail startup, not silently fall back"
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
}
