use std::sync::atomic::{AtomicUsize, Ordering};

use aws_config::{BehaviorVersion, Region};
use common_continuous_profiling::ContinuousProfilingConfig;
use common_kafka::config::KafkaConfig;
use envconfig::Envconfig;
use tracing::{info, warn};

// TODO - I'm just too lazy to pipe this all the way through the resolve call stack
pub static FRAME_CONTEXT_LINES: AtomicUsize = AtomicUsize::new(15);
pub static BATCH_APPLY_CONCURRENCY: AtomicUsize = AtomicUsize::new(64);

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,

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

    #[envconfig(default = "cdp_internal_events")]
    pub internal_events_topic: String,

    #[envconfig(default = "clickhouse_error_tracking_fingerprint_issue_state")]
    pub fingerprint_issue_state_topic: String,

    #[envconfig(default = "document_embeddings_input")]
    pub embedding_worker_topic: String,

    #[envconfig(default = "postgres://posthog:posthog@localhost:5432/posthog")]
    pub database_url: String,

    // Rust service connect directly to postgres, not via pgbouncer, so we keep this low
    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    // cymbal makes HTTP get requests to auto-resolve sourcemaps - and follows redirects. To protect against SSRF, we only allow requests to public URLs by default
    #[envconfig(default = "false")]
    pub allow_internal_ips: bool,

    #[envconfig(default = "30")]
    pub sourcemap_timeout_seconds: u64,

    #[envconfig(default = "5")]
    pub sourcemap_connect_timeout_seconds: u64,

    #[envconfig(default = "100000000")] // 100MB - in prod, we should use closer to 1-10GB
    pub symbol_store_cache_max_bytes: usize,

    #[envconfig(default = "http://127.0.0.1:19000")] // minio
    pub object_storage_endpoint: String,

    #[envconfig(default = "symbol_sets")]
    pub object_storage_bucket: String,

    #[envconfig(default = "us-east-1")]
    pub object_storage_region: String,

    #[envconfig(default = "object_storage_root_user")]
    pub object_storage_access_key_id: String,

    #[envconfig(default = "object_storage_root_password")]
    pub object_storage_secret_access_key: String,

    #[envconfig(default = "false")] // Enable for MinIO compatibility
    pub object_storage_force_path_style: bool,

    #[envconfig(default = "symbolsets")]
    pub ss_prefix: String,

    #[envconfig(default = "600")]
    pub issue_cache_ttl_seconds: u64,

    #[envconfig(default = "100000")]
    pub frame_cache_size: u64,

    #[envconfig(default = "600")]
    pub frame_cache_ttl_seconds: u64,

    // When we resolve a frame, we put it in PG, so other instances of cymbal can
    // use it, or so we can re-use it after a restart. This is the TTL for that,
    // after this many minutes we'll discard saved resolution results and re-resolve
    // TODO - 10 minutes is too short for production use, it's only twice as long as
    // our in-memory caching. We should do at least an hour once we release
    #[envconfig(default = "10")]
    pub frame_result_ttl_minutes: u32,

    // Maximum number of lines of pre and post context to get per frame
    #[envconfig(default = "15")]
    pub context_line_count: usize,

    // Maximum number of in-flight futures for a single `Batch::apply_func` call.
    // This is a per-call-site limit, not a global pipeline-wide concurrency cap.
    #[envconfig(default = "64")]
    pub batch_apply_concurrency: usize,

    // Global maximum number of concurrent symbol resolution operations.
    // This limiter is shared across frame and exception symbol resolution paths.
    #[envconfig(default = "64")]
    pub symbol_resolution_concurrency: usize,

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

    #[envconfig(from = "ISSUE_BUCKETS_REDIS_URL", default = "redis://localhost:6379/")]
    pub issue_buckets_redis_url: String,

    #[envconfig(default = "100")]
    pub redis_response_timeout_ms: u64,

    #[envconfig(default = "5000")]
    pub redis_connection_timeout_ms: u64,

    // Comma separated list of team IDs that can receive spike alerts.
    // If empty, all teams can receive alerts
    #[envconfig(default = "")]
    pub spike_alert_enabled_team_ids: String,

    // Internal API for signal emission
    #[envconfig(default = "")]
    pub signals_api_base_url: String,

    #[envconfig(default = "")]
    pub internal_api_secret: String,

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

impl Config {
    pub fn init_with_defaults() -> Result<Self, envconfig::Error> {
        let res = Self::init_from_env()?;
        init_global_state(&res);
        Ok(res)
    }
}

pub fn init_global_state(config: &Config) {
    FRAME_CONTEXT_LINES.store(config.context_line_count, Ordering::Relaxed);
    BATCH_APPLY_CONCURRENCY.store(config.batch_apply_concurrency.max(1), Ordering::Relaxed);
}

pub async fn get_aws_config(config: &Config) -> aws_sdk_s3::Config {
    // If we have a role ARN and token file, which are added to the container due to the SA annotation we use in prod
    if std::env::var("AWS_ROLE_ARN").is_ok() && std::env::var("AWS_WEB_IDENTITY_TOKEN_FILE").is_ok()
    {
        info!("AWS role and token file detected, config loaded from environment variables");
        // Use default aws config loading behaviour, which should pick up the role-based credentials. We
        // assume region and endpoint will be properly set due to SA annotation. Behaviour version will
        // be latest due to config crate feature flag
        aws_sdk_s3::config::Builder::from(&aws_config::load_from_env().await)
            .force_path_style(config.object_storage_force_path_style)
            .build()
    } else {
        warn!("Falling back to building config from explicit environment variables");
        // Fall back to building our config from the explicit environment variables we use in local dev
        let env_credentials = aws_sdk_s3::config::Credentials::new(
            &config.object_storage_access_key_id,
            &config.object_storage_secret_access_key,
            None,
            None,
            "environment",
        );
        aws_sdk_s3::config::Builder::new()
            .region(Region::new(config.object_storage_region.clone()))
            .endpoint_url(&config.object_storage_endpoint)
            .credentials_provider(env_credentials)
            .behavior_version(BehaviorVersion::latest())
            .force_path_style(config.object_storage_force_path_style)
            .build()
    }
}
