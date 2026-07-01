use std::sync::atomic::{AtomicUsize, Ordering};

use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;

use crate::core::config::ResolverConfig;

pub static BATCH_APPLY_CONCURRENCY: AtomicUsize = AtomicUsize::new(64);

#[derive(Envconfig, Clone)]
pub struct ProcessingConfig {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

    /// Shared symbol-resolution config (Postgres, object storage, frame cache,
    /// sourcemap fetching). Both modes read this slice; it lives in `core` so
    /// resolution mode never pulls in the processing-only knobs below.
    #[envconfig(nested = true)]
    pub resolver: ResolverConfig,

    #[envconfig(from = "BIND_HOST", default = "::")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3305")]
    pub port: u16,

    pub posthog_api_key: Option<String>,

    #[envconfig(default = "https://us.i.posthog.com/capture")]
    pub posthog_endpoint: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,

    // Optional override for the brokers used to produce `cdp_internal_events`. When set,
    // cymbal opens a second producer pointed at this host list (used for the warpstream-cyclotron
    // VC, where the hog-functions consumer reads). When unset, internal events go through the
    // primary `kafka` producer like everything else.
    #[envconfig(from = "CYMBAL_CYCLOTRON_KAFKA_HOSTS")]
    pub cyclotron_kafka_hosts: Option<String>,

    // Optional TLS override for the cyclotron producer. When unset, the cyclotron producer
    // inherits `KAFKA_TLS` from the primary kafka config; set this to flip TLS independently
    // (e.g. primary on plaintext warpstream-shared, secondary on SSL MSK).
    #[envconfig(from = "CYMBAL_CYCLOTRON_KAFKA_TLS")]
    pub cyclotron_kafka_tls: Option<bool>,

    // Optional override for the brokers used to produce `clickhouse_app_metrics2`. When set,
    // cymbal opens a dedicated producer pointed at this host list (the warpstream-ingestion VC,
    // where ClickHouse consumes app_metrics2). When unset, app metrics go through the primary
    // `kafka` producer — which only carries that topic where the cluster has it (e.g. local dev).
    #[envconfig(from = "CYMBAL_APP_METRICS_KAFKA_HOSTS")]
    pub app_metrics_kafka_hosts: Option<String>,

    // Optional TLS override for the app-metrics producer. When unset, it inherits `KAFKA_TLS`
    // from the primary kafka config.
    #[envconfig(from = "CYMBAL_APP_METRICS_KAFKA_TLS")]
    pub app_metrics_kafka_tls: Option<bool>,

    #[envconfig(default = "cdp_internal_events")]
    pub internal_events_topic: String,

    #[envconfig(default = "clickhouse_error_tracking_fingerprint_issue_state")]
    pub fingerprint_issue_state_topic: String,

    #[envconfig(default = "document_embeddings_input")]
    pub embedding_worker_topic: String,

    #[envconfig(default = "error_tracking_ingestion_notifications")]
    pub ingestion_notifications_topic: String,

    #[envconfig(default = "600")]
    pub issue_cache_ttl_seconds: u64,

    // Maximum number of in-flight futures for a single `Batch::apply_func` call.
    // This is a per-call-site limit, not a global pipeline-wide concurrency cap.
    #[envconfig(default = "64")]
    pub batch_apply_concurrency: usize,

    // Maximum number of in-flight /process requests accepted by the API.
    // Requests above this limit are rejected with 429 to apply backpressure.
    #[envconfig(default = "128")]
    pub process_max_in_flight_requests: usize,

    #[envconfig(default = "60000")]
    pub process_slow_log_threshold_ms: u64,

    #[envconfig(default = "300")]
    pub team_cache_ttl_secs: u64,

    #[envconfig(default = "10000")]
    pub max_team_cache_size: u64,

    #[envconfig(default = "300")]
    pub assignment_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_assignment_rule_cache_size: u64,

