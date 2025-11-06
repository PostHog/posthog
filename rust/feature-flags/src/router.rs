use std::{future::ready, sync::Arc};

use crate::billing_limiters::{FeatureFlagsLimiter, SessionReplayLimiter};
use crate::database_pools::DatabasePools;
use axum::{
    http::{Method, StatusCode},
    routing::{any, get},
    Router,
};
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
    // Shared Redis for non-critical path (analytics counters, billing limits)
    pub redis_reader: Arc<dyn RedisClient + Send + Sync>,
    pub redis_writer: Arc<dyn RedisClient + Send + Sync>,
    // Dedicated Redis for critical path (team cache + flags cache)
    pub flags_redis_reader: Arc<dyn RedisClient + Send + Sync>,
    pub flags_redis_writer: Arc<dyn RedisClient + Send + Sync>,
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
}

#[allow(clippy::too_many_arguments)]
pub fn router<RR, RW, FRR, FRW>(
    redis_reader: Arc<RR>,
    redis_writer: Arc<RW>,
    flags_redis_reader: Arc<FRR>,
    flags_redis_writer: Arc<FRW>,
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
    FRR: RedisClient + Send + Sync + 'static,
    FRW: RedisClient + Send + Sync + 'static,
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

    // Clone database_pools for readiness check before moving into State
    let db_pools_for_readiness = database_pools.clone();

    let state = State {
        redis_reader,
        redis_writer,
        flags_redis_reader,
        flags_redis_writer,
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
        .route(
            "/_readiness",
            get(move || readiness(db_pools_for_readiness.clone())),
        )
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

pub async fn readiness(
    database_pools: Arc<DatabasePools>,
) -> Result<&'static str, (StatusCode, String)> {
    // Check all pools and collect errors
    let pools = [
        ("non_persons_reader", &database_pools.non_persons_reader),
        ("non_persons_writer", &database_pools.non_persons_writer),
        ("persons_reader", &database_pools.persons_reader),
        ("persons_writer", &database_pools.persons_writer),
    ];

    for (name, pool) in pools {
        let mut conn = pool.acquire().await.map_err(|e| {
            (
                StatusCode::SERVICE_UNAVAILABLE,
                format!("{name} pool unavailable: {e}"),
            )
        })?;

        // If test_before_acquire is false, explicitly test the connection
        if !database_pools.test_before_acquire {
            sqlx::query("SELECT 1")
                .execute(&mut *conn)
                .await
                .map_err(|e| {
                    (
                        StatusCode::SERVICE_UNAVAILABLE,
                        format!("{name} connection test failed: {e}"),
                    )
                })?;
        }
    }

    Ok("ready")
}

pub async fn index() -> &'static str {
    "feature flags"
}
