use std::{future::ready, sync::Arc};

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::database_pools::DatabasePools;
use axum::{
    http::Method,
    routing::{any, get},
    Router,
};
use common_cache::{CacheConfig, ReadThroughCache};
use common_cookieless::CookielessManager;
use common_geoip::GeoIpClient;
use common_metrics::{setup_metrics_recorder, track_metrics};
use common_redis::Client as RedisClient;
use health::HealthRegistry;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{
    cors::{AllowHeaders, AllowOrigin, CorsLayer},
    trace::TraceLayer,
};

use crate::{
    api::{
        endpoint, flag_definitions,
        flag_definitions_rate_limiter::FlagDefinitionsRateLimiter,
        flags_rate_limiter::{FlagsRateLimiter, IpRateLimiter},
    },
    cohorts::cohort_cache_manager::CohortCacheManager,
    config::{Config, TeamIdCollection},
    metrics::{
        consts::{FLAG_DEFINITIONS_RATE_LIMITED_COUNTER, FLAG_DEFINITIONS_REQUESTS_COUNTER},
        utils::team_id_label_filter,
    },
};

#[derive(Clone)]
pub struct State {
    pub redis_reader: Arc<dyn RedisClient + Send + Sync>,
    pub redis_writer: Arc<dyn RedisClient + Send + Sync>,
    pub database_pools: Arc<DatabasePools>,
    pub cohort_cache_manager: Arc<CohortCacheManager>,
    pub geoip: Arc<GeoIpClient>,
    pub team_ids_to_track: TeamIdCollection,
    pub feature_flags_billing_limiter: FeatureFlagsLimiter,
    pub session_replay_billing_limiter: SessionReplayLimiter,
    pub cookieless_manager: Arc<CookielessManager>,
    pub flag_definitions_limiter: FlagDefinitionsRateLimiter,
    pub config: Config,
    pub flags_rate_limiter: FlagsRateLimiter,
    pub ip_rate_limiter: IpRateLimiter,
    pub team_token_cache: Arc<ReadThroughCache>,
    pub team_secret_token_cache: Arc<ReadThroughCache>,
}

#[allow(clippy::too_many_arguments)]
pub fn router<RR, RW>(
    redis_reader: Arc<RR>,
    redis_writer: Arc<RW>,
    database_pools: Arc<DatabasePools>,
    cohort_cache: Arc<CohortCacheManager>,
    geoip: Arc<GeoIpClient>,
    liveness: HealthRegistry,
    feature_flags_billing_limiter: FeatureFlagsLimiter,
    session_replay_billing_limiter: SessionReplayLimiter,
    cookieless_manager: Arc<CookielessManager>,
    config: Config,
) -> Router
where
    RR: RedisClient + Send + Sync + 'static,
    RW: RedisClient + Send + Sync + 'static,
{
    // Initialize flag definitions rate limiter with default and custom team rates
    let flag_definitions_limiter = FlagDefinitionsRateLimiter::new(
        config.flag_definitions_default_rate_per_minute,
        config.flag_definitions_rate_limits.0.clone(),
        FLAG_DEFINITIONS_REQUESTS_COUNTER,
        FLAG_DEFINITIONS_RATE_LIMITED_COUNTER,
    )
    .expect("Failed to initialize flag definitions rate limiter");

    // Initialize token-based rate limiter with configuration
    let flags_rate_limiter = FlagsRateLimiter::new(
        *config.flags_rate_limit_enabled,
        *config.flags_rate_limit_log_only,
        config.flags_bucket_replenish_rate,
        config.flags_bucket_capacity,
    )
    .unwrap_or_else(|e| {
        panic!(
            "Invalid token-based rate limit configuration: {e}. \
             Check FLAGS_BUCKET_REPLENISH_RATE (must be > 0) and FLAGS_BUCKET_CAPACITY (must be > 0)"
        )
    });

    // Initialize IP-based rate limiter with configuration
    let ip_rate_limiter = IpRateLimiter::new(
        *config.flags_ip_rate_limit_enabled,
        *config.flags_ip_rate_limit_log_only,
        config.flags_ip_replenish_rate,
        config.flags_ip_burst_size,
    )
    .unwrap_or_else(|e| {
        panic!(
            "Invalid IP-based rate limit configuration: {e}. \
             Check FLAGS_IP_REPLENISH_RATE (must be > 0) and FLAGS_IP_BURST_SIZE (must be > 0)"
        )
    });

    // Initialize team token cache (for regular API token lookups)
    let team_token_cache_config =
        CacheConfig::new("posthog:1:team_token:", Some(config.team_cache_ttl_seconds));
    let team_token_cache = Arc::new(ReadThroughCache::new(
        redis_reader.clone(),
        redis_writer.clone(),
        team_token_cache_config,
        None, // TODO: Add negative cache via config.create_negative_cache() to prevent repeated DB queries for invalid tokens
    ));

    // Initialize team secret token cache (for secret API token lookups)
    let team_secret_token_cache_config = CacheConfig::new(
        "posthog:1:team_secret_token:",
        Some(config.team_cache_ttl_seconds),
    );
    let team_secret_token_cache = Arc::new(ReadThroughCache::new(
        redis_reader.clone(),
        redis_writer.clone(),
        team_secret_token_cache_config,
        None, // TODO: Add negative cache via config.create_negative_cache() to prevent repeated DB queries for invalid tokens
    ));

    let state = State {
        redis_reader,
        redis_writer,
        database_pools,
        cohort_cache_manager: cohort_cache,
        geoip,
        team_ids_to_track: config.team_ids_to_track.clone(),
        feature_flags_billing_limiter,
        session_replay_billing_limiter,
        cookieless_manager,
        flag_definitions_limiter,
        config: config.clone(),
        flags_rate_limiter,
        ip_rate_limiter,
        team_token_cache,
        team_secret_token_cache,
    };

    // Very permissive CORS policy, as old SDK versions
    // and reverse proxies might send funky headers.
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS, Method::HEAD])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    // liveness/readiness checks
    let status_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    // flags endpoint
    // IP rate limiting is now handled in the endpoint handler for better control and log-only mode support
    let flags_router = Router::new()
        .route("/flags", any(endpoint::flags))
        .route("/flags/", any(endpoint::flags))
        .route(
            "/flags/definitions",
            any(flag_definitions::flags_definitions),
        )
        .route(
            "/flags/definitions/",
            any(flag_definitions::flags_definitions),
        )
        .route("/decide", any(endpoint::flags))
        .route("/decide/", any(endpoint::flags))
        .layer(ConcurrencyLimitLayer::new(config.max_concurrency));

    let router = Router::new()
        .merge(status_router)
        .merge(flags_router)
        .layer(TraceLayer::new_for_http())
        .layer(cors)
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Global metrics recorders can play poorly with e.g. tests
    // In other words, only turn these on in production
    if config.enable_metrics {
        common_metrics::set_label_filter(team_id_label_filter(config.team_ids_to_track.clone()));
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}

pub async fn index() -> &'static str {
    "feature flags"
}