    #[envconfig(default = "300")]
    pub grouping_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_grouping_rule_cache_size: u64,

    #[envconfig(default = "300")]
    pub suppression_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_suppression_rule_cache_size: u64,

    #[envconfig(default = "300")]
    pub bypass_rule_cache_ttl_secs: u64,

    #[envconfig(default = "100000")]
    // The maximum number of bytecode operations we'll store in the cache, across all rules, across all teams
    pub max_bypass_rule_cache_size: u64,

    #[envconfig(from = "ISSUE_BUCKETS_REDIS_URL", default = "redis://localhost:6379/")]
    pub issue_buckets_redis_url: String,

    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,

    #[envconfig(from = "ERROR_TRACKING_CYMBAL_RATE_LIMITER_ENABLED", default = "false")]
    pub error_tracking_rate_limiter_enabled: bool,

    #[envconfig(
        from = "ERROR_TRACKING_CYMBAL_RATE_LIMITER_REDIS_URL",
        default = "redis://localhost:6379/"
    )]
    pub error_tracking_rate_limiter_redis_url: String,

    #[envconfig(
        from = "ERROR_TRACKING_CYMBAL_RATE_LIMITER_KEY_PREFIX",
        default = "@posthog/error-tracking-cymbal-rate-limiter"
    )]
    pub error_tracking_rate_limiter_key_prefix: String,

    #[envconfig(
        from = "ERROR_TRACKING_CYMBAL_RATE_LIMITER_BUCKET_TTL_SECONDS",
        default = "86400"
    )]
    pub error_tracking_rate_limiter_bucket_ttl_seconds: u64,

    // Comma separated list of team IDs the error-tracking rate limiter applies to.
    // If empty, it applies to all teams (that have limits configured).
    #[envconfig(
        from = "ERROR_TRACKING_CYMBAL_RATE_LIMITER_ENABLED_TEAM_IDS",
        default = ""
    )]
    pub error_tracking_rate_limiter_enabled_team_ids: String,

    // Comma separated list of team IDs that can receive spike alerts.
    // If empty, all teams can receive alerts
    #[envconfig(default = "")]
    pub spike_alert_enabled_team_ids: String,

    // ----------------------------------------------------------------------
    // Remote resolution (cymbal.resolution.v1) — Batch 3 client integration.
    //
    // When `remote_resolution_enabled` is true, cymbal routes exception-level
    // symbol resolution through the configured `cymbal-resolution` service
    // pool instead of running the local resolver inline. There is no silent
    // local fallback: if the pool can't satisfy the request, the stage
    // surfaces the failure to its caller. Local mode (the default) is
    // unchanged.
    // ----------------------------------------------------------------------
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_ENABLED", default = "false")]
    pub remote_resolution_enabled: bool,

    /// Hostname of the cymbal-resolution service. Resolved via DNS, then each
    /// returned address gets its own gRPC channel in the endpoint pool.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_HOST", default = "")]
    pub remote_resolution_host: String,

    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_PORT", default = "50061")]
    pub remote_resolution_port: u16,

    /// How often to re-resolve the configured hostname and refresh the pool.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_DNS_REFRESH_SECS", default = "30")]
    pub remote_resolution_dns_refresh_secs: u64,

    /// Per-call deadline for a single Resolve RPC, in milliseconds. The
    /// stage enforces this independently of any transport-level keepalive.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_DEADLINE_MS", default = "15000")]
    pub remote_resolution_deadline_ms: u64,

    /// Connection establishment timeout for a single endpoint, in
    /// milliseconds. Endpoints that exceed this are skipped for routing.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_CONNECT_TIMEOUT_MS", default = "1000")]
    pub remote_resolution_connect_timeout_ms: u64,

    /// Maximum number of caller-side retries against the endpoint pool when
    /// transport, load shedding, or explicit `retry` outcomes are observed.
    /// `0` disables retries; the first attempt still runs.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_MAX_RETRIES", default = "2")]
    pub remote_resolution_max_retries: u32,

    /// Initial backoff applied between caller-side retries, in milliseconds.
    /// Each subsequent attempt doubles the wait (capped at
    /// `CYMBAL_REMOTE_RESOLUTION_RETRY_MAX_BACKOFF_MS`), plus up to ~50% random
    /// jitter so a fleet of cymbal pods does not synchronize retries against a
    /// briefly-overloaded upstream.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_RETRY_BACKOFF_MS", default = "50")]
    pub remote_resolution_retry_backoff_ms: u64,

    /// Upper bound on the retry backoff window, in milliseconds. The exponential
    /// schedule never sleeps longer than this between attempts.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_RETRY_MAX_BACKOFF_MS",
        default = "1000"
    )]
    pub remote_resolution_retry_max_backoff_ms: u64,

    /// Initial duration to temporarily remove an endpoint from routing after it
    /// returns a per-item overload outcome. `0` keeps the legacy per-item-only
    /// reroute behavior.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MS",
        default = "100"
    )]
    pub remote_resolution_overload_ejection_ms: u64,

    /// Maximum endpoint ejection duration after repeated overloads.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_MAX_MS",
        default = "5000"
    )]
    pub remote_resolution_overload_ejection_max_ms: u64,

    /// Quiet window after which an endpoint's overload ejection duration resets
    /// to the initial value.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_OVERLOAD_EJECTION_DECAY_MS",
        default = "30000"
    )]
    pub remote_resolution_overload_ejection_decay_ms: u64,

    /// Deterministic event-level rollout sample for remote resolution.
    /// Defaults to `0.0` so flipping `CYMBAL_REMOTE_RESOLUTION_ENABLED=true`
    /// alone does not start sending traffic — the rollout has to be ramped
    /// explicitly. Values outside 0.0..=1.0 are clamped by
    /// `RemoteResolutionConfig`, matching the defensive normalization used
    /// by adjacent duration knobs.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_SAMPLE_RATE", default = "0.0")]
    pub remote_resolution_sample_rate: f64,

    /// Flattens remote resolution routing across the rendezvous-ranked candidate
    /// list. `0.0` sends all traffic to the top-ranked endpoint, `1.0` is
    /// uniform across all candidates, and intermediate values decay by rank.
    #[envconfig(from = "CYMBAL_REMOTE_RESOLUTION_ROUTING_JITTER", default = "0.0")]
    pub remote_resolution_routing_jitter: f64,

    /// Maximum number of remote resolution items that can concurrently wait
    /// for a pod to accept routing ownership.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_ROUTING_ACCEPTANCE_CONCURRENCY",
        default = "10"
    )]
    pub remote_resolution_routing_acceptance_concurrency: usize,

    /// Tick cadence hint sent on `SubscribeRequest.tick_hint_ms` to the
    /// cymbal-resolution freshness/draining stream. The server clamps to its own bounds
    /// (see cymbal-resolution `SUBSCRIBE_MIN_TICK_MS`/`SUBSCRIBE_MAX_TICK_MS`),
    /// so this is only a hint.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_TICK_HINT_MS",
        default = "1000"
    )]
    pub remote_resolution_subscribe_tick_hint_ms: u64,

    /// Backoff between reconnect attempts when a per-endpoint subscription
    /// stream terminates, in milliseconds. Kept small so a transient blip
    /// doesn't keep the pool blind for long.
    #[envconfig(
        from = "CYMBAL_REMOTE_RESOLUTION_SUBSCRIBE_RECONNECT_BACKOFF_MS",
        default = "500"
    )]
    pub remote_resolution_subscribe_reconnect_backoff_ms: u64,
}

impl ProcessingConfig {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        init_global_state(&res);
        Ok(res)
    }
}

pub fn init_global_state(config: &ProcessingConfig) {
    BATCH_APPLY_CONCURRENCY.store(config.batch_apply_concurrency.max(1), Ordering::Relaxed);
}
